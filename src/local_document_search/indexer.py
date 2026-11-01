"""Discover files and maintain an incremental index."""

import hashlib
import os
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .extractors import ExtractionError, extract_text, is_supported
from .storage import DocumentRecord, IndexStore

COMMIT_EVERY = 200
HASH_CHUNK_SIZE = 1024 * 1024


@dataclass
class IndexReport:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    moved: int = 0
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


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def find_moved_source(store: IndexStore, size: int, content_hash: str) -> DocumentRecord | None:
    """Return an indexed document with identical content whose file no longer exists."""
    for candidate in store.find_by_content(size, content_hash):
        if not Path(candidate.path).exists():
            return candidate
    return None


def index_folder(
    store: IndexStore,
    root: Path,
    progress: Callable[[Path], None] | None = None,
) -> IndexReport:
    """Index supported files under ``root``.

    Unchanged files are skipped, moved or renamed files keep their extracted text, and
    documents under ``root`` that no longer exist are removed.
    """
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
            existing = store.get_document(key)
            stat_unchanged = (
                existing is not None
                and existing.mtime == stat.st_mtime
                and existing.size == stat.st_size
            )
            if stat_unchanged and existing.content_hash is not None:
                report.unchanged += 1
                continue
            digest = file_hash(path)
        except OSError as exc:
            report.failed.append((path, exc.strerror or str(exc)))
            continue

        if existing is not None and (stat_unchanged or existing.content_hash == digest):
            # Same bytes (e.g. only touched, or indexed before hashes were stored).
            store.update_file_state(existing.id, stat.st_mtime, stat.st_size, digest)
            report.unchanged += 1
        elif existing is None and (source := find_moved_source(store, stat.st_size, digest)):
            store.move_document(source.id, key, stat.st_mtime)
            report.moved += 1
        else:
            try:
                text = extract_text(path)
            except ExtractionError as exc:
                report.failed.append((path, str(exc)))
                continue
            store.upsert_document(key, stat.st_mtime, stat.st_size, text, digest)
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


def remove_folder(store: IndexStore, root: Path, keep: Iterable[Path] = ()) -> int:
    """Remove documents under ``root`` unless they are also under a folder in ``keep``."""
    root = Path(root).resolve()
    kept = [Path(folder).resolve() for folder in keep]
    removed = 0
    for key in store.all_paths():
        path = Path(key)
        if path.is_relative_to(root) and not any(path.is_relative_to(k) for k in kept):
            store.delete_document(key)
            removed += 1
    store.commit()
    return removed


def prune_missing(store: IndexStore) -> int:
    """Remove documents whose files no longer exist anywhere; return how many were removed."""
    removed = 0
    for key in store.all_paths():
        if not Path(key).exists():
            store.delete_document(key)
            removed += 1
    store.commit()
    return removed
