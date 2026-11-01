import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt, QTimer  # noqa: E402

from local_document_search import indexer  # noqa: E402
from local_document_search.gui import main_window  # noqa: E402
from local_document_search.gui.errors import IndexErrorsDialog  # noqa: E402
from local_document_search.gui.main_window import MainWindow  # noqa: E402
from local_document_search.gui.preview import (  # noqa: E402
    HIGHLIGHT_END,
    HIGHLIGHT_START,
    highlight_snippet,
    render_preview,
)
from local_document_search.gui.settings_dialog import SettingsDialog  # noqa: E402
from local_document_search.search import SearchHit  # noqa: E402
from local_document_search.settings import Settings, load_settings  # noqa: E402
from local_document_search.storage import IndexStore  # noqa: E402


@pytest.fixture
def window(qtbot, tmp_path):
    window = MainWindow(tmp_path / "index.db")
    qtbot.addWidget(window)
    window.show()
    yield window
    window.close()


@pytest.fixture
def docs(tmp_path):
    root = tmp_path / "docs"
    (root / "nested").mkdir(parents=True)
    (root / "a.txt").write_text("alpha budget", encoding="utf-8")
    (root / "nested" / "b.md").write_text("beta budget", encoding="utf-8")
    return root


def index_and_wait(qtbot, window):
    window.folder_panel.index_button.click()
    assert window.index_job is not None
    qtbot.waitUntil(lambda: window.index_job is None, timeout=10000)


def indexed_count(window):
    with IndexStore(window.db_path) as store:
        return store.document_count()


def test_main_window_layout(window):
    assert window.windowTitle() == "FileLens"
    assert window.search_field.placeholderText() == "Search document contents"
    assert window.results_list.count() == 0
    assert window.statusBar().currentMessage() == "Ready"


def test_folder_buttons_follow_state(window, docs):
    panel = window.folder_panel
    assert not panel.index_button.isEnabled()
    assert not panel.remove_button.isEnabled()

    assert panel.add_folder(docs)
    assert not panel.add_folder(docs / "nested" / "..")  # same folder, different spelling
    assert panel.folders() == [docs.resolve()]
    assert panel.index_button.isEnabled()

    panel.folder_list.setCurrentRow(0)
    assert panel.remove_button.isEnabled()


def test_index_runs_in_background_and_reports(qtbot, window, docs):
    window.folder_panel.add_folder(docs)
    index_and_wait(qtbot, window)

    assert indexed_count(window) == 2
    assert window.statusBar().currentMessage().startswith("Indexing complete: 2 added")
    assert window.folder_panel.add_button.isEnabled()


def test_missing_folder_is_skipped_not_emptied(qtbot, window, docs, tmp_path):
    window.folder_panel.add_folder(docs)
    index_and_wait(qtbot, window)
    gone = tmp_path / "unplugged"
    gone.mkdir()
    window.folder_panel.add_folder(gone)
    gone.rmdir()

    index_and_wait(qtbot, window)
    assert indexed_count(window) == 2
    assert "skipped 1 missing folder" in window.statusBar().currentMessage()


def test_removing_folder_drops_its_documents(qtbot, window, docs):
    panel = window.folder_panel
    panel.add_folder(docs)
    panel.add_folder(docs / "nested")
    index_and_wait(qtbot, window)

    panel.folder_list.setCurrentRow(0)  # the parent folder
    panel.remove_selected()
    # b.md is still covered by the nested folder.
    assert indexed_count(window) == 1
    assert panel.folders() == [(docs / "nested").resolve()]


def result_names(window):
    return [Path(hit.path).name for hit in window.search_panel.hits()]


def test_search_before_indexing_explains(window):
    window.search_field.setText("budget")
    window.search_panel.run_search()
    assert "Nothing indexed yet" in window.search_panel.count_label.text()


def test_typing_searches_after_a_pause(qtbot, window, docs):
    window.folder_panel.add_folder(docs)
    index_and_wait(qtbot, window)

    window.search_field.setText("budget")
    qtbot.waitUntil(lambda: window.results_list.count() == 2, timeout=2000)
    assert sorted(result_names(window)) == ["a.txt", "b.md"]
    assert window.search_panel.count_label.text() == "2 results."

    qtbot.keyClicks(window.search_field, " alpha")
    qtbot.keyClick(window.search_field, Qt.Key.Key_Return)
    assert result_names(window) == ["a.txt"]

    window.search_field.clear()
    window.search_panel.run_search()
    assert window.results_list.count() == 0


def test_type_filter_narrows_results(qtbot, window, docs):
    window.folder_panel.add_folder(docs)
    index_and_wait(qtbot, window)
    window.search_field.setText("budget")
    window.search_panel.run_search()

    combo = window.search_panel.type_filter
    combo.setCurrentIndex(combo.findData(".md"))
    assert result_names(window) == ["b.md"]


def test_results_refresh_after_indexing(qtbot, window, docs):
    window.search_field.setText("budget")
    window.search_panel.run_search()
    window.folder_panel.add_folder(docs)
    index_and_wait(qtbot, window)
    assert window.results_list.count() == 2


def test_highlight_snippet_escapes_document_text():
    snippet = f"a <b>tag</b> & {HIGHLIGHT_START}budget{HIGHLIGHT_END}\n  plan"
    rendered = highlight_snippet(snippet)
    assert "&lt;b&gt;tag&lt;/b&gt; &amp;" in rendered
    assert ">budget</span> plan" in rendered
    assert HIGHLIGHT_START not in rendered and HIGHLIGHT_END not in rendered


def test_render_preview_shows_details():
    hit = SearchHit(
        path=str(Path("C:/docs/report.pdf")),
        snippet=f"{HIGHLIGHT_START}Revenue{HIGHLIGHT_END} grew",
        mtime=1717200000.0,
        size=2048,
        score=-1.0,
    )
    rendered = render_preview(hit)
    assert "<h3>report.pdf</h3>" in rendered
    assert "PDF" in rendered and "2.0 KB" in rendered
    assert ">Revenue</span> grew" in rendered


def test_selecting_result_updates_preview(qtbot, window, docs):
    (docs / "c.txt").write_text("<script>budget</script> notes", encoding="utf-8")
    window.folder_panel.add_folder(docs)
    index_and_wait(qtbot, window)
    window.search_field.setText("alpha budget")
    window.search_panel.run_search()

    # The top result is selected automatically.
    text = window.preview.toPlainText()
    assert "a.txt" in text and "alpha budget" in text

    window.search_field.setText("script")
    window.search_panel.run_search()
    assert "<script>budget</script>" in window.preview.toPlainText()

    window.search_field.clear()
    window.search_panel.run_search()
    assert window.preview.toPlainText() == ""


@pytest.fixture
def opened(monkeypatch):
    """Record open/show/warn calls instead of touching the OS."""
    calls = {"open": [], "show": [], "warn": []}
    monkeypatch.setattr(main_window, "open_document", lambda path: calls["open"].append(path) or True)
    monkeypatch.setattr(main_window, "show_in_folder", lambda path: calls["show"].append(path))
    monkeypatch.setattr(MainWindow, "_warn", lambda self, message: calls["warn"].append(message))
    return calls


def search_for(qtbot, window, docs, query):
    window.folder_panel.add_folder(docs)
    index_and_wait(qtbot, window)
    window.search_field.setText(query)
    window.search_panel.run_search()


def test_open_buttons_need_a_selection(window):
    assert not window.open_button.isEnabled()
    assert not window.show_button.isEnabled()


def test_activating_result_opens_document(qtbot, window, docs, opened):
    search_for(qtbot, window, docs, "alpha")
    window.results_list.setFocus()
    qtbot.keyClick(window.results_list, Qt.Key.Key_Return)
    assert opened["open"] == [(docs / "a.txt").resolve()]


def test_buttons_open_and_reveal_selected_result(qtbot, window, docs, opened):
    search_for(qtbot, window, docs, "beta")
    assert window.open_button.isEnabled()
    window.open_button.click()
    window.show_button.click()
    expected = (docs / "nested" / "b.md").resolve()
    assert opened["open"] == [expected]
    assert opened["show"] == [expected]


def test_missing_file_warns_instead_of_opening(qtbot, window, docs, opened):
    search_for(qtbot, window, docs, "alpha")
    (docs / "a.txt").unlink()
    window.open_button.click()
    window.show_button.click()
    assert opened["open"] == [] and opened["show"] == []
    assert len(opened["warn"]) == 2
    assert "no longer exists" in opened["warn"][0]


def test_progress_reaches_total(qtbot, window, docs):
    window.folder_panel.add_folder(docs)
    seen = []
    window.folder_panel.index_button.click()
    window.index_job.progress.connect(lambda done, total, _path: seen.append((done, total)))
    qtbot.waitUntil(lambda: window.index_job is None, timeout=10000)

    assert seen[-1] == (2, 2)
    assert window.progress_bar.isHidden()
    assert window.errors_button.isHidden()


def test_gui_stays_responsive_while_indexing(qtbot, window, docs, monkeypatch):
    for n in range(10):
        (docs / f"extra{n}.txt").write_text("filler", encoding="utf-8")
    real_extract = indexer.extract_text

    def slow_extract(path, data=None):
        time.sleep(0.05)
        return real_extract(path, data)

    monkeypatch.setattr(indexer, "extract_text", slow_extract)
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(window.progress_bar.value()))
    timer.start(20)

    window.folder_panel.add_folder(docs)
    window.folder_panel.index_button.click()
    assert not window.folder_panel.index_button.isEnabled()
    qtbot.waitUntil(lambda: window.index_job is None, timeout=10000)
    timer.stop()

    # The event loop kept running, and progress was visible part-way through.
    assert len(ticks) > 10
    assert any(0 < value < 12 for value in ticks)


def test_indexing_problems_are_listed(qtbot, window, docs, tmp_path, monkeypatch):
    (docs / "broken.pdf").write_bytes(b"not a pdf")
    gone = tmp_path / "unplugged"
    gone.mkdir()
    window.folder_panel.add_folder(docs)
    window.folder_panel.add_folder(gone)
    gone.rmdir()
    index_and_wait(qtbot, window)

    assert window.errors_button.isVisible()
    assert window.errors_button.text() == "2 problems…"

    shown = []
    monkeypatch.setattr(IndexErrorsDialog, "exec", lambda dialog: shown.append(dialog))
    window.errors_button.click()
    table = shown[0].table
    rows = {table.item(row, 0).text(): table.item(row, 1).text() for row in range(table.rowCount())}
    assert rows[str(gone.resolve())] == "Folder not found; skipped"
    assert "cannot parse PDF" in rows[str((docs / "broken.pdf").resolve())]


def test_folders_are_remembered(qtbot, tmp_path, docs):
    first = MainWindow(tmp_path / "index.db")
    qtbot.addWidget(first)
    first.folder_panel.add_folder(docs)
    first.folder_panel.add_folder(docs / "nested")
    first.folder_panel.folder_list.setCurrentRow(1)
    first.folder_panel.remove_selected()
    first.close()

    second = MainWindow(tmp_path / "index.db")
    qtbot.addWidget(second)
    assert second.folder_panel.folders() == [docs.resolve()]
    assert load_settings(tmp_path / "settings.json").folders == [str(docs.resolve())]


def test_settings_dialog_edits_preferences(qtbot, tmp_path):
    original = Settings(folders=["D:/Docs"], excluded_folders=["D:/Old"], result_limit=100)
    dialog = SettingsDialog(original)
    qtbot.addWidget(dialog)
    dialog.excluded_list.setCurrentRow(0)
    dialog.remove_selected_exclusions()
    dialog.add_exclusion(tmp_path)
    dialog.add_exclusion(tmp_path)  # duplicates are ignored
    dialog.result_limit.setValue(30)
    dialog.index_on_startup.setChecked(True)

    assert dialog.result_settings() == Settings(
        folders=["D:/Docs"],
        excluded_folders=[str(tmp_path.resolve())],
        result_limit=30,
        index_on_startup=True,
    )
    assert original.result_limit == 100  # the dialog doesn't modify the settings it was given


def test_settings_menu_opens_dialog(qtbot, window, monkeypatch):
    opened = []
    monkeypatch.setattr(SettingsDialog, "exec", lambda dialog: opened.append(dialog) or 0)
    window.settings_action.trigger()
    assert len(opened) == 1


def test_applied_settings_are_saved_and_used(qtbot, window, docs):
    for n in range(15):
        (docs / f"extra{n}.txt").write_text("budget", encoding="utf-8")
    window.folder_panel.add_folder(docs)
    window.apply_settings(
        Settings(
            folders=window.settings.folders,
            excluded_folders=[str(docs / "nested")],
            result_limit=10,
        )
    )
    index_and_wait(qtbot, window)

    assert indexed_count(window) == 16  # nested/b.md is excluded
    window.search_field.setText("budget")
    window.search_panel.run_search()
    assert window.results_list.count() == 10
    assert load_settings(window.settings_path).result_limit == 10


@pytest.fixture
def fast_monitor(monkeypatch):
    monkeypatch.setattr(MainWindow, "monitor_debounce", 0.1)


def test_changes_are_indexed_automatically(qtbot, window, docs, fast_monitor):
    window.folder_panel.add_folder(docs)
    index_and_wait(qtbot, window)
    assert window.monitor is not None

    (docs / "fresh.md").write_text("watchdog keyword", encoding="utf-8")
    window.search_field.setText("keyword")

    def found():
        window.search_panel.run_search()
        return result_names(window) == ["fresh.md"]

    qtbot.waitUntil(found, timeout=5000)
    # The row is committed slightly before the window hears the job finished.
    qtbot.waitUntil(
        lambda: window.statusBar().currentMessage().startswith("Index updated: 1 added"),
        timeout=5000,
    )

    (docs / "fresh.md").unlink()
    qtbot.waitUntil(lambda: not found() and window.index_job is None, timeout=5000)
    assert window.results_list.count() == 0


def test_watching_can_be_turned_off(qtbot, window, docs, fast_monitor):
    window.folder_panel.add_folder(docs)
    assert window.monitor is not None
    window.apply_settings(Settings(folders=window.settings.folders, watch_folders=False))
    assert window.monitor is None


def test_changes_to_index_files_are_ignored(qtbot, window, fast_monitor):
    window._on_files_changed({window.db_path.with_name("index.db-wal")})
    assert window.index_job is None and window.pending_changes == set()


@pytest.fixture
def slow_docs(docs, monkeypatch):
    for n in range(20):
        (docs / f"slow{n}.txt").write_text("filler", encoding="utf-8")
    real_extract = indexer.extract_text

    def slow_extract(path, data=None):
        time.sleep(0.05)
        return real_extract(path, data)

    monkeypatch.setattr(indexer, "extract_text", slow_extract)
    return docs


def test_cancel_stops_indexing_and_keeps_progress(qtbot, window, slow_docs):
    window.folder_panel.add_folder(slow_docs)
    window.folder_panel.index_button.click()
    assert window.cancel_button.isVisible() and window.pause_button.isVisible()
    qtbot.waitUntil(lambda: window.progress_bar.value() >= 3, timeout=5000)

    window.cancel_button.click()
    qtbot.waitUntil(lambda: window.index_job is None, timeout=5000)
    assert window.statusBar().currentMessage().startswith("Indexing cancelled")
    assert 0 < indexed_count(window) < 22
    assert window.cancel_button.isHidden() and window.pause_button.isHidden()
    assert window.folder_panel.index_button.isEnabled()


def test_pause_and_resume(qtbot, window, slow_docs):
    window.folder_panel.add_folder(slow_docs)
    window.folder_panel.index_button.click()
    qtbot.waitUntil(lambda: window.progress_bar.value() >= 2, timeout=5000)

    window.pause_button.click()
    assert window.pause_button.text() == "Resume"
    qtbot.wait(200)  # let the file in progress finish
    paused_at = indexed_count(window)
    assert paused_at >= 2  # work done before pausing is committed and searchable
    qtbot.wait(300)
    assert indexed_count(window) == paused_at
    assert window.statusBar().currentMessage().startswith("Paused")

    window.pause_button.click()
    qtbot.waitUntil(lambda: window.index_job is None, timeout=10000)
    assert indexed_count(window) == 22
    assert window.statusBar().currentMessage().startswith("Indexing complete")


def test_closing_during_indexing_cancels(qtbot, window, slow_docs):
    window.folder_panel.add_folder(slow_docs)
    window.folder_panel.index_button.click()
    qtbot.waitUntil(lambda: window.progress_bar.value() >= 1, timeout=5000)
    started = time.monotonic()
    window.close()
    assert time.monotonic() - started < 1.0


def test_settings_dialog_edits_skip_rules(qtbot):
    dialog = SettingsDialog(Settings(excluded_patterns=["~$*"], excluded_extensions=[".pdf"]))
    qtbot.addWidget(dialog)
    assert dialog.patterns_field.text() == "~$*"
    assert not dialog.type_checks[".pdf"].isChecked()

    dialog.patterns_field.setText(" ~$* , *.tmp,, node_modules, *.tmp ")
    dialog.type_checks[".pdf"].setChecked(True)
    dialog.type_checks[".md"].setChecked(False)
    result = dialog.result_settings()
    assert result.excluded_patterns == ["~$*", "*.tmp", "node_modules"]
    assert result.excluded_extensions == [".md"]


def test_gui_indexing_applies_skip_rules(qtbot, window, docs):
    (docs / "~$a.txt").write_text("lock", encoding="utf-8")
    window.folder_panel.add_folder(docs)
    window.apply_settings(
        Settings(folders=window.settings.folders, excluded_extensions=[".md"])
    )
    index_and_wait(qtbot, window)
    # nested/b.md is skipped by type and ~$a.txt by the default pattern.
    assert indexed_count(window) == 1
