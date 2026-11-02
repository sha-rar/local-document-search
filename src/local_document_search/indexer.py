"""Discover files and maintain an incremental index."""

import fnmatch
import hashlib
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from stat import IO_REPARSE_TAG_MOUNT_POINT

from .extractors import ExtractionError, extract_text, is_supported
from .storage import DocumentRecord, IndexStore

# Commit after this many changed files or seconds, whichever comes first, so searches
# see progress without paying for a disk sync per file.
COMMIT_EVERY = 1000
COMMIT_INTERVAL = 2.0
HASH_CHUNK_SIZE = 1024 * 1024
# Files up to this size are read once and the bytes reused for hashing and extraction.
WHOLE_FILE_LIMIT = 64 * 1024 * 1024
# Larger documents are skipped: extracting them could exhaust memory, and a file this big
# is almost always a log or data dump rather than something to search.
MAX_EXTRACT_SIZE = 200 * 1024 * 1024

logger = logging.getLogger(__name__)


@dataclass
class IndexReport:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    moved: int = 0
    removed: int = 0
    unsupported: int = 0
    failed: list[tuple[Path, str]] = field(default_factory=list)
    cancelled: bool = False


class IndexCancelled(Exception):
    """Raised at a checkpoint once indexing has been cancelled."""


class IndexControl:
    """Lets another thread pause, resume or cancel a running index operation.

    The indexer calls ``checkpoint()`` between files; it blocks while paused and raises
    ``IndexCancelled`` once cancelled.
    """

    def __init__(self):
        self._cancelled = threading.Event()
        self._running = threading.Event()
        self._running.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def paused(self) -> bool:
        return not self._running.is_set()

    def cancel(self) -> None:
        self._cancelled.set()
        self._running.set()  # wake a paused indexer so it can stop

    def pause(self) -> None:
        if not self.cancelled:
            self._running.clear()

    def resume(self) -> None:
        self._running.set()

    def checkpoint(self) -> None:
        self._running.wait()
        if self._cancelled.is_set():
            raise IndexCancelled


@dataclass(frozen=True)
class Exclusions:
    """What to leave out of the index.

    ``folders`` are skipped with everything under them. ``patterns`` are shell-style
    wildcards (``*``, ``?``, ``[abc]``) matched case-insensitively against each file and
    folder name, e.g. ``~$*`` or ``node_modules``. ``extensions`` skips file types.
    """

    folders: tuple[Path, ...] = ()
    patterns: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()

    @classmethod
    def from_any(cls, value: "Exclusions | Iterable[Path]") -> "Exclusions":
        """Accept an ``Exclusions`` or, for convenience, a plain iterable of folders."""
        return value if isinstance(value, cls) else cls(folders=tuple(value))

    def resolved(self) -> "Exclusions":
        return Exclusions(
            folders=tuple(Path(folder).resolve() for folder in self.folders),
            patterns=tuple(pattern.strip().lower() for pattern in self.patterns if pattern.strip()),
            extensions=tuple(_normalize_extension(ext) for ext in self.extensions if ext.strip()),
        )

    def matches_name(self, name: str) -> bool:
        name = name.lower()
        return any(fnmatch.fnmatchcase(name, pattern) for pattern in self.patterns)

    def excludes_dir(self, path: Path) -> bool:
        return is_excluded(path, self.folders) or self.matches_name(path.name)

    def excludes_file(self, path: Path) -> bool:
        return path.suffix.lower() in self.extensions or self.matches_name(path.name)

    def excludes_path(self, path: Path, root: Path) -> bool:
        """Whether ``path`` (a file or folder under ``root``) or any folder above it is excluded."""
        if is_excluded(path, self.folders):
            return True
        relative = path.relative_to(root).parts if path.is_relative_to(root) else (path.name,)
        if any(self.matches_name(part) for part in relative):
            return True
        return not path.is_dir() and path.suffix.lower() in self.extensions


def _normalize_extension(extension: str) -> str:
    extension = extension.strip().lower()
    return extension if extension.startswith(".") else "." + extension


def is_excluded(path: Path, excluded: Iterable[Path]) -> bool:
    return any(path.is_relative_to(folder) for folder in excluded)


def scan_files(
    root: Path,
    errors: list[tuple[Path, str]] | None = None,
    exclude: Exclusions | Iterable[Path] = (),
) -> Iterator[os.DirEntry]:
    """Recursively yield ``DirEntry`` objects for regular files under ``root``.

    Excluded folders and files, symlinks and junctions are skipped; unreadable directories
    go to ``errors``. On Windows ``entry.stat()`` is answered from the directory listing,
    so it costs no extra system call.
    """
    root = Path(root).resolve()
    exclusions = Exclusions.from_any(exclude).resolved()
    if is_excluded(root, exclusions.folders):
        return
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink() or _is_junction(entry):
                            continue
                        if entry.is_dir():
                            child = Path(entry.path)
                            if not exclusions.excludes_dir(child):
                                stack.append(child)
                        elif entry.is_file() and not exclusions.excludes_file(Path(entry.path)):
                            yield entry
                    except OSError:
                        continue
        except OSError as exc:
            if errors is not None:
                errors.append((directory, exc.strerror or str(exc)))


def _is_junction(entry: os.DirEntry) -> bool:
    # ``DirEntry.is_junction`` only exists from Python 3.12; this is the check it makes.
    # Only mount points count: OneDrive placeholders are reparse points too, but are
    # ordinary folders to index.
    tag = getattr(entry.stat(follow_symlinks=False), "st_reparse_tag", 0)
    return tag == IO_REPARSE_TAG_MOUNT_POINT


def iter_files(
    root: Path,
    errors: list[tuple[Path, str]] | None = None,
    exclude: Exclusions | Iterable[Path] = (),
) -> Iterator[Path]:
    """Recursively yield regular files under ``root`` that ``exclude`` doesn't rule out."""
    for entry in scan_files(root, errors, exclude):
        yield Path(entry.path)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def find_moved_source(store: IndexStore, size: int, content_hash: str) -> DocumentRecord | None:
    """Return an indexed document with identical content whose file no longer exists."""
    for candidate in store.find_by_content(size, content_hash):
        if not Path(candidate.path).exists():
            return candidate
    return None


def clean_text(text: str) -> str:
    """Make extracted text storable: unpaired surrogates (seen in some PDFs) become "?"."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return text.encode("utf-8", "replace").decode("utf-8")
    return text


def _record_failure(report: IndexReport, path: Path, reason: str) -> None:
    report.failed.append((path, reason))
    logger.warning(
        "Could not index file",
        extra={"event": "file_failed", "path": str(path), "reason": reason},
    )


def _index_file_safely(
    store: IndexStore,
    path: Path,
    report: IndexReport,
    existing: DocumentRecord | None,
    stat: os.stat_result,
    known: dict[str, DocumentRecord] | None = None,
) -> bool:
    """``_index_file``, but an unexpected error affects only this file.

    Database errors still propagate: they mean the index itself is unusable, and every
    following file would fail the same way.
    """
    try:
        return _index_file(store, path, report, existing, stat, known)
    except sqlite3.Error:
        raise
    except Exception as exc:  # noqa: BLE001 - includes MemoryError and parser bugs
        report.failed.append((path, f"unexpected error: {type(exc).__name__}: {exc}"))
        logger.exception(
            "Unexpected error indexing file",
            extra={"event": "file_error", "path": str(path), "error": type(exc).__name__},
        )
        return False


def _index_file(
    store: IndexStore,
    path: Path,
    report: IndexReport,
    existing: DocumentRecord | None,
    stat: os.stat_result,
    known: dict[str, DocumentRecord] | None = None,
) -> bool:
    """Bring one supported file's entry up to date; return whether the database changed.

    ``existing`` is the file's current record, if any. When a moved file takes over a
    record, that record's old path is dropped from ``known``.
    """
    key = str(path)
    stat_unchanged = (
        existing is not None and existing.mtime == stat.st_mtime and existing.size == stat.st_size
    )
    if stat_unchanged and existing.content_hash is not None:
        report.unchanged += 1
        return False
    data = None
    try:
        if stat.st_size <= WHOLE_FILE_LIMIT:
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
        else:
            digest = file_hash(path)
    except OSError as exc:
        _record_failure(report, path, exc.strerror or str(exc))
        return False

    if existing is not None and (stat_unchanged or existing.content_hash == digest):
        # Same bytes (e.g. only touched, or indexed before hashes were stored).
        store.update_file_state(existing.id, stat.st_mtime, stat.st_size, digest)
        report.unchanged += 1
    elif existing is None and (source := find_moved_source(store, stat.st_size, digest)):
        store.move_document(source.id, key, stat.st_mtime)
        if known is not None:
            known.pop(source.path, None)
        report.moved += 1
    else:
        if stat.st_size > MAX_EXTRACT_SIZE:
            size_mb = stat.st_size / 1024**2
            _record_failure(report, path, f"too large to index ({size_mb:.0f} MB)")
            return False
        try:
            text = extract_text(path, data)
        except ExtractionError as exc:
            _record_failure(report, path, str(exc))
            return False
        store.upsert_document(key, stat.st_mtime, stat.st_size, clean_text(text), digest)
        if existing:
            report.updated += 1
        else:
            report.added += 1
    return True


def index_folder(
    store: IndexStore,
    root: Path,
    progress: Callable[[Path], None] | None = None,
    exclude: Exclusions | Iterable[Path] = (),
    control: IndexControl | None = None,
) -> IndexReport:
    """Index supported files under ``root``, skipping anything ``exclude`` rules out.

    Unchanged files are skipped, moved or renamed files keep their extracted text, and
    documents under ``root`` that no longer exist or are now excluded are removed.

    If ``control`` is cancelled, work done so far is kept and ``report.cancelled`` is set;
    removal is skipped because the scan didn't see every file.
    """
    root = Path(root).resolve()
    report = IndexReport()
    started = time.monotonic()
    logger.info("Indexing folder", extra={"event": "scan_started", "folder": str(root)})
    # One query up front instead of a lookup per file.
    known = store.documents_under(root)
    seen: set[str] = set()
    pending = 0
    last_commit = time.monotonic()

    try:
        for entry in scan_files(root, report.failed, exclude):
            path = Path(entry.path)
            if not is_supported(path):
                report.unsupported += 1
                continue
            if control:
                if control.paused:
                    # Make finished work visible to searches before waiting.
                    store.commit()
                    pending = 0
                control.checkpoint()
            if progress:
                progress(path)
            key = str(path)
            seen.add(key)
            try:
                stat = entry.stat()
            except OSError as exc:
                _record_failure(report, path, exc.strerror or str(exc))
                continue
            if _index_file_safely(store, path, report, known.get(key), stat, known):
                pending += 1
            if pending and (
                pending >= COMMIT_EVERY or time.monotonic() - last_commit >= COMMIT_INTERVAL
            ):
                store.commit()
                pending = 0
                last_commit = time.monotonic()
    except IndexCancelled:
        store.commit()
        report.cancelled = True
        _log_summary("Indexing cancelled", "scan_cancelled", root, report, started)
        return report

    removed = [record.id for key, record in known.items() if key not in seen]
    store.delete_ids(removed)
    report.removed = len(removed)
    store.commit()
    _log_summary("Indexed folder", "scan_finished", root, report, started)
    return report


def _log_summary(
    message: str, event: str, root: Path, report: IndexReport, started: float
) -> None:
    logger.info(
        message,
        extra={
            "event": event,
            "folder": str(root),
            "seconds": round(time.monotonic() - started, 2),
            "added": report.added,
            "updated": report.updated,
            "unchanged": report.unchanged,
            "moved": report.moved,
            "removed": report.removed,
            "unsupported": report.unsupported,
            "failed": len(report.failed),
        },
    )


def update_paths(
    store: IndexStore,
    paths: Iterable[Path],
    roots: Iterable[Path],
    exclude: Exclusions | Iterable[Path] = (),
) -> IndexReport:
    """Apply changes to specific files or folders, e.g. reported by a filesystem watcher.

    Paths outside ``roots`` or ruled out by ``exclude`` are ignored. Existing paths are
    indexed before missing ones are removed, so a move is recognised rather than
    re-extracted.
    """
    roots = [Path(root).resolve() for root in roots]
    excluded = Exclusions.from_any(exclude).resolved()
    report = IndexReport()

    def relevant_path(path: Path) -> bool:
        root = next((root for root in roots if path.is_relative_to(root)), None)
        return root is not None and not excluded.excludes_path(path, root)

    relevant = {Path(path) for path in paths if relevant_path(Path(path))}
    present = sorted(path for path in relevant if path.exists())
    missing = sorted(path for path in relevant if not path.exists())

    for path in present:
        files = iter_files(path, report.failed, excluded) if path.is_dir() else [path]
        for file in files:
            if not is_supported(file):
                report.unsupported += 1
                continue
            try:
                stat = file.stat()
            except OSError as exc:
                _record_failure(report, file, exc.strerror or str(exc))
                continue
            _index_file_safely(store, file, report, store.get_document(str(file)), stat)
    for path in missing:
        # A missing path may have been a file or a whole folder.
        for key in store.paths_under(path):
            store.delete_document(key)
            report.removed += 1

    store.commit()
    logger.info(
        "Applied file changes",
        extra={
            "event": "changes_applied",
            "paths": len(relevant),
            "added": report.added,
            "updated": report.updated,
            "moved": report.moved,
            "removed": report.removed,
            "failed": len(report.failed),
        },
    )
    return report


def remove_folder(store: IndexStore, root: Path, keep: Iterable[Path] = ()) -> int:
    """Remove documents under ``root`` unless they are also under a folder in ``keep``."""
    root = Path(root).resolve()
    kept = [Path(folder).resolve() for folder in keep]
    removed = 0
    for key in store.all_paths():
        path = Path(key)
        if path.is_relative_to(root) and not any(path.is_relative_to(k) for k in kept):
            store.delete_document(key)
            removed += 1
    store.commit()
    return removed


def prune_missing(store: IndexStore) -> int:
    """Remove documents whose files no longer exist anywhere; return how many were removed."""
    removed = 0
    for key in store.all_paths():
        if not Path(key).exists():
            store.delete_document(key)
            removed += 1
    store.commit()
    return removed
