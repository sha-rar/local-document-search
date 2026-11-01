import time

import pytest
from local_document_search.monitor import FolderMonitor


def wait_for(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def watched(tmp_path):
    root = tmp_path / "watched"
    root.mkdir()
    batches = []
    monitor = FolderMonitor([root], batches.append, debounce=0.1)
    monitor.start()
    yield root.resolve(), batches, monitor
    monitor.stop()


def changed(batches):
    return set().union(*batches) if batches else set()


def test_reports_created_modified_and_deleted_files(watched):
    root, batches, _monitor = watched
    note = root / "note.txt"
    note.write_text("one", encoding="utf-8")
    assert wait_for(lambda: note in changed(batches))

    batches.clear()
    note.write_text("two", encoding="utf-8")
    assert wait_for(lambda: note in changed(batches))

    batches.clear()
    note.unlink()
    assert wait_for(lambda: note in changed(batches))


def test_reports_both_ends_of_a_move(watched):
    root, batches, _monitor = watched
    (root / "sub").mkdir()
    source = root / "a.md"
    source.write_text("x", encoding="utf-8")
    assert wait_for(lambda: source in changed(batches))
    batches.clear()

    target = root / "sub" / "b.md"
    source.rename(target)
    assert wait_for(lambda: {source, target} <= changed(batches))


def test_ignores_new_unsupported_files(watched):
    root, batches, _monitor = watched
    (root / "photo.jpg").write_bytes(b"\xff\xd8")
    marker = root / "marker.txt"
    marker.write_text("x", encoding="utf-8")
    assert wait_for(lambda: marker in changed(batches))
    assert root / "photo.jpg" not in changed(batches)


def test_burst_of_changes_arrives_as_one_batch(watched):
    root, batches, _monitor = watched
    for n in range(20):
        (root / f"f{n}.txt").write_text("x", encoding="utf-8")
    assert wait_for(lambda: len(changed(batches)) == 20)
    assert len(batches) <= 2


def test_stop_ends_reporting(watched):
    root, batches, monitor = watched
    monitor.stop()
    (root / "late.txt").write_text("x", encoding="utf-8")
    time.sleep(0.4)
    assert batches == []


def test_missing_folder_is_skipped(tmp_path):
    monitor = FolderMonitor([tmp_path / "absent"], lambda paths: None)
    monitor.start()
    assert monitor.watched == []
    monitor.stop()
