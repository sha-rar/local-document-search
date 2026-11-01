"""Command-line interface for indexing folders and searching their contents."""

import argparse
import signal
import sys
from datetime import date, datetime
from pathlib import Path

from .formatting import format_size
from .indexer import Exclusions, IndexControl, index_folder, prune_missing
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
    index_command.add_argument(
        "--exclude",
        type=Path,
        action="append",
        default=[],
        metavar="FOLDER",
        help="Skip this folder and everything under it (repeatable)",
    )
    index_command.add_argument(
        "--exclude-name",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Skip files and folders whose name matches, e.g. '~$*' or node_modules (repeatable)",
    )
    index_command.add_argument(
        "--skip-type",
        type=parse_extensions,
        action="extend",
        default=[],
        metavar="EXT",
        help="Skip these file types, e.g. pdf or pdf,docx (repeatable)",
    )

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

    commands.add_parser(
        "prune",
        help="Remove index entries for files that no longer exist",
        description="Remove index entries for files that no longer exist. Files on a "
        "disconnected drive count as missing and are removed too.",
    )
    return parser


def run_index(db_path: Path, folder: Path, exclusions: Exclusions) -> int:
    if not folder.is_dir():
        print(f"error: not a directory: {folder}", file=sys.stderr)
        return 1
    control = IndexControl()

    def on_interrupt(signum, frame):
        if control.cancelled:
            raise KeyboardInterrupt  # second Ctrl+C: stop immediately
        control.cancel()
        print("Stopping after the current file (Ctrl+C again to abort)…", file=sys.stderr)

    previous_handler = signal.signal(signal.SIGINT, on_interrupt)
    try:
        with IndexStore(db_path) as store:
            report = index_folder(store, folder, exclude=exclusions, control=control)
            total = store.document_count()
    finally:
        signal.signal(signal.SIGINT, previous_handler)

    verb = "Cancelled indexing" if report.cancelled else "Indexed"
    print(
        f"{verb} {folder.resolve()}: {report.added} added, {report.updated} updated, "
        f"{report.unchanged} unchanged, {report.moved} moved, {report.removed} removed, "
        f"{report.unsupported} unsupported, {len(report.failed)} failed."
    )
    for path, reason in report.failed:
        print(f"  failed: {path}: {reason}", file=sys.stderr)
    print(f"{total} documents in index ({db_path}).")
    return 130 if report.cancelled else 0  # 130 is the conventional exit code for Ctrl+C


def run_prune(db_path: Path) -> int:
    if not db_path.exists():
        print(f"error: no index at {db_path}", file=sys.stderr)
        return 1
    with IndexStore(db_path) as store:
        removed = prune_missing(store)
        total = store.document_count()
    print(f"Removed {removed} missing documents; {total} remain in index.")
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
        exclusions = Exclusions(
            folders=tuple(args.exclude),
            patterns=tuple(args.exclude_name),
            extensions=tuple(args.skip_type),
        )
        return run_index(db_path, args.folder, exclusions)
    if args.command == "prune":
        return run_prune(db_path)
    filters = SearchFilters(
        extensions=tuple(args.types),
        folder=args.folder,
        modified_after=args.after,
        modified_before=args.before,
    )
    return run_search(db_path, args.query, args.limit, filters)
