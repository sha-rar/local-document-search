"""Watch folders for changes and report them in debounced batches."""

import threading
from collections.abc import Callable, Iterable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .extractors import is_supported

DEFAULT_DEBOUNCE_SECONDS = 1.0


class _ChangeCollector(FileSystemEventHandler):
    def __init__(self, on_path: Callable[[Path], None]):
        self.on_path = on_path

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.event_type in ("opened", "closed", "closed_no_write"):
            return
        # A folder's own "modified" event just echoes changes to its children.
        if event.is_directory and event.event_type == "modified":
            return
        for raw in (event.src_path, getattr(event, "dest_path", "")):
            if not raw:
                continue
            path = Path(raw)
            # Deletions can't say whether they were folders, so keep them all.
            if event.is_directory or event.event_type in ("deleted", "moved") or is_supported(path):
                self.on_path(path)


def _shutdown(observer: Observer) -> None:
    observer.stop()
    observer.join()


class FolderMonitor:
    """Recursively watches folders and calls ``on_changes`` with the paths that changed.

    Events are collected until none arrive for ``debounce`` seconds, so a burst of saves
    or a large copy becomes one batch. ``on_changes`` runs on a background thread.
    """

    def __init__(
        self,
        folders: Iterable[Path],
        on_changes: Callable[[set[Path]], None],
        debounce: float = DEFAULT_DEBOUNCE_SECONDS,
    ):
        self.folders = [Path(folder).resolve() for folder in folders]
        self.on_changes = on_changes
        self.debounce = debounce
        self._pending: set[Path] = set()
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._observer: Observer | None = None
        self._stopped = False

    @property
    def watched(self) -> list[Path]:
        """Folders actually being watched (missing folders are skipped)."""
        return [folder for folder in self.folders if folder.is_dir()] if self._observer else []

    def start(self) -> None:
        if self._observer is not None:
            return
        observer = Observer()
        handler = _ChangeCollector(self._record)
        for folder in self.folders:
            if folder.is_dir():
                observer.schedule(handler, str(folder), recursive=True)
        observer.daemon = True
        self._stopped = False
        observer.start()
        self._observer = observer

    def stop(self, wait: bool = False) -> None:
        """Stop reporting changes immediately.

        Shutting down watchdog's observer takes about a second on Windows, so unless
        ``wait`` is set it finishes on a background thread instead of blocking the caller.
        """
        if self._observer is None:
            return
        observer, self._observer = self._observer, None
        with self._lock:
            self._stopped = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._pending.clear()
        if wait:
            _shutdown(observer)
        else:
            threading.Thread(target=_shutdown, args=(observer,), daemon=True).start()

    def _record(self, path: Path) -> None:
        with self._lock:
            if self._stopped:
                return
            self._pending.add(path)
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self) -> None:
        with self._lock:
            if self._stopped:
                return
            paths, self._pending = self._pending, set()
            self._timer = None
        if paths:
            self.on_changes(paths)
