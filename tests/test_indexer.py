import os
import subprocess
import sys
from pathlib import Path
import threading

import pytest
from local_document_search import indexer
from local_document_search.indexer import (
    Exclusions,
    IndexControl,
    index_folder,
    prune_missing,
    remove_folder,
    update_paths,
)
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

    monkeypatch.setattr(indexer, "extract_text", lambda *args: pytest.fail("re-extracted"))
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

    monkeypatch.setattr(indexer, "extract_text", lambda *args: pytest.fail("re-extracted"))
    report = index_folder(store, docs)
    assert (report.unchanged, report.updated) == (2, 0)
    assert store.get_document(str(path.resolve())).mtime == stat.st_mtime + 10


def test_missing_hashes_are_backfilled(store, docs):
    index_folder(store, docs)
    store.connection.execute("UPDATE documents SET content_hash = NULL")
    report = index_folder(store, docs)
    assert report.unchanged == 2
    assert store.get_document(str(docs.resolve() / "one.txt")).content_hash is not None


def test_remove_folder_keeps_documents_under_kept_folders(store, docs):
    index_folder(store, docs)
    assert remove_folder(store, docs, keep=[docs / "sub"]) == 1
    assert store.get_document(str((docs / "sub" / "two.md").resolve())) is not None


def test_prune_removes_missing_files_outside_any_root(store, tmp_path, docs):
    other = tmp_path / "other"
    other.mkdir()
    (other / "gone.txt").write_text("bye", encoding="utf-8")
    index_folder(store, other)
    index_folder(store, docs)
    (other / "gone.txt").unlink()

    assert prune_missing(store) == 1
    assert store.document_count() == 2


def test_excluded_folders_are_skipped_and_removed(store, docs):
    (docs / "sub" / "deeper").mkdir()
    (docs / "sub" / "deeper" / "three.txt").write_text("gamma", encoding="utf-8")
    index_folder(store, docs)
    assert store.document_count() == 3

    report = index_folder(store, docs, exclude=[docs / "sub"])
    assert report.removed == 2
    assert store.all_paths() == [str(docs.resolve() / "one.txt")]


def test_excluding_the_root_indexes_nothing(store, docs):
    report = index_folder(store, docs, exclude=[docs])
    assert report.added == 0 and store.document_count() == 0


def test_update_paths_applies_individual_changes(store, docs, monkeypatch):
    index_folder(store, docs)
    root = docs.resolve()
    new = root / "new.txt"
    new.write_text("delta", encoding="utf-8")
    changed = root / "one.txt"
    changed.write_text("alpha changed", encoding="utf-8")
    stat = changed.stat()
    os.utime(changed, (stat.st_atime, stat.st_mtime + 10))
    (root / "sub" / "two.md").unlink()

    report = update_paths(store, [new, changed, root / "sub" / "two.md"], [docs])
    assert (report.added, report.updated, report.removed) == (1, 1, 1)
    assert store.document_count() == 2


def test_update_paths_handles_moves_and_folder_deletion(store, docs, monkeypatch):
    index_folder(store, docs)
    root = docs.resolve()
    (root / "one.txt").rename(root / "sub" / "one.txt")
    monkeypatch.setattr(indexer, "extract_text", lambda *args: pytest.fail("re-extracted"))
    # Order of reported paths must not matter.
    report = update_paths(store, [root / "one.txt", root / "sub" / "one.txt"], [docs])
    assert (report.moved, report.removed) == (1, 0)

    for path in (root / "sub").iterdir():
        path.unlink()
    (root / "sub").rmdir()
    report = update_paths(store, [root / "sub"], [docs])
    assert report.removed == 2
    assert store.document_count() == 0


def test_update_paths_indexes_new_folders(store, docs):
    index_folder(store, docs)
    added = docs.resolve() / "added"
    (added / "inner").mkdir(parents=True)
    (added / "inner" / "x.md").write_text("x", encoding="utf-8")
    (added / "y.txt").write_text("y", encoding="utf-8")
    assert update_paths(store, [added], [docs]).added == 2


def test_update_paths_ignores_outside_and_excluded(store, tmp_path, docs):
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    private = docs / "sub" / "private.txt"
    private.write_text("x", encoding="utf-8")
    report = update_paths(
        store, [outside.resolve(), private.resolve()], [docs], exclude=[docs / "sub"]
    )
    assert report.added == 0 and store.document_count() == 0


def test_cancel_keeps_progress_and_skips_removal(store, docs):
    index_folder(store, docs)
    (docs / "one.txt").unlink()
    for n in range(5):
        (docs / f"new{n}.txt").write_text("x", encoding="utf-8")
    control = IndexControl()
    seen = []

    def cancel_after_two(path):
        seen.append(path)
        if len(seen) == 2:
            control.cancel()

    report = index_folder(store, docs, progress=cancel_after_two, control=control)
    assert report.cancelled
    assert report.removed == 0  # one.txt's entry survives: the scan was incomplete
    assert report.added + report.unchanged == 2
    assert store.get_document(str(docs.resolve() / "one.txt")) is not None


def test_pause_blocks_until_resumed(store, tmp_path, docs):
    control = IndexControl()
    control.pause()
    result = {}

    def run():
        # SQLite connections belong to the thread that opened them.
        with IndexStore(tmp_path / "paused.db") as own_store:
            result["report"] = index_folder(own_store, docs, control=control)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(0.3)
    assert thread.is_alive() and control.paused

    control.resume()
    thread.join(5)
    assert result["report"].added == 2 and not result["report"].cancelled


def test_cancel_wakes_a_paused_indexer(tmp_path, docs):
    control = IndexControl()
    control.pause()
    control.cancel()
    assert not control.paused
    with IndexStore(tmp_path / "index.db") as store:
        assert index_folder(store, docs, control=control).cancelled


def test_large_files_are_hashed_in_chunks(store, docs, monkeypatch):
    monkeypatch.setattr(indexer, "WHOLE_FILE_LIMIT", 0)
    report = index_folder(store, docs)
    assert report.added == 2
    record = store.get_document(str(docs.resolve() / "one.txt"))
    assert record.content_hash == indexer.file_hash(docs / "one.txt")


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows-only")
def test_junction_loops_are_not_followed(store, docs):
    loop = docs / "sub" / "loop"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(loop), str(docs)], capture_output=True
    )
    if result.returncode != 0:
        pytest.skip("could not create a junction")
    report = index_folder(store, docs)
    assert report.added == 2
    assert not any(Path(path).is_relative_to(loop) for path in store.all_paths())


def test_exclusions_match_names_case_insensitively(tmp_path):
    rules = Exclusions(
        patterns=("~$*", "Node_Modules", "*.TMP"), extensions=("PDF", ".md")
    ).resolved()
    assert rules.excludes_file(Path("~$report.docx"))
    assert rules.excludes_file(Path("draft.tmp"))
    assert rules.excludes_file(Path("scan.pdf")) and rules.excludes_file(Path("notes.MD"))
    assert not rules.excludes_file(Path("report.docx"))
    assert rules.excludes_dir(Path("node_modules"))
    assert rules.excludes_path(tmp_path / "node_modules" / "pkg" / "a.txt", tmp_path)
    assert not rules.excludes_path(tmp_path / "src" / "a.txt", tmp_path)


def test_patterns_and_types_are_skipped_and_removed(store, docs):
    (docs / "~$lock.txt").write_text("lock", encoding="utf-8")
    (docs / "node_modules" / "pkg").mkdir(parents=True)
    (docs / "node_modules" / "pkg" / "readme.md").write_text("pkg", encoding="utf-8")
    index_folder(store, docs)
    assert store.document_count() == 4

    rules = Exclusions(patterns=("~$*", "node_modules"), extensions=("md",))
    report = index_folder(store, docs, exclude=rules)
    assert report.removed == 3
    assert store.all_paths() == [str(docs.resolve() / "one.txt")]


def test_update_paths_respects_patterns_and_types(store, docs):
    root = docs.resolve()
    (root / "node_modules").mkdir()
    (root / "node_modules" / "a.txt").write_text("x", encoding="utf-8")
    (root / "keep.txt").write_text("x", encoding="utf-8")
    (root / "skip.md").write_text("x", encoding="utf-8")
    rules = Exclusions(patterns=("node_modules",), extensions=(".md",))
    changed = [root / "node_modules" / "a.txt", root / "keep.txt", root / "skip.md"]
    assert update_paths(store, changed, [docs], exclude=rules).added == 1
    assert store.all_paths() == [str(root / "keep.txt")]
