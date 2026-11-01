"""Structured logging and environment diagnostics.

Logs are JSON lines (one object per line) so they can be read by people and filtered by
tools. Extra fields passed with ``logger.info(..., extra={...})`` become JSON keys.
"""

import json
import logging
import logging.handlers
import platform
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from .storage import IndexStore, default_db_path

PACKAGE_LOGGER = "local_document_search"
LOG_FILE_NAME = "filelens.log"
LOG_MAX_BYTES = 1024 * 1024
LOG_BACKUPS = 3

# Attributes every LogRecord has; anything else came from ``extra`` and is logged as a field.
_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "taskName",
}


def default_log_dir() -> Path:
    return default_db_path().parent / "logs"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                plain = isinstance(value, (int, float, bool, type(None)))
                entry[key] = value if plain else str(value)
        if record.exc_info:
            entry["traceback"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


class _ReadableFormatter(logging.Formatter):
    """Console output for ``--verbose``: the message plus any extra fields."""

    def format(self, record: logging.LogRecord) -> str:
        fields = {
            key: value
            for key, value in vars(record).items()
            if key not in _STANDARD_ATTRS and not key.startswith("_")
        }
        text = f"{record.levelname.lower()}: {record.getMessage()}"
        if fields:
            text += " (" + ", ".join(f"{key}={value}" for key, value in fields.items()) + ")"
        if record.exc_info:
            text += "\n" + self.formatException(record.exc_info)
        return text


def configure_logging(log_dir: Path | None = None, verbose: bool = False) -> Path:
    """Send the package's logs to a rotating JSON file (and stderr if ``verbose``).

    Safe to call more than once: handlers from earlier calls are replaced. Returns the
    log file path.
    """
    log_dir = Path(log_dir or default_log_dir())
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / LOG_FILE_NAME

    logger = logging.getLogger(PACKAGE_LOGGER)
    for handler in list(logger.handlers):
        if getattr(handler, "_filelens", False):
            logger.removeHandler(handler)
            handler.close()

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
    )
    file_handler.setFormatter(JsonFormatter())
    file_handler._filelens = True
    logger.addHandler(file_handler)

    if verbose:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(_ReadableFormatter())
        console._filelens = True
        logger.addHandler(console)

    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    # Our handlers are the only output; don't also print through the root logger.
    logger.propagate = False
    return log_path


def collect_diagnostics(db_path: Path, log_path: Path | None = None) -> dict:
    """Facts that help diagnose a problem report. Never raises."""
    info: dict = {
        "app_version": _app_version(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "sqlite": sqlite3.sqlite_version,
        "index_path": str(db_path),
        "index_exists": Path(db_path).exists(),
    }
    if log_path is not None:
        info["log_path"] = str(log_path)
    try:
        import PySide6
        from PySide6.QtCore import qVersion

        info["pyside6"] = PySide6.__version__
        info["qt"] = qVersion()
    except ImportError:
        info["pyside6"] = None
    try:
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
        connection.close()
        info["fts5"] = True
    except sqlite3.Error:
        info["fts5"] = False
    if info["index_exists"]:
        try:
            info["index_size_mb"] = round(Path(db_path).stat().st_size / 1024**2, 1)
            with IndexStore(db_path) as store:
                info["documents"] = store.document_count()
        except (OSError, sqlite3.Error) as exc:
            info["index_error"] = str(exc)
    return info


def _app_version() -> str:
    try:
        from importlib.metadata import version

        return version("local-document-search")
    except Exception:  # noqa: BLE001 - running from a source tree without metadata
        return "unknown"
