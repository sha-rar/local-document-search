"""Folder selection panel."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class FolderPanel(QWidget):
    """Lists the folders to index, with buttons to add, remove and index them."""

    folder_added = Signal(Path)
    folder_removed = Signal(Path)
    index_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.folder_list = QListWidget()
        self.folder_list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.folder_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.folder_list.itemSelectionChanged.connect(self._update_buttons)

        self.add_button = QPushButton("Add folder…")
        self.add_button.clicked.connect(self._choose_folder)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self.remove_selected)
        self.index_button = QPushButton("Index now")
        self.index_button.clicked.connect(self.index_requested)

        buttons = QHBoxLayout()
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Folders"))
        layout.addWidget(self.folder_list)
        layout.addLayout(buttons)
        layout.addWidget(self.index_button)

        self._busy = False
        self._update_buttons()

    def folders(self) -> list[Path]:
        return [
            self.folder_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.folder_list.count())
        ]

    def add_folder(self, folder: Path) -> bool:
        """Add ``folder`` unless it is already listed; return whether it was added."""
        folder = Path(folder).resolve()
        if folder in self.folders():
            return False
        item = QListWidgetItem(str(folder))
        item.setData(Qt.ItemDataRole.UserRole, folder)
        item.setToolTip(str(folder))
        self.folder_list.addItem(item)
        self._update_buttons()
        self.folder_added.emit(folder)
        return True

    def remove_selected(self) -> None:
        for item in self.folder_list.selectedItems():
            folder = item.data(Qt.ItemDataRole.UserRole)
            self.folder_list.takeItem(self.folder_list.row(item))
            self.folder_removed.emit(folder)
        self._update_buttons()

    def set_busy(self, busy: bool) -> None:
        """Disable changes while indexing runs."""
        self._busy = busy
        self._update_buttons()

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder to index")
        if folder:
            self.add_folder(Path(folder))

    def _update_buttons(self) -> None:
        self.add_button.setEnabled(not self._busy)
        self.remove_button.setEnabled(not self._busy and bool(self.folder_list.selectedItems()))
        self.index_button.setEnabled(not self._busy and self.folder_list.count() > 0)
