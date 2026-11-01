"""Main application window: folders on the left, search and results in the middle, preview on the right."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..indexer import IndexReport, remove_folder
from ..search import SearchHit
from ..settings import Settings, load_settings, save_settings
from ..storage import IndexStore
from .errors import IndexErrorsDialog
from .folders import FolderPanel
from .indexing import IndexJob, collect_errors, summarize
from .opening import open_document, show_in_folder
from .preview import PreviewPane
from .search_panel import SearchPanel
from .settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    def __init__(
        self,
        db_path: Path,
        settings_path: Path | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.db_path = Path(db_path)
        # Settings live beside the index unless a location is given.
        self.settings_path = Path(settings_path or self.db_path.with_name("settings.json"))
        self.settings = load_settings(self.settings_path)
        self.index_job: IndexJob | None = None
        self.setWindowTitle("FileLens")
        self.resize(1100, 700)
        self._build_menu()

        self.folder_panel = FolderPanel()
        for folder in self.settings.folders:
            self.folder_panel.add_folder(Path(folder))
        self.folder_panel.index_requested.connect(self.start_indexing)
        self.folder_panel.folder_added.connect(self._save_folders)
        self.folder_panel.folder_removed.connect(self._forget_folder)

        self.search_panel = SearchPanel(self.db_path)
        self.search_panel.result_limit = self.settings.result_limit
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

        self.index_errors: list[tuple[Path, str]] = []
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(220)
        self.progress_bar.hide()
        self.errors_button = QPushButton()
        self.errors_button.setFlat(True)
        self.errors_button.clicked.connect(self.show_index_errors)
        self.errors_button.hide()
        self.statusBar().addPermanentWidget(self.errors_button)
        self.statusBar().addPermanentWidget(self.progress_bar)
        self.statusBar().showMessage("Ready")

    def start_indexing(self) -> None:
        folders = self.folder_panel.folders()
        if self.index_job is not None or not folders:
            return
        exclude = [Path(folder) for folder in self.settings.excluded_folders]
        self.index_job = IndexJob(self.db_path, folders, exclude, parent=self)
        self.index_job.counting.connect(self._on_index_counting)
        self.index_job.progress.connect(self._on_index_progress)
        self.index_job.finished.connect(self._on_index_finished)
        self.index_job.failed.connect(self._on_index_failed)
        self.index_job.done.connect(self._on_index_done)
        self.folder_panel.set_busy(True)
        self.errors_button.hide()
        self.index_job.start()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            self.apply_settings(dialog.result_settings())

    def apply_settings(self, settings: Settings) -> None:
        self.settings = settings
        save_settings(self.settings, self.settings_path)
        self.search_panel.result_limit = settings.result_limit
        self.search_panel.run_search()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        self.settings_action = QAction("&Settings…", self)
        self.settings_action.setShortcut(QKeySequence.StandardKey.Preferences)
        self.settings_action.triggered.connect(self.open_settings)
        file_menu.addAction(self.settings_action)
        file_menu.addSeparator()
        quit_action = QAction("E&xit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    def _save_folders(self) -> None:
        self.settings.folders = [str(folder) for folder in self.folder_panel.folders()]
        save_settings(self.settings, self.settings_path)

    def show_index_errors(self) -> None:
        IndexErrorsDialog(self.index_errors, self).exec()

    def _on_index_counting(self) -> None:
        self.progress_bar.setRange(0, 0)  # busy indicator until the total is known
        self.progress_bar.show()
        self.statusBar().showMessage("Finding documents…")

    def _on_index_progress(self, done: int, total: int, current: str) -> None:
        total = max(total, done, 1)
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(done)
        message = f"Indexing {done:,} of {total:,}"
        if current:
            message += f": {Path(current).name}"
        self.statusBar().showMessage(message)

    def _on_index_finished(self, reports: list[tuple[Path, IndexReport]], missing: list[Path]) -> None:
        message = f"Indexing complete: {summarize(reports)}"
        if missing:
            message += f"; skipped {len(missing)} missing folder(s)"
        self.statusBar().showMessage(message)
        self.index_errors = collect_errors(reports, missing)
        if self.index_errors:
            count = len(self.index_errors)
            self.errors_button.setText(f"{count} problem{'s' if count != 1 else ''}…")
            self.errors_button.show()
        self.search_panel.run_search()

    def _on_index_failed(self, error: str) -> None:
        self.statusBar().showMessage(f"Indexing failed: {error}")

    def _on_index_done(self) -> None:
        self.index_job.deleteLater()
        self.index_job = None
        self.progress_bar.hide()
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
        self._save_folders()
        with IndexStore(self.db_path) as store:
            removed = remove_folder(store, folder, keep=self.folder_panel.folders())
        self.statusBar().showMessage(f"Removed {removed} document(s) from {folder}")
        self.search_panel.run_search()

    def closeEvent(self, event: QCloseEvent) -> None:
        # The worker thread must finish before its QThread is destroyed.
        if self.index_job is not None:
            self.index_job.wait()
        super().closeEvent(event)
