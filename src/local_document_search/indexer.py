"""Discover files and maintain an incremental index."""

import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .extractors import ExtractionError, extract_text, is_supported
from .storage import IndexStore

COMMIT_EVERY = 200


@dataclass
class IndexReport:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    unsupported: int = 0
    failed: list[tuple[Path, str]] = field(default_factory=list)


def iter_files(root: Path, errors: list[tuple[Path, str]] | None = None) -> Iterator[Path]:
    """Recursively yield regular files under ``root``; unreadable directories go to ``errors``."""

    def on_error(exc: OSError) -> None:
        if errors is not None:
            errors.append((Path(exc.filename), exc.strerror or str(exc)))

    for dirpath, _dirnames, filenames in os.walk(root, onerror=on_error):
        for filename in filenames:
            yield Path(dirpath) / filename


def index_folder(
    store: IndexStore,
    root: Path,
    progress: Callable[[Path], None] | None = None,
) -> IndexReport:
    """Index supported files under ``root``, skipping unchanged files and removing deleted ones."""
    root = Path(root).resolve()
    report = IndexReport()
    seen: set[str] = set()
    pending = 0

    for path in iter_files(root, report.failed):
        if not is_supported(path):
            report.unsupported += 1
            continue
        if progress:
            progress(path)
        key = str(path)
        seen.add(key)
        try:
            stat = path.stat()
        except OSError as exc:
            report.failed.append((path, exc.strerror or str(exc)))
            continue

        existing = store.get_document(key)
        if existing and existing.mtime == stat.st_mtime and existing.size == stat.st_size:
            report.unchanged += 1
            continue
        try:
            text = extract_text(path)
        except ExtractionError as exc:
            report.failed.append((path, str(exc)))
            continue

        store.upsert_document(key, stat.st_mtime, stat.st_size, text)
        if existing:
            report.updated += 1
        else:
            report.added += 1
        pending += 1
        if pending >= COMMIT_EVERY:
            store.commit()
            pending = 0

    for key in store.all_paths():
        if key not in seen and Path(key).is_relative_to(root):
            store.delete_document(key)
            report.removed += 1

    store.commit()
    return report
