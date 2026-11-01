"""Run indexed full-text queries and return ranked results."""

import re
from dataclasses import dataclass

from .storage import IndexStore

SNIPPET_START = "["
SNIPPET_END = "]"
SNIPPET_ELLIPSIS = "..."
SNIPPET_TOKENS = 12

# Filename matches outrank body matches.
NAME_WEIGHT = 5.0
CONTENT_WEIGHT = 1.0

_TERM_PATTERN = re.compile(r'"([^"]*)"|(\S+)')


@dataclass(frozen=True)
class SearchHit:
    path: str
    snippet: str
    mtime: float
    score: float


def build_fts_query(text: str) -> str:
    """Turn user input into a safe FTS5 query.

    Bare words must all match; ``"quoted text"`` matches as a phrase. FTS5
    operators in the input are treated as literal terms.
    """
    terms = []
    for phrase, word in _TERM_PATTERN.findall(text):
        # Neither group can contain '"' once stray quotes are dropped, so wrapping is safe.
        term = (phrase or word.replace('"', "")).strip()
        if term:
            terms.append(f'"{term}"')
    return " ".join(terms)


def search(store: IndexStore, query: str, limit: int = 20) -> list[SearchHit]:
    fts_query = build_fts_query(query)
    if not fts_query:
        return []
    rows = store.connection.execute(
        """
        SELECT d.path, d.mtime,
               snippet(documents_fts, 1, ?, ?, ?, ?) AS snippet,
               bm25(documents_fts, ?, ?) AS score
        FROM documents_fts
        JOIN documents AS d ON d.id = documents_fts.rowid
        WHERE documents_fts MATCH ?
        ORDER BY score
        LIMIT ?
        """,
        (
            SNIPPET_START,
            SNIPPET_END,
            SNIPPET_ELLIPSIS,
            SNIPPET_TOKENS,
            NAME_WEIGHT,
            CONTENT_WEIGHT,
            fts_query,
            limit,
        ),
    ).fetchall()
    return [
        SearchHit(path=row["path"], snippet=row["snippet"], mtime=row["mtime"], score=row["score"])
        for row in rows
    ]
