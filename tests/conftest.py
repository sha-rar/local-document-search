import logging
import os

import pytest

# Run Qt tests without opening windows; must be set before a QApplication exists.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolated_app_data(tmp_path_factory, monkeypatch):
    """Point the default index, settings and log locations at a temporary folder.

    Without this, any code path that uses the defaults (e.g. the CLI's log file) would
    write into the real user profile.
    """
    app_data = tmp_path_factory.mktemp("appdata")
    monkeypatch.setenv("LOCALAPPDATA", str(app_data))
    yield app_data
    # Close log files opened during the test so the next test starts clean.
    package_logger = logging.getLogger("local_document_search")
    for handler in list(package_logger.handlers):
        if getattr(handler, "_filelens", False):  # added by configure_logging
            package_logger.removeHandler(handler)
            handler.close()
    package_logger.propagate = True
