"""Command-line interface for indexing folders and searching their contents."""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from .indexer import index_folder
from .search import SearchFilters, search
from .storage import IndexStore, default_db_path


def parse_date(value: str) -> float:
    """Parse YYYY-MM-DD as a timestamp for local midnight at the start of that day."""
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date '{value}', expected YYYY-MM-DD") from None
    return datetime(day.year, day.month, day.day).timestamp()


def parse_extensions(value: str) -> list[str]:
    return [part for part in value.split(",") if part.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docsearch", description="Index and search documents locally."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help=f"Index database file (default: {default_db_path()})",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    index_command = commands.add_parser("index", help="Index documents in a folder")
    index_command.add_argument("folder", type=Path, help="Folder to index")

    search_command = commands.add_parser("search", help="Search indexed document contents")
    search_command.add_argument("query", help='Words to find; use "quotes" for a phrase')
    search_command.add_argument(
        "-n", "--limit", type=int, default=20, help="Maximum results (default: 20)"
    )
    search_command.add_argument(
        "-t",
        "--type",
        dest="types",
        type=parse_extensions,
        action="extend",
        default=[],
        metavar="EXT",
        help="Only these file types, e.g. pdf or pdf,docx (repeatable)",
    )
    search_command.add_argument(
        "--in", dest="folder", type=Path, metavar="FOLDER", help="Only files under this folder"
    )
    search_command.add_argument(
        "--after", type=parse_date, metavar="DATE", help="Only files modified on or after YYYY-MM-DD"
    )
    search_command.add_argument(
        "--before", type=parse_date, metavar="DATE", help="Only files modified before YYYY-MM-DD"
    )
    return parser


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def run_index(db_path: Path, folder: Path) -> int:
    if not folder.is_dir():
        print(f"error: not a directory: {folder}", file=sys.stderr)
        return 1
    with IndexStore(db_path) as store:
        report = index_folder(store, folder)
        total = store.document_count()

    print(
        f"Indexed {folder.resolve()}: {report.added} added, {report.updated} updated, "
        f"{report.unchanged} unchanged, {report.removed} removed, "
        f"{report.unsupported} unsupported, {len(report.failed)} failed."
    )
    for path, reason in report.failed:
        print(f"  failed: {path}: {reason}", file=sys.stderr)
    print(f"{total} documents in index ({db_path}).")
    return 0


def run_search(db_path: Path, query: str, limit: int, filters: SearchFilters) -> int:
    if not db_path.exists():
        print(f"error: no index at {db_path}; run 'docsearch index <folder>' first", file=sys.stderr)
        return 1
    with IndexStore(db_path) as store:
        hits = search(store, query, limit, filters)

    if not hits:
        print("No matches.")
        return 0
    for hit in hits:
        modified = datetime.fromtimestamp(hit.mtime).strftime("%Y-%m-%d %H:%M")
        print(f"{hit.path}  ({format_size(hit.size)}, modified {modified})")
        print(f"    {' '.join(hit.snippet.split())}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = args.db or default_db_path()
    if args.command == "index":
        return run_index(db_path, args.folder)
    filters = SearchFilters(
        extensions=tuple(args.types),
        folder=args.folder,
        modified_after=args.after,
        modified_before=args.before,
    )
    return run_search(db_path, args.query, args.limit, filters)
