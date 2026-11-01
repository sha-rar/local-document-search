"""Persist metadata and full-text content in SQLite FTS5."""

import os
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE documents (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    extension TEXT NOT NULL,
    directory TEXT NOT NULL,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    indexed_at REAL NOT NULL
);
CREATE INDEX documents_extension ON documents (extension);
CREATE INDEX documents_mtime ON documents (mtime);
CREATE VIRTUAL TABLE documents_fts USING fts5(
    name,
    content,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


def _add_path_metadata(connection: sqlite3.Connection) -> None:
    # Separate execute() calls (not executescript) keep the migration in one transaction.
    for column in ("name", "extension", "directory"):
        connection.execute(f"ALTER TABLE documents ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
    connection.execute("CREATE INDEX documents_extension ON documents (extension)")
    connection.execute("CREATE INDEX documents_mtime ON documents (mtime)")
    rows = connection.execute("SELECT id, path FROM documents").fetchall()
    connection.executemany(
        "UPDATE documents SET name = ?, extension = ?, directory = ? WHERE id = ?",
        [(*path_metadata(row[1]), row[0]) for row in rows],
    )


# MIGRATIONS[n] upgrades a database from schema version n to n + 1.
MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [_add_path_metadata]
SCHEMA_VERSION = len(MIGRATIONS)


def path_metadata(path: str) -> tuple[str, str, str]:
    """Return (name, lower-case extension, parent directory) for an indexed path."""
    p = Path(path)
    return p.name, p.suffix.lower(), str(p.parent)


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
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        has_tables = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'documents'"
        ).fetchone()
        with self.connection:
            if not has_tables:
                self.connection.executescript(SCHEMA)
            else:
                for migrate in MIGRATIONS[version:]:
                    migrate(self.connection)
            self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

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
        name, extension, directory = path_metadata(path)
        now = time.time()
        if existing is None:
            cursor = self.connection.execute(
                "INSERT INTO documents (path, name, extension, directory, mtime, size, indexed_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (path, name, extension, directory, mtime, size, now),
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
