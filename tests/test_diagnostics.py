"""Structured logs and diagnostics record what happened, especially what went wrong."""

import json
import logging

from local_document_search import indexer
from local_document_search.cli import main
from local_document_search.diagnostics import collect_diagnostics, configure_logging
from local_document_search.indexer import index_folder
from local_document_search.storage import IndexStore


def read_log(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def events(entries, name):
    return [entry for entry in entries if entry.get("event") == name]


def test_log_lines_are_json_with_extra_fields(tmp_path):
    log_path = configure_logging(tmp_path)
    logging.getLogger("local_document_search.test").info(
        "Something happened", extra={"event": "probe", "count": 3, "path": tmp_path}
    )
    [entry] = read_log(log_path)
    assert entry["message"] == "Something happened"
    assert entry["level"] == "INFO"
    assert entry["logger"] == "local_document_search.test"
    assert entry["event"] == "probe" and entry["count"] == 3
    assert entry["path"] == str(tmp_path)  # non-JSON values are stored as text
    assert entry["time"].endswith("+00:00")


def test_reconfiguring_does_not_duplicate_lines(tmp_path):
    configure_logging(tmp_path)
    log_path = configure_logging(tmp_path)
    logging.getLogger("local_document_search").info("once")
    assert len(read_log(log_path)) == 1


def test_indexing_records_failures_and_a_summary(tmp_path):
    log_path = configure_logging(tmp_path / "logs")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "good.txt").write_text("fine", encoding="utf-8")
    (docs / "bad.pdf").write_bytes(b"not a pdf")
    with IndexStore(tmp_path / "index.db") as store:
        index_folder(store, docs)

    entries = read_log(log_path)
    [failure] = events(entries, "file_failed")
    assert failure["level"] == "WARNING"
    assert failure["path"].endswith("bad.pdf")
    assert failure["reason"].startswith("cannot parse PDF")
    [summary] = events(entries, "scan_finished")
    assert summary["added"] == 1 and summary["failed"] == 1
    assert summary["seconds"] >= 0
    assert events(entries, "index_created")


def test_unexpected_errors_are_logged_with_a_traceback(tmp_path, monkeypatch):
    log_path = configure_logging(tmp_path / "logs")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("x", encoding="utf-8")

    def broken(path, data=None):
        raise ValueError("parser bug")

    monkeypatch.setattr(indexer, "extract_text", broken)
    with IndexStore(tmp_path / "index.db") as store:
        index_folder(store, docs)

    [error] = events(read_log(log_path), "file_error")
    assert error["level"] == "ERROR" and error["error"] == "ValueError"
    assert "ValueError: parser bug" in error["traceback"]


def test_cli_logs_to_the_app_data_folder(isolated_app_data, tmp_path, capsys):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("x", encoding="utf-8")
    main(["--db", str(tmp_path / "index.db"), "index", str(docs)])

    log_path = isolated_app_data / "FileLens" / "logs" / "filelens.log"
    assert events(read_log(log_path), "scan_finished")
    assert capsys.readouterr().err == ""  # quiet unless --verbose


def test_cli_verbose_prints_log_messages(tmp_path, capsys):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "bad.docx").write_bytes(b"nope")
    main(["--db", str(tmp_path / "index.db"), "--verbose", "index", str(docs)])
    err = capsys.readouterr().err
    assert "warning: Could not index file" in err
    assert "event=file_failed" in err


def test_cli_logs_damaged_index(isolated_app_data, tmp_path, capsys):
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"junk" * 100)
    main(["--db", str(broken), "search", "x"])
    log_path = isolated_app_data / "FileLens" / "logs" / "filelens.log"
    [entry] = events(read_log(log_path), "index_damaged")
    assert "file is not a database" in entry["traceback"]


def test_diagnostics_command(tmp_path, capsys):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("x", encoding="utf-8")
    db = tmp_path / "index.db"
    main(["--db", str(db), "index", str(docs)])
    capsys.readouterr()

    assert main(["--db", str(db), "diagnostics"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["documents"] == 1 and info["fts5"] is True
    assert info["index_path"] == str(db)
    assert info["log_path"].endswith("filelens.log")
    assert {"app_version", "python", "platform", "sqlite"} <= set(info)


def test_diagnostics_survive_a_damaged_index(tmp_path):
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"junk" * 100)
    info = collect_diagnostics(broken)
    assert info["index_exists"] is True
    assert "file is not a database" in info["index_error"]
