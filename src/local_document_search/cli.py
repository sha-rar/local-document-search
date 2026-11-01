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
