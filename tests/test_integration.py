"""End-to-end tests: index, query, update and remove documents through the CLI."""

import os

import pytest
from helpers import write_docx, write_pdf
from local_document_search.cli import main


@pytest.fixture
def library(tmp_path):
    """A small mixed-format document folder."""
    root = tmp_path / "library"
    (root / "reports").mkdir(parents=True)
    (root / "notes").mkdir()
    (root / "notes" / "meeting.txt").write_text("Agenda: hiring plan and roadmap", encoding="utf-8")
    (root / "notes" / "ideas.md").write_text("# Ideas\nOffline sync prototype", encoding="utf-8")
    write_pdf(root / "reports" / "annual.pdf", ["Annual revenue grew", "Outlook for expansion"])
    write_docx(root / "reports" / "budget.docx", ["Marketing budget proposal"])
    (root / "photo.jpg").write_bytes(b"\xff\xd8\xff")
    return root


class Cli:
    def __init__(self, db, capsys):
        self.db = db
        self.capsys = capsys

    def run(self, *args):
        self.capsys.readouterr()
        code = main(["--db", str(self.db), *args])
        captured = self.capsys.readouterr()
        return code, captured.out, captured.err

    def index(self, folder):
        code, out, err = self.run("index", str(folder))
        assert code == 0, err
        return out

    def found(self, query, *options):
        """Return the file names listed by a search, in ranked order."""
        code, out, err = self.run("search", query, *options)
        assert code == 0, err
        return [
            os.path.basename(line.split("  (")[0])
            for line in out.splitlines()
            if line and not line.startswith(" ") and line != "No matches."
        ]


@pytest.fixture
def cli(tmp_path, capsys):
    return Cli(tmp_path / "index.db", capsys)


def test_index_and_search_every_format(cli, library):
    out = cli.index(library)
    assert "4 added" in out
    assert "1 unsupported" in out

    assert cli.found("hiring") == ["meeting.txt"]
    assert cli.found("prototype") == ["ideas.md"]
    assert cli.found('"revenue grew"') == ["annual.pdf"]
    assert cli.found("expansion") == ["annual.pdf"]
    assert cli.found("marketing budget") == ["budget.docx"]


def test_filters_across_formats(cli, library):
    (library / "notes" / "budget-notes.txt").write_text("budget review", encoding="utf-8")
    cli.index(library)

    assert sorted(cli.found("budget")) == ["budget-notes.txt", "budget.docx"]
    assert cli.found("budget", "--type", "docx") == ["budget.docx"]
    assert cli.found("budget", "--in", str(library / "notes")) == ["budget-notes.txt"]
    assert cli.found("budget", "--after", "2999-01-01") == []


def test_reindex_reflects_edits(cli, library):
    cli.index(library)
    meeting = library / "notes" / "meeting.txt"
    budget = library / "reports" / "budget.docx"
    meeting.write_text("Agenda: quarterly offsite", encoding="utf-8")
    write_docx(budget, ["Engineering budget proposal"])
    # Ensure the scan sees a new mtime even on coarse filesystem clocks.
    for path in (meeting, budget):
        stat = path.stat()
        os.utime(path, (stat.st_atime, stat.st_mtime + 10))

    out = cli.index(library)
    assert "2 updated" in out
    assert cli.found("offsite") == ["meeting.txt"]
    assert cli.found("hiring") == []
    assert cli.found("engineering") == ["budget.docx"]
    assert cli.found("marketing") == []


def test_reindex_reflects_moves_and_deletions(cli, library):
    cli.index(library)
    (library / "reports" / "annual.pdf").rename(library / "notes" / "annual-2024.pdf")
    (library / "notes" / "ideas.md").unlink()

    out = cli.index(library)
    assert "1 moved" in out
    assert "1 removed" in out
    assert cli.found("revenue") == ["annual-2024.pdf"]
    assert cli.found("revenue", "--in", str(library / "reports")) == []
    assert cli.found("prototype") == []


def test_prune_clears_documents_from_unindexed_folders(cli, tmp_path, library):
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "old.txt").write_text("legacy contract", encoding="utf-8")
    cli.index(archive)
    cli.index(library)
    (archive / "old.txt").unlink()

    assert cli.found("legacy") == ["old.txt"]
    code, out, _err = cli.run("prune")
    assert code == 0
    assert "Removed 1 missing documents; 4 remain" in out
    assert cli.found("legacy") == []
    assert cli.found("hiring") == ["meeting.txt"]
