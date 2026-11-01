import pytest
from local_document_search.indexer import index_folder
from local_document_search.search import build_fts_query, search
from local_document_search.storage import IndexStore


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
