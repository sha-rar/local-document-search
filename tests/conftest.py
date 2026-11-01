import os

# Run Qt tests without opening windows; must be set before a QApplication exists.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
