import pytest

pytest.importorskip("PySide6")

from local_document_search.gui.main_window import MainWindow  # noqa: E402


@pytest.fixture
def window(qtbot, tmp_path):
    window = MainWindow(tmp_path / "index.db")
    qtbot.addWidget(window)
    window.show()
    return window


def test_main_window_layout(window):
    assert window.windowTitle() == "FileLens"
    assert window.search_field.placeholderText() == "Search document contents"
    assert window.results_list.count() == 0
    assert window.statusBar().currentMessage() == "Ready"
