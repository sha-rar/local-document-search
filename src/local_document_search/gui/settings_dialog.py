"""Settings dialog: exclusions and preferences."""

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..extractors import EXTRACTORS
from ..settings import MAX_RESULT_LIMIT, MIN_RESULT_LIMIT, Settings
from .preview import TYPE_LABELS


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(560, 520)
        self._settings = settings

        self.excluded_list = QListWidget()
        self.excluded_list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.excluded_list.addItems(settings.excluded_folders)
        self.excluded_list.itemSelectionChanged.connect(self._update_buttons)
        self.add_excluded_button = QPushButton("Add folder…")
        self.add_excluded_button.clicked.connect(self._choose_excluded)
        self.remove_excluded_button = QPushButton("Remove")
        self.remove_excluded_button.clicked.connect(self.remove_selected_exclusions)

        excluded_buttons = QHBoxLayout()
        excluded_buttons.addWidget(self.add_excluded_button)
        excluded_buttons.addWidget(self.remove_excluded_button)
        excluded_buttons.addStretch()
        excluded_note = QLabel(
            "Files in these folders are skipped, and removed from the index the next time "
            "it is updated."
        )
        excluded_note.setWordWrap(True)

        excluded_box = QGroupBox("Excluded folders")
        excluded_layout = QVBoxLayout(excluded_box)
        excluded_layout.addWidget(excluded_note)
        excluded_layout.addWidget(self.excluded_list)
        excluded_layout.addLayout(excluded_buttons)

        self.patterns_field = QLineEdit(", ".join(settings.excluded_patterns))
        self.patterns_field.setPlaceholderText("e.g. ~$*, *.tmp, node_modules")
        self.patterns_field.setToolTip(
            "Comma-separated names to skip. * matches any characters and ? matches one."
        )
        excluded_types = {ext.lower() for ext in settings.excluded_extensions}
        self.type_checks: dict[str, QCheckBox] = {}
        types_row = QHBoxLayout()
        for extension in EXTRACTORS:
            label = TYPE_LABELS.get(extension, extension.lstrip(".").upper())
            check = QCheckBox(f"{label} ({extension})")
            check.setChecked(extension not in excluded_types)
            self.type_checks[extension] = check
            types_row.addWidget(check)
        types_row.addStretch()

        skip_box = QGroupBox("Files to skip")
        skip_layout = QFormLayout(skip_box)
        skip_layout.addRow("Names matching", self.patterns_field)
        skip_layout.addRow("Index these types", types_row)

        self.result_limit = QSpinBox()
        self.result_limit.setRange(MIN_RESULT_LIMIT, MAX_RESULT_LIMIT)
        self.result_limit.setSingleStep(10)
        self.result_limit.setValue(settings.result_limit)
        self.index_on_startup = QCheckBox("Update the index when FileLens starts")
        self.index_on_startup.setChecked(settings.index_on_startup)
        self.watch_folders = QCheckBox("Update the index automatically when files change")
        self.watch_folders.setChecked(settings.watch_folders)

        preferences_box = QGroupBox("Preferences")
        preferences = QFormLayout(preferences_box)
        preferences.addRow("Maximum results", self.result_limit)
        preferences.addRow(self.index_on_startup)
        preferences.addRow(self.watch_folders)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(excluded_box)
        layout.addWidget(skip_box)
        layout.addWidget(preferences_box)
        layout.addWidget(buttons)
        self._update_buttons()

    def add_exclusion(self, folder: Path) -> None:
        folder_text = str(Path(folder).resolve())
        if folder_text not in self.excluded_folders():
            self.excluded_list.addItem(folder_text)

    def remove_selected_exclusions(self) -> None:
        for item in self.excluded_list.selectedItems():
            self.excluded_list.takeItem(self.excluded_list.row(item))
        self._update_buttons()

    def excluded_folders(self) -> list[str]:
        return [self.excluded_list.item(row).text() for row in range(self.excluded_list.count())]

    def excluded_patterns(self) -> list[str]:
        patterns = (part.strip() for part in self.patterns_field.text().split(","))
        return list(dict.fromkeys(pattern for pattern in patterns if pattern))

    def excluded_extensions(self) -> list[str]:
        return [ext for ext, check in self.type_checks.items() if not check.isChecked()]

    def result_settings(self) -> Settings:
        """The settings as edited, keeping fields this dialog doesn't show."""
        return replace(
            self._settings,
            excluded_folders=self.excluded_folders(),
            excluded_patterns=self.excluded_patterns(),
            excluded_extensions=self.excluded_extensions(),
            result_limit=self.result_limit.value(),
            index_on_startup=self.index_on_startup.isChecked(),
            watch_folders=self.watch_folders.isChecked(),
        )

    def _choose_excluded(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder to exclude")
        if folder:
            self.add_exclusion(Path(folder))

    def _update_buttons(self) -> None:
        self.remove_excluded_button.setEnabled(bool(self.excluded_list.selectedItems()))
