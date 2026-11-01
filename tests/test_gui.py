from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402

from local_document_search.gui.main_window import MainWindow  # noqa: E402
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
