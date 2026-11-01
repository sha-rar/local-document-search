"""Main application window: folders on the left, search and results in the middle, preview on the right."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


class MainWindow(QMainWindow):
    def __init__(self, db_path: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.db_path = Path(db_path)
        self.setWindowTitle("FileLens")
        self.resize(1100, 700)

        self.folder_panel = self._build_folder_panel()

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Search document contents")
        self.search_field.setClearButtonEnabled(True)
        self.results_list = QListWidget()

        search_panel = QWidget()
        search_layout = QVBoxLayout(search_panel)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.addWidget(self.search_field)
        search_layout.addWidget(self.results_list)

        self.preview = QTextBrowser()
        self.preview.setPlaceholderText("Select a result to preview it.")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.folder_panel)
        splitter.addWidget(search_panel)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 480, 380])
        self.setCentralWidget(splitter)

        self.statusBar().showMessage("Ready")

    def _build_folder_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Folders"))
        layout.addStretch()
        return panel
