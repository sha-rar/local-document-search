# PowerShell 5.1+ or 7+, run from the directory that should contain the repository.
$ErrorActionPreference = "Stop"
$root = Join-Path (Get-Location) "local-document-search"
if (Test-Path $root) { throw "Folder already exists: $root" }
New-Item -ItemType Directory -Path $root | Out-Null

$path = Join-Path $root '.gitignore'
$parent = Split-Path -Parent $path
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$content = @'
.venv/
__pycache__/
.pytest_cache/
*.py[cod]
*.egg-info/
build/
dist/
*.db
*.sqlite
*.sqlite3
.env
'@
[System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))

$path = Join-Path $root 'README.md'
$parent = Split-Path -Parent $path
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$content = @'
# FileLens — Local Document Search

Search the contents of documents on your computer without opening them one at a time.

**Status:** Starter scaffold. The CLI entry point exists, but indexing and searching are not implemented yet.

## The finished product

FileLens will be a local-first desktop application that lets someone select folders, index thousands of documents, and find information by searching the *contents* of those files rather than just their filenames.

A user should be able to:

- Select one or more folders to index and exclude irrelevant or sensitive directories.
- Index `.txt`, `.md`, `.pdf`, and `.docx` files, with an extensible extractor system for additional formats.
- Search words and phrases, find results ranked by relevance, and narrow results by file type, folder, or modification date.
- See matching snippets, filename, original path, and last-modified time; open the original file directly.
- Update the index incrementally when documents are created, changed, moved, or deleted.
- Review indexing progress, failed files, and index statistics without losing the rest of a scan.
- Keep the index and document contents on the user's machine; no account or cloud service required.

A desktop UI should make indexing and searching straightforward, even for someone who doesn't use the command line.

## Intended technology

- **Python:** indexing pipeline and application logic.
- **SQLite FTS5:** persistent full-text index and relevance-ranked search.
- **`pathlib` and `hashlib`:** filesystem traversal and change detection.
- **`pypdf` and `python-docx`:** PDF and Word text extraction (added when those milestones begin).
- **PySide6:** eventual desktop UI.
- **pytest:** automated testing.

Start with plain-text and Markdown files. Add PDF and Word support once indexing and searching work end-to-end.

## Initial repository structure

```text
local-document-search/
├── src/local_document_search/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py            # Command-line entry point
│   ├── extractors.py     # Format-specific text extraction
│   ├── indexer.py        # Folder scans and incremental updates
│   ├── storage.py        # SQLite schema and persistence
│   └── search.py         # Querying and ranking
├── tests/
│   └── test_cli.py
├── docs/
│   └── architecture.md
├── pyproject.toml
├── .gitignore
└── README.md
```

The structure is provisional. Add a `gui/` package when the core functionality is dependable.

## Roadmap

1. **Working CLI and file discovery:** Accept a directory, recursively enumerate supported files, and report skipped or unreadable files.
2. **Text extraction:** Read `.txt` and `.md` files, with predictable Unicode and decoding behaviour.
3. **Index and query:** Create an SQLite FTS5 table; store paths, metadata, and extracted text; implement keyword and phrase searches with result snippets.
4. **Incremental indexing:** Detect changed and removed files; avoid unnecessary re-extraction and keep the index consistent.
5. **More formats:** Add PDF and DOCX extraction, with tests for empty, malformed, and encrypted documents.
6. **Desktop application:** Build a simple PySide6 interface for selecting folders, seeing progress, and browsing results.
7. **Reliability and packaging:** Add larger-directory benchmarks, cancellation, logging, installation/packaging, and documentation.

## Set-up (Windows PowerShell)

Requires Python 3.11+.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
python -m local_document_search --help
pytest
```

The `index` and `search` commands currently report that they have not been implemented. The README describes the intended product, **not** already-shipped features.

## Definition of done

A fresh installation can index a real folder containing thousands of mixed documents, accurately find known text across supported formats, update changed files without a full rebuild, and open search results reliably. Core extraction, indexing, and query behaviour have automated tests.

## Out of scope for the initial release

Cloud sync, accounts, AI-powered semantic search, and OCR for scanned PDFs. These can be evaluated after basic full-text search works well.
'@
[System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))

$path = Join-Path $root 'docs\architecture.md'
$parent = Split-Path -Parent $path
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$content = @'
# Architecture notes

The first version will be a single local process:

1. `cli.py` accepts an indexing directory or search query.
2. `indexer.py` enumerates files and delegates extraction to `extractors.py`.
3. `storage.py` persists metadata and extracted text using SQLite FTS5.
4. `search.py` executes text queries and returns ranked hits and snippets.

After the CLI works, add a PySide6 UI that calls the same indexing/search services.
Do not run indexing work on the GUI event loop. Avoid committing indexed user data.
'@
[System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))

$path = Join-Path $root 'pyproject.toml'
$parent = Split-Path -Parent $path
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$content = @'
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "local-document-search"
version = "0.1.0"
description = "Local-first document indexing and full-text search"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
docsearch = "local_document_search.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
'@
[System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))

$path = Join-Path $root 'src\local_document_search\__init__.py'
$parent = Split-Path -Parent $path
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$content = @'
"""FileLens local document search package."""
'@
[System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))

$path = Join-Path $root 'src\local_document_search\__main__.py'
$parent = Split-Path -Parent $path
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$content = @'
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
'@
[System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))

$path = Join-Path $root 'src\local_document_search\cli.py'
$parent = Split-Path -Parent $path
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$content = @'
"""Initial command-line interface; functionality will be implemented incrementally."""

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="docsearch", description="Index and search documents locally."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    index_command = commands.add_parser("index", help="Index documents in a folder")
    index_command.add_argument("folder", help="Folder to index")

    search_command = commands.add_parser("search", help="Search indexed document contents")
    search_command.add_argument("query", help="Text or phrase to find")

    args = parser.parse_args(argv)
    print(f"TODO: '{args.command}' is not implemented yet.")
    return 2
'@
[System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))

$path = Join-Path $root 'src\local_document_search\extractors.py'
$parent = Split-Path -Parent $path
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$content = @'
"""Extract text from supported document formats.

Not implemented yet.
"""
'@
[System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))

$path = Join-Path $root 'src\local_document_search\indexer.py'
$parent = Split-Path -Parent $path
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$content = @'
"""Discover files and maintain an incremental index.

Not implemented yet.
"""
'@
[System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))

$path = Join-Path $root 'src\local_document_search\search.py'
$parent = Split-Path -Parent $path
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$content = @'
"""Run indexed full-text queries and return ranked results.

Not implemented yet.
"""
'@
[System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))

$path = Join-Path $root 'src\local_document_search\storage.py'
$parent = Split-Path -Parent $path
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$content = @'
"""Persist metadata and full-text content in SQLite FTS5.

Not implemented yet.
"""
'@
[System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))

$path = Join-Path $root 'tests\test_cli.py'
$parent = Split-Path -Parent $path
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$content = @'
import pytest
from local_document_search.cli import main


def test_help_exits_successfully(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "Index and search documents locally" in capsys.readouterr().out


def test_index_reports_not_implemented(capsys):
    assert main(["index", "."]) == 2
    assert "not implemented" in capsys.readouterr().out
'@
[System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))

if (Get-Command git -ErrorAction SilentlyContinue) { git -C $root init }
Write-Host "Created $root"
Write-Host "Read its README.md for setup and milestones."
