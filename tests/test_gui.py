from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402

from local_document_search.gui import main_window  # noqa: E402
from local_document_search.gui.main_window import MainWindow  # noqa: E402
from local_document_search.gui.preview import (  # noqa: E402
    HIGHLIGHT_END,
    HIGHLIGHT_START,
    highlight_snippet,
    render_preview,
)
from local_document_search.search import SearchHit  # noqa: E402
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
