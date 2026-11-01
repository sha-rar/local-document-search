"""Main application window: folders on the left, search and results in the middle, preview on the right."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..indexer import IndexReport, remove_folder
from ..search import SearchHit
from ..storage import IndexStore
from .folders import FolderPanel
from .indexing import IndexJob, summarize
from .opening import open_document, show_in_folder
from .preview import PreviewPane
from .search_panel import SearchPanel


class MainWindow(QMainWindow):
    def __init__(self, db_path: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.db_path = Path(db_path)
        self.index_job: IndexJob | None = None
        self.setWindowTitle("FileLens")
        self.resize(1100, 700)

        self.folder_panel = FolderPanel()
        self.folder_panel.index_requested.connect(self.start_indexing)
        self.folder_panel.folder_removed.connect(self._forget_folder)

        self.search_panel = SearchPanel(self.db_path)
        self.search_field = self.search_panel.search_field
        self.results_list = self.search_panel.results_list

        self.preview = PreviewPane()
        self.current_hit: SearchHit | None = None
        self.open_button = QPushButton("Open")
        self.open_button.clicked.connect(lambda: self.open_hit(self.current_hit))
        self.show_button = QPushButton("Show in folder")
        self.show_button.clicked.connect(lambda: self.show_hit_in_folder(self.current_hit))
        self.search_panel.result_selected.connect(self._on_result_selected)
        self.search_panel.result_activated.connect(self.open_hit)
        self._on_result_selected(None)

        preview_buttons = QHBoxLayout()
        preview_buttons.addWidget(self.open_button)
        preview_buttons.addWidget(self.show_button)
        preview_buttons.addStretch()
        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.addWidget(self.preview)
        preview_layout.addLayout(preview_buttons)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.folder_panel)
        splitter.addWidget(self.search_panel)
        splitter.addWidget(preview_panel)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 480, 380])
        self.setCentralWidget(splitter)

        self.statusBar().showMessage("Ready")

    def start_indexing(self) -> None:
        folders = self.folder_panel.folders()
        if self.index_job is not None or not folders:
            return
        self.index_job = IndexJob(self.db_path, folders, self)
        self.index_job.finished.connect(self._on_index_finished)
        self.index_job.failed.connect(self._on_index_failed)
        self.index_job.done.connect(self._on_index_done)
        self.folder_panel.set_busy(True)
        self.statusBar().showMessage(f"Indexing {len(folders)} folder(s)…")
        self.index_job.start()

    def _on_index_finished(self, reports: list[tuple[Path, IndexReport]], missing: list[Path]) -> None:
        message = f"Indexing complete: {summarize(reports)}"
        if missing:
            message += f"; skipped {len(missing)} missing folder(s)"
        self.statusBar().showMessage(message)
        self.search_panel.run_search()

    def _on_index_failed(self, error: str) -> None:
        self.statusBar().showMessage(f"Indexing failed: {error}")

    def _on_index_done(self) -> None:
        self.index_job.deleteLater()
        self.index_job = None
        self.folder_panel.set_busy(False)

    def open_hit(self, hit: SearchHit | None) -> None:
        if hit is not None and self._check_exists(hit) and not open_document(Path(hit.path)):
            self._warn(f"No application could open:\n{hit.path}")

    def show_hit_in_folder(self, hit: SearchHit | None) -> None:
        if hit is not None and self._check_exists(hit):
            show_in_folder(Path(hit.path))

    def _check_exists(self, hit: SearchHit) -> bool:
        if Path(hit.path).exists():
            return True
        self._warn(
            f"This file no longer exists:\n{hit.path}\n\n"
            "It may have been moved or deleted. Choose Index now to update the results."
        )
        return False

    def _warn(self, message: str) -> None:
        QMessageBox.warning(self, "FileLens", message)

    def _on_result_selected(self, hit: SearchHit | None) -> None:
        self.current_hit = hit
        self.preview.show_hit(hit)
        self.open_button.setEnabled(hit is not None)
        self.show_button.setEnabled(hit is not None)

    def _forget_folder(self, folder: Path) -> None:
        with IndexStore(self.db_path) as store:
            removed = remove_folder(store, folder, keep=self.folder_panel.folders())
        self.statusBar().showMessage(f"Removed {removed} document(s) from {folder}")
        self.search_panel.run_search()

    def closeEvent(self, event: QCloseEvent) -> None:
        # The worker thread must finish before its QThread is destroyed.
        if self.index_job is not None:
            self.index_job.wait()
        super().closeEvent(event)
