import os

import pytest
from local_document_search.indexer import index_folder
from local_document_search.search import SearchFilters, build_fts_query, search
from local_document_search.storage import IndexStore

JAN_2024 = 1704067200.0  # 2024-01-01 00:00 UTC
JUN_2024 = 1717200000.0  # 2024-06-01 00:00 UTC


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "recipes.txt").write_text(
        "Bake the bread at high heat. Bread needs time to rise.", encoding="utf-8"
    )
    (root / "travel.md").write_text("Pack light and bring bread for the train.", encoding="utf-8")
    (root / "notes.txt").write_text("The quick brown fox jumps.", encoding="utf-8")
    with IndexStore(tmp_path / "index.db") as store:
        index_folder(store, root)
        yield store


def test_build_fts_query_quotes_terms():
    assert build_fts_query('brown "quick fox" AND') == '"brown" "quick fox" "AND"'
    assert build_fts_query('say "hi') == '"say" "hi"'
    assert build_fts_query("   ") == ""


def test_keyword_search_ranks_by_relevance(store):
    hits = search(store, "bread")
    assert [h.path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for h in hits] == [
        "recipes.txt",
        "travel.md",
    ]
    assert "[Bread]" in hits[0].snippet or "[bread]" in hits[0].snippet


def test_all_words_must_match(store):
    assert len(search(store, "bread train")) == 1


def test_phrase_search(store):
    assert len(search(store, '"quick brown"')) == 1
    assert search(store, '"brown quick"') == []


def test_filename_matches(store):
    assert len(search(store, "recipes")) == 1


def test_operator_characters_do_not_error(store):
    assert search(store, "fox* OR (NEAR") == []
    assert search(store, "") == []


@pytest.fixture
def filter_root(tmp_path):
    """Files mentioning "invoice" spread across types, folders and dates."""
    root = tmp_path / "filtered"
    files = {
        "work/jan.txt": JAN_2024,
        "work/jun.md": JUN_2024,
        "work/deep/jun.txt": JUN_2024,
        "work2/jan.txt": JAN_2024,
    }
    for relative, mtime in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("invoice", encoding="utf-8")
        os.utime(path, (mtime, mtime))
    return root


@pytest.fixture
def filter_store(tmp_path, filter_root):
    with IndexStore(tmp_path / "filtered.db") as store:
        index_folder(store, filter_root)
        yield store


def found(store, filters, root):
    hits = search(store, "invoice", filters=filters)
    return sorted(os.path.relpath(hit.path, root).replace(os.sep, "/") for hit in hits)


def test_filter_by_type(filter_store, filter_root):
    assert found(filter_store, SearchFilters(extensions=("MD",)), filter_root) == ["work/jun.md"]
    assert len(found(filter_store, SearchFilters(extensions=(".txt", "md")), filter_root)) == 4


def test_filter_by_folder_includes_subfolders_only(filter_store, filter_root):
    assert found(filter_store, SearchFilters(folder=filter_root / "work"), filter_root) == [
        "work/deep/jun.txt",
        "work/jan.txt",
        "work/jun.md",
    ]


def test_filter_by_modified_date(filter_store, filter_root):
    after = SearchFilters(modified_after=JUN_2024)
    before = SearchFilters(modified_before=JUN_2024)
    assert found(filter_store, after, filter_root) == ["work/deep/jun.txt", "work/jun.md"]
    assert found(filter_store, before, filter_root) == ["work/jan.txt", "work2/jan.txt"]


def test_filters_combine(filter_store, filter_root):
    filters = SearchFilters(
        extensions=("txt",), folder=filter_root / "work", modified_after=JUN_2024
    )
    assert found(filter_store, filters, filter_root) == ["work/deep/jun.txt"]
