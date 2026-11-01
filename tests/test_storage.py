import sqlite3

from local_document_search.storage import SCHEMA_VERSION, IndexStore

# Layout written by the first release, before metadata columns existed.
V0_SCHEMA = """
CREATE TABLE documents (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    indexed_at REAL NOT NULL
);
CREATE VIRTUAL TABLE documents_fts USING fts5(
    name, content, tokenize = 'unicode61 remove_diacritics 2'
);
"""


def metadata(store, path):
    return tuple(
        store.connection.execute(
            "SELECT name, extension, directory, size, mtime FROM documents WHERE path = ?",
            (path,),
        ).fetchone()
    )


def test_stores_path_metadata(tmp_path):
    path = str(tmp_path / "Reports" / "Summary.PDF")
    with IndexStore(tmp_path / "index.db") as store:
        store.upsert_document(path, 1700000000.0, 2048, "text")
        assert metadata(store, path) == (
            "Summary.PDF",
            ".pdf",
            str(tmp_path / "Reports"),
            2048,
            1700000000.0,
        )


def test_new_database_is_at_current_schema_version(tmp_path):
    with IndexStore(tmp_path / "index.db") as store:
        version = store.connection.execute("PRAGMA user_version").fetchone()[0]
    assert version == SCHEMA_VERSION


def test_migrates_v0_database(tmp_path):
    db = tmp_path / "index.db"
    path = str(tmp_path / "notes" / "todo.md")
    connection = sqlite3.connect(db)
    connection.executescript(V0_SCHEMA)
    connection.execute(
        "INSERT INTO documents (id, path, mtime, size, indexed_at) VALUES (1, ?, 5.0, 10, 6.0)",
        (path,),
    )
    connection.execute("INSERT INTO documents_fts (rowid, name, content) VALUES (1, 'todo.md', 'x')")
    connection.commit()
    connection.close()

    with IndexStore(db) as store:
        assert metadata(store, path) == ("todo.md", ".md", str(tmp_path / "notes"), 10, 5.0)
        assert store.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
