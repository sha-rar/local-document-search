"""Desktop application entry point."""

import sys

from PySide6.QtWidgets import QApplication

from ..storage import default_db_path
from .main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("FileLens")
    window = MainWindow(default_db_path())
    window.show()
    return app.exec()
