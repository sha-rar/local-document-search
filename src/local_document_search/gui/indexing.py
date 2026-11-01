"""Run indexing on a worker thread so the GUI event loop stays responsive."""

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..indexer import IndexReport, index_folder
from ..storage import IndexStore


class IndexWorker(QObject):
    """Indexes folders with its own database connection; lives on a ``QThread``."""

    # (list[tuple[Path, IndexReport]], list[Path] of folders that no longer exist)
    finished = Signal(object, object)
    failed = Signal(str)

    def __init__(self, db_path: Path, folders: list[Path]):
        super().__init__()
        self.db_path = db_path
        self.folders = list(folders)

    @Slot()
    def run(self) -> None:
        reports: list[tuple[Path, IndexReport]] = []
        missing: list[Path] = []
        try:
            with IndexStore(self.db_path) as store:
                for folder in self.folders:
                    # Indexing a vanished folder (e.g. an unplugged drive) would delete its entries.
                    if not folder.is_dir():
                        missing.append(folder)
                        continue
                    reports.append((folder, index_folder(store, folder)))
        except Exception as exc:  # noqa: BLE001 - report anything rather than kill the thread silently
            self.failed.emit(str(exc))
            return
        self.finished.emit(reports, missing)


class IndexJob(QObject):
    """Owns a worker and its thread for one indexing run."""

    finished = Signal(object, object)
    failed = Signal(str)
    done = Signal()

    def __init__(self, db_path: Path, folders: list[Path], parent: QObject | None = None):
        super().__init__(parent)
        self.thread = QThread()
        self.worker = IndexWorker(db_path, folders)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
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
