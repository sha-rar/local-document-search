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
    indexed_at REAL NOT NULL,
    content_hash TEXT
);
CREATE INDEX documents_extension ON documents (extension);
CREATE INDEX documents_mtime ON documents (mtime);
CREATE INDEX documents_content ON documents (size, content_hash);
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


def _add_content_hash(connection: sqlite3.Connection) -> None:
    # Existing rows keep NULL until the indexer next sees the file.
    connection.execute("ALTER TABLE documents ADD COLUMN content_hash TEXT")
    connection.execute("CREATE INDEX documents_content ON documents (size, content_hash)")


# MIGRATIONS[n] upgrades a database from schema version n to n + 1.
MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [_add_path_metadata, _add_content_hash]
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
    content_hash: str | None


class IndexStore:
    """SQLite-backed document index. Rows in ``documents_fts`` share rowids with ``documents``."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        # WAL lets the GUI read while a background indexer writes.
        self.connection.execute("PRAGMA journal_mode = WAL")
        # With WAL, NORMAL can lose the last commits on power loss but never corrupts the
        # index, and avoids a disk sync per commit.
        self.connection.execute("PRAGMA synchronous = NORMAL")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        has_tables = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'documents'"
        ).fetchone()
        if has_tables and version == SCHEMA_VERSION:
            # Opening an up-to-date index must not write: a write would wait on any
            # connection that is mid-transaction (e.g. a running indexer).
            return
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
            "SELECT id, path, mtime, size, content_hash FROM documents WHERE path = ?", (path,)
        ).fetchone()
        return DocumentRecord(**row) if row else None

    def find_by_content(self, size: int, content_hash: str) -> list[DocumentRecord]:
        rows = self.connection.execute(
            "SELECT id, path, mtime, size, content_hash FROM documents"
            " WHERE size = ? AND content_hash = ?",
            (size, content_hash),
        )
        return [DocumentRecord(**row) for row in rows]

    def upsert_document(
        self, path: str, mtime: float, size: int, text: str, content_hash: str | None = None
    ) -> None:
        existing = self.get_document(path)
        name, extension, directory = path_metadata(path)
        now = time.time()
        if existing is None:
            cursor = self.connection.execute(
                "INSERT INTO documents"
                " (path, name, extension, directory, mtime, size, indexed_at, content_hash)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (path, name, extension, directory, mtime, size, now, content_hash),
            )
            self.connection.execute(
                "INSERT INTO documents_fts (rowid, name, content) VALUES (?, ?, ?)",
                (cursor.lastrowid, name, text),
            )
        else:
            self.connection.execute(
                "UPDATE documents SET mtime = ?, size = ?, indexed_at = ?, content_hash = ?"
                " WHERE id = ?",
                (mtime, size, now, content_hash, existing.id),
            )
            self.connection.execute(
                "UPDATE documents_fts SET name = ?, content = ? WHERE rowid = ?",
                (name, text, existing.id),
            )

    def update_file_state(
        self, document_id: int, mtime: float, size: int, content_hash: str | None
    ) -> None:
        """Record new stat/hash values for a document whose extracted text is still valid."""
        self.connection.execute(
            "UPDATE documents SET mtime = ?, size = ?, content_hash = ? WHERE id = ?",
            (mtime, size, content_hash, document_id),
        )

    def move_document(self, document_id: int, new_path: str, mtime: float) -> None:
        """Point an existing document at a new path, keeping its extracted text."""
        name, extension, directory = path_metadata(new_path)
        self.connection.execute(
            "UPDATE documents SET path = ?, name = ?, extension = ?, directory = ?, mtime = ?,"
            " indexed_at = ? WHERE id = ?",
            (new_path, name, extension, directory, mtime, time.time(), document_id),
        )
        self.connection.execute(
            "UPDATE documents_fts SET name = ? WHERE rowid = ?", (name, document_id)
        )

    def delete_document(self, path: str) -> None:
        existing = self.get_document(path)
        if existing is None:
            return
        self.connection.execute("DELETE FROM documents_fts WHERE rowid = ?", (existing.id,))
        self.connection.execute("DELETE FROM documents WHERE id = ?", (existing.id,))

    def documents_under(self, path: Path) -> dict[str, DocumentRecord]:
        """Indexed documents at ``path`` or inside it as a folder, keyed by path."""
        path_text = str(path)
        prefix = path_text if path_text.endswith(os.sep) else path_text + os.sep
        rows = self.connection.execute(
            "SELECT id, path, mtime, size, content_hash FROM documents"
            " WHERE path = ? OR substr(path, 1, ?) = ?",
            (path_text, len(prefix), prefix),
        )
        return {row["path"]: DocumentRecord(**row) for row in rows}

    def paths_under(self, path: Path) -> list[str]:
        """Indexed paths equal to ``path`` or inside it as a folder."""
        return list(self.documents_under(path))

    def delete_ids(self, document_ids: list[int]) -> None:
        params = [(document_id,) for document_id in document_ids]
        self.connection.executemany("DELETE FROM documents_fts WHERE rowid = ?", params)
        self.connection.executemany("DELETE FROM documents WHERE id = ?", params)

    def all_paths(self) -> list[str]:
        return [row["path"] for row in self.connection.execute("SELECT path FROM documents")]

    def document_count(self) -> int:
        return self.connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
