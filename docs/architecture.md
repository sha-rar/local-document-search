# Architecture notes

The first version will be a single local process:

1. `cli.py` accepts an indexing directory or search query.
2. `indexer.py` enumerates files and delegates extraction to `extractors.py`.
3. `storage.py` persists metadata and extracted text using SQLite FTS5.
4. `search.py` executes text queries and returns ranked hits and snippets.

After the CLI works, add a PySide6 UI that calls the same indexing/search services.
Do not run indexing work on the GUI event loop. Avoid committing indexed user data.
