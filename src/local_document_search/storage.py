"""Persist metadata and full-text content in SQLite FTS5."""

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    indexed_at REAL NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    name,
    content,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


def default_db_path() -> Path:
    """Per-user index location, kept outside any repository or indexed folder."""
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "FileLens" / "index.db"


@dataclass(frozen=True)
class DocumentRecord:
    id: int
    path: str
    mtime: float
    size: int


class IndexStore:
    """SQLite-backed document index. Rows in ``documents_fts`` share rowids with ``documents``."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    def __enter__(self) -> "IndexStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def commit(self) -> None:
        self.connection.commit()

    def get_document(self, path: str) -> DocumentRecord | None:
        row = self.connection.execute(
            "SELECT id, path, mtime, size FROM documents WHERE path = ?", (path,)
        ).fetchone()
        return DocumentRecord(**row) if row else None

    def upsert_document(self, path: str, mtime: float, size: int, text: str) -> None:
        existing = self.get_document(path)
        name = Path(path).name
        now = time.time()
        if existing is None:
            cursor = self.connection.execute(
                "INSERT INTO documents (path, mtime, size, indexed_at) VALUES (?, ?, ?, ?)",
                (path, mtime, size, now),
            )
            self.connection.execute(
                "INSERT INTO documents_fts (rowid, name, content) VALUES (?, ?, ?)",
                (cursor.lastrowid, name, text),
            )
        else:
            self.connection.execute(
                "UPDATE documents SET mtime = ?, size = ?, indexed_at = ? WHERE id = ?",
                (mtime, size, now, existing.id),
            )
            self.connection.execute(
                "UPDATE documents_fts SET name = ?, content = ? WHERE rowid = ?",
                (name, text, existing.id),
            )

    def delete_document(self, path: str) -> None:
        existing = self.get_document(path)
        if existing is None:
            return
        self.connection.execute("DELETE FROM documents_fts WHERE rowid = ?", (existing.id,))
        self.connection.execute("DELETE FROM documents WHERE id = ?", (existing.id,))

    def all_paths(self) -> list[str]:
        return [row["path"] for row in self.connection.execute("SELECT path FROM documents")]

    def document_count(self) -> int:
        return self.connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
