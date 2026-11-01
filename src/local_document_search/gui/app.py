"""Desktop application entry point."""

import logging
import sys
import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from ..diagnostics import collect_diagnostics, configure_logging
from ..settings import default_settings_path
from ..storage import default_db_path
from .main_window import MainWindow

logger = logging.getLogger(__name__)


def install_error_handlers(parent_window: MainWindow | None = None) -> None:
    """Log unhandled exceptions and tell the user, instead of failing silently.

    Started via ``filelens`` there is no console, so without this an error in a Qt slot
    or a background thread would leave no trace.
    """
    showing = False

    def report(exc_type, exc_value, exc_traceback) -> None:
        nonlocal showing
        logger.critical(
            "Unhandled error",
            exc_info=(exc_type, exc_value, exc_traceback),
            extra={"event": "unhandled_error", "error": exc_type.__name__},
        )
        if showing or QApplication.instance() is None:
            return
        showing = True  # an error while the dialog is open must not open another
        try:
            QMessageBox.critical(
                parent_window,
                "FileLens",
                f"Something went wrong: {exc_value}\n\n"
                "FileLens will try to carry on. The details were saved to the log "
                "(Help → Open log folder).",
            )
        finally:
            showing = False

    def report_thread(args: threading.ExceptHookArgs) -> None:
        logger.critical(
            "Unhandled error in background thread",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            extra={
                "event": "unhandled_thread_error",
                "thread_name": getattr(args.thread, "name", None),
            },
        )

    sys.excepthook = report
    threading.excepthook = report_thread


def main(argv: list[str] | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("FileLens")
    try:
        log_path = configure_logging()
    except OSError:
        log_path = None  # keep running without a log file rather than not at all
    db_path = default_db_path()
    logger.info(
        "FileLens started",
        extra={"event": "app_started", **collect_diagnostics(db_path, log_path)},
    )
    window = MainWindow(db_path, default_settings_path())
    install_error_handlers(window)
    window.show()
    # Quitting without closing the window (e.g. at logoff) must still stop worker threads.
    app.aboutToQuit.connect(window.close)
    if window.settings.index_on_startup:
        # Start after the window has painted so the progress bar is visible.
        QTimer.singleShot(0, window.start_indexing)
    exit_code = app.exec()
    logger.info("FileLens closed", extra={"event": "app_closed"})
    return exit_code
