import pytest
from local_document_search.cli import main


def test_help_exits_successfully(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "Index and search documents locally" in capsys.readouterr().out


def test_index_then_search(tmp_path, capsys):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "notes.md").write_text("Quarterly budget review", encoding="utf-8")
    db = tmp_path / "index.db"

    assert main(["--db", str(db), "index", str(docs)]) == 0
    assert "1 added" in capsys.readouterr().out

    assert main(["--db", str(db), "search", "budget"]) == 0
    out = capsys.readouterr().out
    assert "notes.md" in out
    assert "[budget]" in out


def test_search_reports_no_matches(tmp_path, capsys):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("hello", encoding="utf-8")
    db = tmp_path / "index.db"
    main(["--db", str(db), "index", str(docs)])
    capsys.readouterr()

    assert main(["--db", str(db), "search", "absent"]) == 0
    assert "No matches." in capsys.readouterr().out


def test_index_rejects_missing_folder(tmp_path, capsys):
    assert main(["--db", str(tmp_path / "index.db"), "index", str(tmp_path / "nope")]) == 1
    assert "not a directory" in capsys.readouterr().err


def test_search_without_index_fails(tmp_path, capsys):
    assert main(["--db", str(tmp_path / "missing.db"), "search", "x"]) == 1
    assert "no index" in capsys.readouterr().err
    assert not (tmp_path / "missing.db").exists()
