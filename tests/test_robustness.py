"""One bad file, or a bad index, must never take the whole application down."""

import sqlite3
import zipfile

import pytest
from helpers import write_docx, write_pdf
from local_document_search import indexer
from local_document_search.cli import main
from local_document_search.extractors import OLE_SIGNATURE
from local_document_search.indexer import index_folder, update_paths
from local_document_search.search import search
from local_document_search.storage import IndexStore


@pytest.fixture
def store(tmp_path):
    with IndexStore(tmp_path / "index.db") as store:
        yield store


@pytest.fixture
def damaged_folder(tmp_path):
    """Good documents mixed with every kind of broken one we know about."""
    root = tmp_path / "mixed"
    root.mkdir()
    (root / "good.txt").write_text("healthy text", encoding="utf-8")
    write_pdf(root / "good.pdf", ["healthy pdf"])
    write_docx(root / "good.docx", ["healthy docx"])
    (root / "empty.txt").write_bytes(b"")
    (root / "binary.txt").write_bytes(bytes(range(256)) * 4)
    (root / "truncated.pdf").write_bytes((root / "good.pdf").read_bytes()[:200])
    (root / "empty.pdf").write_bytes(b"")
    (root / "not-really.docx").write_bytes(b"plain text pretending to be Word")
    (root / "locked.docx").write_bytes(OLE_SIGNATURE + b"\0" * 504)
    with zipfile.ZipFile(root / "wrong-zip.docx", "w") as archive:
        archive.writestr("hello.txt", "a zip, but not a Word document")
    return root


def test_damaged_files_are_reported_and_the_rest_indexed(store, damaged_folder):
    report = index_folder(store, damaged_folder)

    failed = {path.name for path, _reason in report.failed}
    assert failed == {
        "truncated.pdf",
        "empty.pdf",
        "not-really.docx",
        "locked.docx",
        "wrong-zip.docx",
    }
    # Empty and binary text files are still indexed (as empty/garbled text), not errors.
    assert report.added == 5
    assert [hit.path.endswith("good.pdf") for hit in search(store, "healthy pdf")] == [True]
    assert len(search(store, "healthy")) == 3


def test_unexpected_extractor_error_affects_only_that_file(store, damaged_folder, monkeypatch):
    real_extract = indexer.extract_text

    def explode_on_good_docx(path, data=None):
        if path.name == "good.docx":
            raise MemoryError()
        return real_extract(path, data)

    monkeypatch.setattr(indexer, "extract_text", explode_on_good_docx)
    report = index_folder(store, damaged_folder)
    reasons = dict((path.name, reason) for path, reason in report.failed)
    assert reasons["good.docx"] == "unexpected error: MemoryError: "
    assert report.added == 4

    # The same protection applies to changes reported by the folder watcher.
    (damaged_folder / "good.docx").touch()
    store.connection.execute("DELETE FROM documents")
    store.connection.execute("DELETE FROM documents_fts")
    changed = [damaged_folder.resolve() / "good.docx", damaged_folder.resolve() / "good.txt"]
    update = update_paths(store, changed, [damaged_folder])
    assert update.added == 1 and len(update.failed) == 1


def test_text_that_sqlite_cannot_store_is_cleaned(store, tmp_path, monkeypatch):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "odd.pdf").write_bytes(b"placeholder")
    monkeypatch.setattr(
        indexer, "extract_text", lambda path, data=None: "broken \ud800 surrogate with keyword"
    )
    report = index_folder(store, root)
    assert report.added == 1 and report.failed == []
    assert len(search(store, "keyword")) == 1


def test_oversized_files_are_skipped(store, tmp_path, monkeypatch):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "huge.txt").write_text("x" * 2000, encoding="utf-8")
    (root / "small.txt").write_text("y", encoding="utf-8")
    monkeypatch.setattr(indexer, "MAX_EXTRACT_SIZE", 1000)
    report = index_folder(store, root)
    assert report.added == 1
    assert report.failed[0][0].name == "huge.txt"
    assert report.failed[0][1].startswith("too large to index")


def test_database_errors_still_stop_the_scan(store, tmp_path, monkeypatch):
    """A broken index isn't a per-file problem; carrying on would fail every file."""
    root = tmp_path / "docs"
    root.mkdir()
    (root / "a.txt").write_text("a", encoding="utf-8")

    def disk_full(*args, **kwargs):
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(store, "upsert_document", disk_full)
    with pytest.raises(sqlite3.OperationalError):
        index_folder(store, root)


def test_cli_explains_a_damaged_index(tmp_path, capsys):
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"this is not an SQLite database" * 10)
    assert main(["--db", str(broken), "search", "budget"]) == 1
    err = capsys.readouterr().err
    assert "is damaged" in err and "rebuild" in err
    assert "Traceback" not in err


def test_cli_indexes_damaged_folder_successfully(tmp_path, damaged_folder, capsys):
    assert main(["--db", str(tmp_path / "index.db"), "index", str(damaged_folder)]) == 0
    captured = capsys.readouterr()
    assert "5 added" in captured.out and "5 failed" in captured.out
    assert captured.err.count("failed:") == 5
