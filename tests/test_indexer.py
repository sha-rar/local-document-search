import os

import pytest
from local_document_search.indexer import index_folder
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
