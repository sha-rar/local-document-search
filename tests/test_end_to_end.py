"""End-to-end workflows: the desktop app and the CLI used the way a person would."""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from helpers import write_docx, write_pdf  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from local_document_search.diagnostics import configure_logging, default_log_dir  # noqa: E402
from local_document_search.gui import app as gui_app  # noqa: E402
from local_document_search.gui import main_window  # noqa: E402
from local_document_search.gui.main_window import MainWindow  # noqa: E402
from local_document_search.settings import default_settings_path  # noqa: E402
from local_document_search.storage import default_db_path  # noqa: E402


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "Documents"
    (root / "Reports").mkdir(parents=True)
    (root / "Notes").mkdir()
    write_pdf(root / "Reports" / "annual.pdf", ["Annual revenue grew strongly", "Outlook"])
    write_docx(root / "Reports" / "budget.docx", ["Marketing budget proposal"])
    (root / "Notes" / "meeting.txt").write_text("Agenda: hiring plan", encoding="utf-8")
    (root / "Notes" / "ideas.md").write_text("# Ideas\nOffline sync prototype", encoding="utf-8")
    (root / "Notes" / "~$budget.docx").write_bytes(b"Word lock file")  # skipped by default
    (root / "Reports" / "corrupt.pdf").write_bytes(b"%PDF-1.7 truncated")
    (root / "Reports" / "fake.docx").write_bytes(b"not a zip")
    return root


@pytest.fixture
def opened(monkeypatch):
    calls = []
    monkeypatch.setattr(main_window, "open_document", lambda path: calls.append(path) or True)
    return calls


def new_window(qtbot):
    window = MainWindow(default_db_path(), default_settings_path())
    qtbot.addWidget(window)
    window.show()
    return window


def wait_idle(qtbot, window, timeout=10000):
    qtbot.waitUntil(
        lambda: window.index_job is None
        and not window.pending_changes
        and not window.search_panel.busy,
        timeout=timeout,
    )


def search(qtbot, window, text):
    window.search_field.setText(text)
    with qtbot.waitSignal(window.search_panel.search_finished, timeout=5000):
        window.search_panel.run_search()
    return [Path(hit.path).name for hit in window.search_panel.hits()]


def wait_for_results(qtbot, window, text, expected):
    """Search repeatedly until the folder watcher has applied a change."""
    qtbot.waitUntil(lambda: search(qtbot, window, text) == expected, timeout=10000)


def test_desktop_workflow(qtbot, library, opened, monkeypatch):
    monkeypatch.setattr(MainWindow, "monitor_debounce", 0.1)
    log_path = configure_logging()
    window = new_window(qtbot)

    # 1. Choose a folder and index it.
    window.folder_panel.add_folder(library)
    window.folder_panel.index_button.click()
    wait_idle(qtbot, window)
    status = window.statusBar().currentMessage()
    assert status.startswith("Indexing complete: 4 added"), status

    # 2. Broken files are listed, not fatal.
    assert window.errors_button.text() == "2 problems…"
    problems = {Path(path).name for path, _reason in window.index_errors}
    assert problems == {"corrupt.pdf", "fake.docx"}

    # 3. Every format is searchable; filters narrow results.
    assert search(qtbot, window, '"revenue grew"') == ["annual.pdf"]
    assert search(qtbot, window, "marketing budget") == ["budget.docx"]
    assert search(qtbot, window, "hiring") == ["meeting.txt"]
    assert search(qtbot, window, "prototype") == ["ideas.md"]
    combo = window.search_panel.type_filter
    with qtbot.waitSignal(window.search_panel.search_finished, timeout=5000):
        combo.setCurrentIndex(combo.findData(".pdf"))
    assert search(qtbot, window, "budget revenue outlook") == []
    combo.setCurrentIndex(0)

    # 4. Preview and open the top result.
    search(qtbot, window, "revenue")
    preview = window.preview.toPlainText()
    assert "annual.pdf" in preview and "revenue" in preview.lower()
    window.open_button.click()
    assert opened == [(library / "Reports" / "annual.pdf").resolve()]

    # 5. Changes on disk are picked up automatically.
    (library / "Notes" / "meeting.txt").write_text("Agenda: quarterly offsite", encoding="utf-8")
    wait_for_results(qtbot, window, "offsite", ["meeting.txt"])
    assert search(qtbot, window, "hiring") == []

    (library / "Notes" / "ideas.md").rename(library / "Reports" / "roadmap.md")
    wait_for_results(qtbot, window, "prototype", ["roadmap.md"])

    (library / "Reports" / "budget.docx").unlink()
    wait_for_results(qtbot, window, "marketing", [])
    wait_idle(qtbot, window)
    window.close()

    # 6. Restarting keeps the folders and the index; no re-index needed to search.
    reopened = new_window(qtbot)
    assert reopened.folder_panel.folders() == [library.resolve()]
    assert search(qtbot, reopened, "offsite") == ["meeting.txt"]
    reopened.close()

    # 7. The log recorded the run, including each problem file.
    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    logged = {entry["event"] for entry in entries if "event" in entry}
    expected = {"index_created", "scan_started", "scan_finished", "changes_applied", "watch_started"}
    assert expected <= logged
    failures = [entry for entry in entries if entry.get("event") == "file_failed"]
    failed_paths = {Path(entry["path"]).name for entry in failures}
    assert failed_paths == {"corrupt.pdf", "fake.docx"}


def test_damaged_index_does_not_crash_the_app(qtbot, tmp_path, library):
    default_db_path().parent.mkdir(parents=True, exist_ok=True)
    default_db_path().write_bytes(b"this is not an SQLite database" * 10)
    window = new_window(qtbot)
    window.folder_panel.add_folder(library)

    window.search_field.setText("budget")
    with qtbot.waitSignal(window.search_panel.search_finished, timeout=5000):
        window.search_panel.run_search()
    assert window.search_panel.count_label.text().startswith("Search failed")

    window.folder_panel.index_button.click()
    wait_idle(qtbot, window)
    assert window.statusBar().currentMessage().startswith("Indexing failed")
    assert window.folder_panel.index_button.isEnabled()  # still usable afterwards


@pytest.mark.qt_no_exception_capture
def test_unhandled_errors_are_logged_and_reported(qtbot, monkeypatch):
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: shown.append(args[2]))
    log_path = configure_logging()
    window = new_window(qtbot)
    gui_app.install_error_handlers(window)

    def faulty_slot():
        raise RuntimeError("bug in a slot")

    QTimer.singleShot(0, faulty_slot)
    qtbot.waitUntil(lambda: len(shown) == 1, timeout=2000)
    thread = threading.Thread(target=lambda: 1 / 0, name="worker")
    thread.start()
    thread.join()

    assert "bug in a slot" in shown[0] and "log" in shown[0]
    assert window.isVisible()  # the app carried on
    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    slot_error = next(e for e in entries if e.get("event") == "unhandled_error")
    assert "RuntimeError: bug in a slot" in slot_error["traceback"]
    thread_error = next(e for e in entries if e.get("event") == "unhandled_thread_error")
    assert thread_error["thread_name"] == "worker"
    assert "ZeroDivisionError" in thread_error["traceback"]


def test_app_starts_logs_diagnostics_and_quits(isolated_app_data):
    """Run the real entry point in its own process: quitting the event loop would
    otherwise break the QApplication shared by the rest of the test session."""
    script = "\n".join(
        [
            "import sys",
            "from PySide6.QtCore import QTimer",
            "from PySide6.QtWidgets import QApplication",
            "app = QApplication(sys.argv)",
            "QTimer.singleShot(500, app.quit)",
            "from local_document_search.gui.app import main",
            "sys.exit(main())",
        ]
    )
    env = {**os.environ, "LOCALAPPDATA": str(isolated_app_data), "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=120
    )
    assert result.returncode == 0, result.stderr

    log_path = isolated_app_data / "FileLens" / "logs" / "filelens.log"
    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    started = next(e for e in entries if e.get("event") == "app_started")
    assert Path(started["index_path"]).is_relative_to(isolated_app_data)
    assert started["fts5"] is True and started["qt"]
    assert any(e.get("event") == "app_closed" for e in entries)


def test_help_menu_opens_log_folder(qtbot, opened):
    window = new_window(qtbot)
    window.open_logs_action.trigger()
    assert opened == [default_log_dir()]
    assert default_log_dir().is_dir()


def test_cli_in_a_separate_process(tmp_path, library, isolated_app_data):
    env = {**os.environ, "LOCALAPPDATA": str(isolated_app_data)}

    def docsearch(*args):
        return subprocess.run(
            [sys.executable, "-m", "local_document_search", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )

    indexed = docsearch("index", str(library))
    assert indexed.returncode == 0, indexed.stderr
    # The CLI has no default name exclusions, so Word's ~$ lock file is a third failure.
    assert "4 added" in indexed.stdout and "3 failed" in indexed.stdout

    found = docsearch("search", '"revenue grew"')
    assert found.returncode == 0 and "annual.pdf" in found.stdout

    info = json.loads(docsearch("diagnostics").stdout)
    assert info["documents"] == 4
    assert Path(info["index_path"]).is_relative_to(isolated_app_data)
    assert (isolated_app_data / "FileLens" / "logs" / "filelens.log").exists()
