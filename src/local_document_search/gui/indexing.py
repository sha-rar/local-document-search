"""Run indexing on a worker thread so the GUI event loop stays responsive."""

import time
from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..extractors import is_supported
from ..indexer import IndexReport, index_folder, iter_files
from ..storage import IndexStore

# Minimum seconds between progress signals, so large scans don't flood the event loop.
PROGRESS_INTERVAL = 0.05

MISSING_FOLDER_REASON = "Folder not found; skipped"


class IndexWorker(QObject):
    """Indexes folders with its own database connection; lives on a ``QThread``."""

    counting = Signal()
    progress = Signal(int, int, str)  # files processed, files expected, current path
    # (list[tuple[Path, IndexReport]], list[Path] of folders that no longer exist)
    finished = Signal(object, object)
    failed = Signal(str)

    def __init__(self, db_path: Path, folders: list[Path], exclude: Iterable[Path] = ()):
        super().__init__()
        self.db_path = db_path
        self.folders = list(folders)
        self.exclude = list(exclude)

    @Slot()
    def run(self) -> None:
        reports: list[tuple[Path, IndexReport]] = []
        # Indexing a vanished folder (e.g. an unplugged drive) would delete its entries.
        present = [folder for folder in self.folders if folder.is_dir()]
        missing = [folder for folder in self.folders if folder not in present]
        try:
            self.counting.emit()
            total = sum(
                1
                for folder in present
                for path in iter_files(folder, exclude=self.exclude)
                if is_supported(path)
            )
            done = 0
            last_emit = 0.0

            def on_file(path: Path) -> None:
                nonlocal done, last_emit
                done += 1
                now = time.monotonic()
                if now - last_emit >= PROGRESS_INTERVAL:
                    last_emit = now
                    self.progress.emit(done, total, str(path))

            with IndexStore(self.db_path) as store:
                for folder in present:
                    reports.append((folder, index_folder(store, folder, on_file, self.exclude)))
            self.progress.emit(done, max(total, done), "")
        except Exception as exc:  # noqa: BLE001 - report anything rather than kill the thread silently
            self.failed.emit(str(exc))
            return
        self.finished.emit(reports, missing)


class IndexJob(QObject):
    """Owns a worker and its thread for one indexing run."""

    counting = Signal()
    progress = Signal(int, int, str)
    finished = Signal(object, object)
    failed = Signal(str)
    done = Signal()

    def __init__(
        self,
        db_path: Path,
        folders: list[Path],
        exclude: Iterable[Path] = (),
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.thread = QThread()
        self.worker = IndexWorker(db_path, folders, exclude)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.counting.connect(self.counting)
        self.worker.progress.connect(self.progress)
        self.worker.finished.connect(self.finished)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.done)

    def start(self) -> None:
        self.thread.start()

    def wait(self) -> None:
        self.thread.quit()
        self.thread.wait()


def summarize(reports: list[tuple[Path, IndexReport]]) -> str:
    total = IndexReport()
    for _folder, report in reports:
        total.added += report.added
        total.updated += report.updated
        total.unchanged += report.unchanged
        total.moved += report.moved
        total.removed += report.removed
        total.failed.extend(report.failed)
    return (
        f"{total.added} added, {total.updated} updated, {total.unchanged} unchanged, "
        f"{total.moved} moved, {total.removed} removed, {len(total.failed)} failed"
    )


def collect_errors(
    reports: list[tuple[Path, IndexReport]], missing: list[Path]
) -> list[tuple[Path, str]]:
    errors = [(folder, MISSING_FOLDER_REASON) for folder in missing]
    for _folder, report in reports:
        errors.extend(report.failed)
    return errors
