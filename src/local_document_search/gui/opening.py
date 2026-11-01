"""Open documents and their folders with the operating system's default handlers."""

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def open_document(path: Path) -> bool:
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def show_in_folder(path: Path) -> bool:
    """Reveal ``path`` in the file manager, selecting it where the platform supports that."""
    if sys.platform == "win32":
        # Explorer expects /select,"path" as one argument string.
        subprocess.Popen(f'explorer /select,"{path}"')
        return True
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
