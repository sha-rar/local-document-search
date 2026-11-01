import pytest
from local_document_search.cli import main


def test_help_exits_successfully(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "Index and search documents locally" in capsys.readouterr().out


def test_index_reports_not_implemented(capsys):
    assert main(["index", "."]) == 2
    assert "not implemented" in capsys.readouterr().out
