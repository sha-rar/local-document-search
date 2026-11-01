"""Run searches on a worker thread so typing never waits on the database."""

from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from ..search import SearchFilters, search
from ..storage import IndexStore
from .preview import HIGHLIGHT_END, HIGHLIGHT_START, PREVIEW_SNIPPET_TOKENS


class SearchWorker(QObject):
    """Answers search requests with its own connection; lives on a ``QThread``."""

    finished = Signal(int, object)  # request id, list[SearchHit]
    failed = Signal(int, str)  # request id, message

    def __init__(self, db_path: Path):
        super().__init__()
        self.db_path = db_path
        # Written by the GUI thread; requests older than this are skipped unrun.
        self.latest_request = 0
        self._store: IndexStore | None = None

    @Slot(int, str, int, object)
    def run(self, request_id: int, query: str, limit: int, filters: SearchFilters) -> None:
        if request_id < self.latest_request:
            return
        try:
            if self._store is None:
                self._store = IndexStore(self.db_path)
            hits = search(
                self._store,
                query,
                limit,
                filters,
                highlight=(HIGHLIGHT_START, HIGHLIGHT_END),
                snippet_tokens=PREVIEW_SNIPPET_TOKENS,
            )
        except Exception as exc:  # noqa: BLE001 - surface any failure in the UI
            self.failed.emit(request_id, str(exc))
            return
        self.finished.emit(request_id, hits)

    @Slot()
    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None


class SearchService(QObject):
    """Owns the search thread; ``submit`` returns immediately and results arrive as signals."""

    finished = Signal(int, object)
    failed = Signal(int, str)
    _requested = Signal(int, str, int, object)

    def __init__(self, db_path: Path, parent: QObject | None = None):
        super().__init__(parent)
        self._next_id = 0
        self.thread = QThread()
        self.worker = SearchWorker(db_path)
        self.worker.moveToThread(self.thread)
        self._requested.connect(self.worker.run)
        self.worker.finished.connect(self.finished)
        self.worker.failed.connect(self.failed)
        # The connection belongs to the worker thread, so close it there as the thread ends.
        self.thread.finished.connect(self.worker.close, Qt.ConnectionType.DirectConnection)
        self.thread.start()

    def submit(self, query: str, limit: int, filters: SearchFilters) -> int:
        self._next_id += 1
        self.worker.latest_request = self._next_id
        self._requested.emit(self._next_id, query, limit, filters)
        return self._next_id

    def shutdown(self) -> None:
        if self.thread.isRunning():
            self.thread.quit()
            self.thread.wait()
