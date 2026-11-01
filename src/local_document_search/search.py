"""Run indexed full-text queries and return ranked results."""

import os
import re
from dataclasses import dataclass
from pathlib import Path

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
    size: int
    score: float


@dataclass(frozen=True)
class SearchFilters:
    """Optional restrictions on search results; unset fields don't filter."""

    extensions: tuple[str, ...] = ()
    folder: Path | None = None
    modified_after: float | None = None
    modified_before: float | None = None

    def to_sql(self) -> tuple[str, list]:
        """Return extra WHERE conditions (each prefixed with AND) and their parameters."""
        clauses = []
        params: list = []
        if self.extensions:
            normalized = [normalize_extension(ext) for ext in self.extensions]
            clauses.append(f"d.extension IN ({', '.join('?' * len(normalized))})")
            params.extend(normalized)
        if self.folder is not None:
            folder = str(Path(self.folder).resolve())
            prefix = folder if folder.endswith(os.sep) else folder + os.sep
            clauses.append("(d.directory = ? OR substr(d.directory, 1, ?) = ?)")
            params.extend([folder, len(prefix), prefix])
        if self.modified_after is not None:
            clauses.append("d.mtime >= ?")
            params.append(self.modified_after)
        if self.modified_before is not None:
            clauses.append("d.mtime < ?")
            params.append(self.modified_before)
        return "".join(f" AND {clause}" for clause in clauses), params


def normalize_extension(extension: str) -> str:
    extension = extension.strip().lower()
    return extension if extension.startswith(".") else "." + extension


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


def search(
    store: IndexStore,
    query: str,
    limit: int = 20,
    filters: SearchFilters | None = None,
) -> list[SearchHit]:
    fts_query = build_fts_query(query)
    if not fts_query:
        return []
    filter_sql, filter_params = (filters or SearchFilters()).to_sql()
    rows = store.connection.execute(
        f"""
        SELECT d.path, d.mtime, d.size,
               snippet(documents_fts, 1, ?, ?, ?, ?) AS snippet,
               bm25(documents_fts, ?, ?) AS score
        FROM documents_fts
        JOIN documents AS d ON d.id = documents_fts.rowid
        WHERE documents_fts MATCH ?{filter_sql}
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
            *filter_params,
            limit,
        ),
    ).fetchall()
    return [
        SearchHit(
            path=row["path"],
            snippet=row["snippet"],
            mtime=row["mtime"],
            size=row["size"],
            score=row["score"],
        )
        for row in rows
    ]
