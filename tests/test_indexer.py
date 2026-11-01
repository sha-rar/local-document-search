import os

import pytest
from local_document_search import indexer
from local_document_search.indexer import index_folder, prune_missing
from local_document_search.storage import IndexStore


@pytest.fixture
def store(tmp_path):
    with IndexStore(tmp_path / "index.db") as store:
        yield store


@pytest.fixture
def docs(tmp_path):
    root = tmp_path / "docs"
    (root / "sub").mkdir(parents=True)
    (root / "one.txt").write_text("alpha", encoding="utf-8")
    (root / "sub" / "two.md").write_text("beta", encoding="utf-8")
    (root / "skip.png").write_bytes(b"\x89PNG")
    return root


def test_indexes_supported_files_recursively(store, docs):
    report = index_folder(store, docs)
    assert report.added == 2
    assert report.unsupported == 1
    assert report.failed == []
    assert store.document_count() == 2


def test_broken_pdf_is_reported_without_stopping_scan(store, docs):
    (docs / "broken.pdf").write_bytes(b"not a pdf")
    report = index_folder(store, docs)
    assert report.added == 2
    assert [path.name for path, _reason in report.failed] == ["broken.pdf"]


def test_reindex_skips_unchanged_files(store, docs):
    index_folder(store, docs)
    report = index_folder(store, docs)
    assert (report.added, report.updated, report.unchanged) == (0, 0, 2)


def test_reindex_updates_changed_and_removes_deleted(store, docs):
    index_folder(store, docs)
    changed = docs / "one.txt"
    changed.write_text("alpha gamma", encoding="utf-8")
    stat = changed.stat()
    os.utime(changed, (stat.st_atime, stat.st_mtime + 10))
    (docs / "sub" / "two.md").unlink()

    report = index_folder(store, docs)
    assert (report.updated, report.removed) == (1, 1)
    assert store.document_count() == 1


def test_removal_is_limited_to_indexed_root(store, tmp_path, docs):
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.txt").write_text("kept", encoding="utf-8")
    index_folder(store, other)
    index_folder(store, docs)
    assert store.document_count() == 3


@pytest.mark.parametrize("destination", ["renamed.txt", "sub/moved.txt"])
def test_moved_file_keeps_entry_without_reextracting(store, docs, monkeypatch, destination):
    index_folder(store, docs)
    original = store.get_document(str(docs.resolve() / "one.txt"))
    (docs / "one.txt").rename(docs / destination)

    monkeypatch.setattr(indexer, "extract_text", lambda path: pytest.fail("re-extracted"))
    report = index_folder(store, docs)

    assert (report.moved, report.added, report.removed) == (1, 0, 0)
    moved = store.get_document(str((docs / destination).resolve()))
    assert moved is not None and moved.id == original.id
    assert store.get_document(str(docs.resolve() / "one.txt")) is None
    assert store.document_count() == 2


def test_move_between_indexed_roots(store, tmp_path, docs):
    other = tmp_path / "other"
    other.mkdir()
    index_folder(store, docs)
    (docs / "one.txt").rename(other / "one.txt")

    report = index_folder(store, other)
    assert (report.moved, report.added) == (1, 0)
    assert store.document_count() == 2


def test_copy_is_indexed_as_new_document(store, docs):
    index_folder(store, docs)
    (docs / "copy.txt").write_bytes((docs / "one.txt").read_bytes())
    report = index_folder(store, docs)
    assert (report.added, report.moved) == (1, 0)
    assert store.document_count() == 3


def test_touched_file_is_not_reextracted(store, docs, monkeypatch):
    index_folder(store, docs)
    path = docs / "one.txt"
    stat = path.stat()
    os.utime(path, (stat.st_atime, stat.st_mtime + 10))

    monkeypatch.setattr(indexer, "extract_text", lambda path: pytest.fail("re-extracted"))
    report = index_folder(store, docs)
    assert (report.unchanged, report.updated) == (2, 0)
    assert store.get_document(str(path.resolve())).mtime == stat.st_mtime + 10


def test_missing_hashes_are_backfilled(store, docs):
    index_folder(store, docs)
    store.connection.execute("UPDATE documents SET content_hash = NULL")
    report = index_folder(store, docs)
    assert report.unchanged == 2
    assert store.get_document(str(docs.resolve() / "one.txt")).content_hash is not None


def test_prune_removes_missing_files_outside_any_root(store, tmp_path, docs):
    other = tmp_path / "other"
    other.mkdir()
    (other / "gone.txt").write_text("bye", encoding="utf-8")
    index_folder(store, other)
    index_folder(store, docs)
    (other / "gone.txt").unlink()

    assert prune_missing(store) == 1
    assert store.document_count() == 2
