import signal

import pytest
from local_document_search import indexer
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


def test_search_filters(tmp_path, capsys):
    docs = tmp_path / "docs"
    (docs / "sub").mkdir(parents=True)
    (docs / "a.txt").write_text("budget", encoding="utf-8")
    (docs / "sub" / "b.md").write_text("budget", encoding="utf-8")
    db = tmp_path / "index.db"
    main(["--db", str(db), "index", str(docs)])
    capsys.readouterr()

    main(["--db", str(db), "search", "budget", "--type", "md"])
    out = capsys.readouterr().out
    assert "b.md" in out and "a.txt" not in out

    main(["--db", str(db), "search", "budget", "--in", str(docs / "sub")])
    out = capsys.readouterr().out
    assert "b.md" in out and "a.txt" not in out

    main(["--db", str(db), "search", "budget", "--before", "2000-01-01"])
    assert "No matches." in capsys.readouterr().out


def test_search_rejects_bad_date(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--db", str(tmp_path / "index.db"), "search", "x", "--after", "01/02/2024"])
    assert exc.value.code == 2
    assert "expected YYYY-MM-DD" in capsys.readouterr().err


def test_prune_removes_missing_files(tmp_path, capsys):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("alpha", encoding="utf-8")
    (docs / "b.txt").write_text("beta", encoding="utf-8")
    db = tmp_path / "index.db"
    main(["--db", str(db), "index", str(docs)])
    (docs / "a.txt").unlink()
    capsys.readouterr()

    assert main(["--db", str(db), "prune"]) == 0
    assert "Removed 1 missing documents; 1 remain" in capsys.readouterr().out


def test_index_exclude(tmp_path, capsys):
    docs = tmp_path / "docs"
    (docs / "private").mkdir(parents=True)
    (docs / "a.txt").write_text("budget", encoding="utf-8")
    (docs / "private" / "b.txt").write_text("budget", encoding="utf-8")
    db = tmp_path / "index.db"

    main(["--db", str(db), "index", str(docs), "--exclude", str(docs / "private")])
    assert "1 added" in capsys.readouterr().out
    main(["--db", str(db), "search", "budget"])
    out = capsys.readouterr().out
    assert "a.txt" in out and "b.txt" not in out


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


def test_ctrl_c_stops_indexing_gracefully(tmp_path, capsys, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    for n in range(5):
        (docs / f"f{n}.txt").write_text("x", encoding="utf-8")
    real_extract = indexer.extract_text
    calls = []

    def interrupt_once(path, data=None):
        calls.append(path)
        if len(calls) == 1:
            signal.raise_signal(signal.SIGINT)
        return real_extract(path, data)

    monkeypatch.setattr(indexer, "extract_text", interrupt_once)
    assert main(["--db", str(tmp_path / "index.db"), "index", str(docs)]) == 130
    captured = capsys.readouterr()
    assert "Stopping after the current file" in captured.err
    assert "Cancelled indexing" in captured.out and "1 added" in captured.out
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


def test_index_exclude_names_and_types(tmp_path, capsys):
    docs = tmp_path / "docs"
    docs.mkdir()
    for name in ("a.txt", "~$a.txt", "b.md", "c.txt"):
        (docs / name).write_text("budget", encoding="utf-8")
    db = tmp_path / "index.db"

    main(["--db", str(db), "index", str(docs), "--exclude-name", "~$*", "--skip-type", "md"])
    assert "2 added" in capsys.readouterr().out
