"""Search field, type filter and results list."""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..extractors import EXTRACTORS
from ..search import SearchFilters, SearchHit
from ..settings import DEFAULT_RESULT_LIMIT
from .preview import TYPE_LABELS
from .searching import SearchService

SEARCH_DELAY_MS = 250


class SearchPanel(QWidget):
    """Runs searches against the index in the background and lists the hits."""

    result_selected = Signal(object)  # SearchHit | None
    result_activated = Signal(object)  # SearchHit
    search_finished = Signal()  # results (or a message) for the latest search are shown

    def __init__(self, db_path: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.db_path = Path(db_path)
        self.result_limit = DEFAULT_RESULT_LIMIT
        self.service = SearchService(self.db_path, self)
        self.service.finished.connect(self._on_results)
        self.service.failed.connect(self._on_failed)
        self._pending_request: int | None = None

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Search document contents")
        self.search_field.setClearButtonEnabled(True)
        self.search_field.textChanged.connect(self._schedule_search)
        self.search_field.returnPressed.connect(self.run_search)

        self.type_filter = QComboBox()
        self.type_filter.addItem("All types", None)
        for extension in EXTRACTORS:
            label = TYPE_LABELS.get(extension, extension.lstrip(".").upper())
            self.type_filter.addItem(f"{label} ({extension})", extension)
        self.type_filter.currentIndexChanged.connect(self.run_search)

        self.count_label = QLabel()
        self.results_list = QListWidget()
        self.results_list.setAlternatingRowColors(True)
        self.results_list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.results_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results_list.currentItemChanged.connect(self._on_current_changed)
        self.results_list.itemActivated.connect(
            lambda item: self.result_activated.emit(item.data(Qt.ItemDataRole.UserRole))
        )

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SEARCH_DELAY_MS)
        self._timer.timeout.connect(self.run_search)

        query_row = QHBoxLayout()
        query_row.addWidget(self.search_field, 1)
        query_row.addWidget(self.type_filter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(query_row)
        layout.addWidget(self.count_label)
        layout.addWidget(self.results_list)

    def filters(self) -> SearchFilters:
        extension = self.type_filter.currentData()
        return SearchFilters(extensions=(extension,) if extension else ())

    @property
    def busy(self) -> bool:
        return self._pending_request is not None

    def run_search(self) -> None:
        """Start a search for the current text; results replace the list when they arrive."""
        self._timer.stop()
        query = self.search_field.text().strip()
        if not query or not self.db_path.exists():
            self._pending_request = None  # drop any search still in flight
            self.results_list.clear()
            if query:
                self.count_label.setText("Nothing indexed yet. Add a folder and choose Index now.")
            else:
                self.count_label.clear()
            self.search_finished.emit()
            return
        # Previous results stay visible until the new ones arrive, so the list doesn't flicker.
        self._pending_request = self.service.submit(query, self.result_limit, self.filters())

    def shutdown(self) -> None:
        self._pending_request = None
        self.service.shutdown()

    def _on_results(self, request_id: int, hits: list[SearchHit]) -> None:
        if request_id != self._pending_request:
            return  # superseded by a newer search
        self._pending_request = None
        self.results_list.clear()
        for hit in hits:
            path = Path(hit.path)
            item = QListWidgetItem(f"{path.name}\n{path.parent}")
            item.setData(Qt.ItemDataRole.UserRole, hit)
            item.setToolTip(hit.path)
            self.results_list.addItem(item)
        self.count_label.setText(self._count_text(len(hits)))
        if hits:
            self.results_list.setCurrentRow(0)
        self.search_finished.emit()

    def _on_failed(self, request_id: int, message: str) -> None:
        if request_id != self._pending_request:
            return
        self._pending_request = None
        self.results_list.clear()
        self.count_label.setText(f"Search failed: {message}")
        self.search_finished.emit()

    def hits(self) -> list[SearchHit]:
        return [
            self.results_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.results_list.count())
        ]

    def _count_text(self, count: int) -> str:
        if count == 0:
            return "No matches."
        if count >= self.result_limit:
            return f"Showing the top {count} results."
        return f"{count} result{'s' if count != 1 else ''}."

    def _schedule_search(self) -> None:
        self._timer.start()

    def _on_current_changed(self, current: QListWidgetItem | None, _previous) -> None:
        self.result_selected.emit(current.data(Qt.ItemDataRole.UserRole) if current else None)
