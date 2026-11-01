"""Desktop application entry point."""

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from ..settings import default_settings_path
from ..storage import default_db_path
from .main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("FileLens")
    window = MainWindow(default_db_path(), default_settings_path())
    window.show()
    if window.settings.index_on_startup:
        # Start after the window has painted so the progress bar is visible.
        QTimer.singleShot(0, window.start_indexing)
    return app.exec()
