"""Dialog listing files that could not be indexed."""

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class IndexErrorsDialog(QDialog):
    def __init__(self, errors: list[tuple[Path, str]], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Indexing problems")
        self.resize(760, 360)

        self.table = QTableWidget(len(errors), 2)
        self.table.setHorizontalHeaderLabels(["File", "Problem"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for row, (path, reason) in enumerate(errors):
            path_item = QTableWidgetItem(str(path))
            path_item.setToolTip(str(path))
            self.table.setItem(row, 0, path_item)
            self.table.setItem(row, 1, QTableWidgetItem(reason))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("These items were skipped. Everything else was indexed normally.")
        )
        layout.addWidget(self.table)
        layout.addWidget(buttons)
