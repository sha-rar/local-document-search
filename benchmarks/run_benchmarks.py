"""Measure indexing speed, search latency and memory on generated document sets.

Usage:
    python benchmarks/run_benchmarks.py                     # 1,000 / 10,000 / 50,000 files
    python benchmarks/run_benchmarks.py --sizes 1000 5000   # custom sizes
    python benchmarks/run_benchmarks.py --json results.json

Datasets are generated once into ``--data-dir`` (default: a folder in the system temp
directory) and reused. Each size runs in its own process so peak memory isn't shared.
The sizes are test inputs, not claims about the application's capacity.
"""

import argparse
import json
import os
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Reuse the test suite's PDF/DOCX builders rather than committing binary fixtures.
sys.path.insert(0, str(ROOT / "tests"))

from helpers import write_docx, write_pdf  # noqa: E402

from local_document_search.indexer import index_folder  # noqa: E402
from local_document_search.search import SearchFilters, search  # noqa: E402
from local_document_search.storage import IndexStore  # noqa: E402

DEFAULT_SIZES = (1_000, 10_000, 50_000)
DATASET_VERSION = 1
SEARCH_REPEATS = 20

# Share of files generated as PDF and DOCX; the rest are .txt/.md. Office formats are
# slow to generate, so they are a small but present fraction.
PDF_SHARE = 0.01
DOCX_SHARE = 0.01

VOCABULARY = (
    "budget report travel invoice meeting plan revenue quarterly review project design "
    "data search index local file contract policy schedule summary research analysis "
    "customer supplier forecast audit lecture notes thesis chapter draft final proposal"
).split()
RARE_WORD = "zephyrine"  # appears in about 0.1% of documents

QUERIES = {
    "common word": ("report", None),
    "rare word": (RARE_WORD, None),
    "two words": ("budget forecast", None),
    "phrase": ('"quarterly review"', None),
    "filtered": ("invoice", SearchFilters(extensions=(".md",))),
}


def generate_dataset(folder: Path, size: int) -> None:
    """Write ``size`` documents into nested folders, deterministically."""
    marker = folder / ".complete"
    if marker.exists() and marker.read_text() == f"{DATASET_VERSION}:{size}":
        return
    shutil.rmtree(folder, ignore_errors=True)
    rng = random.Random(size)
    pdf_count = int(size * PDF_SHARE)
    docx_count = int(size * DOCX_SHARE)
    for i in range(size):
        directory = folder / f"area{i % 20:02d}" / f"topic{i % 13:02d}" / f"batch{i % 5}"
        directory.mkdir(parents=True, exist_ok=True)
        words = [rng.choice(VOCABULARY) for _ in range(rng.randint(80, 600))]
        if i % 1000 == 7:
            words[rng.randrange(len(words))] = RARE_WORD
        text = " ".join(words)
        if i < pdf_count:
            # One line per page keeps generated PDFs simple.
            pages = [text[j : j + 90] for j in range(0, 450, 90)]
            write_pdf(directory / f"doc{i}.pdf", pages)
        elif i < pdf_count + docx_count:
            paragraphs = [text[j : j + 400] for j in range(0, len(text), 400)]
            write_docx(directory / f"doc{i}.docx", paragraphs)
        else:
            extension = ".md" if i % 3 == 0 else ".txt"
            (directory / f"doc{i}{extension}").write_text(text, encoding="utf-8")
    marker.write_text(f"{DATASET_VERSION}:{size}")


def warm_up(folder: Path) -> None:
    """Read every file once so OS caching and antivirus scanning don't skew the timings."""
    for path in folder.rglob("doc*"):
        path.read_bytes()


def modify_some(folder: Path, share: float, seed: int) -> int:
    """Append text to a share of the .txt files; return how many changed.

    This edits the cached dataset, so repeated runs grow those files slightly.
    """
    files = sorted(folder.rglob("*.txt"))
    chosen = random.Random(seed).sample(files, max(1, int(len(files) * share)))
    for path in chosen:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(" edited")
        stat = path.stat()
        os.utime(path, (stat.st_atime, stat.st_mtime + 1))
    return len(chosen)


def peak_memory_bytes() -> int:
    """Peak resident memory of this process."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        psapi = ctypes.WinDLL("psapi")
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        )
        return counters.PeakWorkingSetSize
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024  # Linux reports KiB


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))]


def run_size(size: int, data_dir: Path, cold: bool = False) -> dict:
    """Benchmark one dataset size in this process and return the measurements."""
    dataset = data_dir / f"docs-{size}"
    started = time.perf_counter()
    generate_dataset(dataset, size)
    generation_seconds = time.perf_counter() - started
    if not cold:
        warm_up(dataset)

    db_path = data_dir / f"index-{size}.db"
    for suffix in ("", "-wal", "-shm"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)

    results: dict = {"files": size, "generation_seconds": round(generation_seconds, 2)}
    with IndexStore(db_path) as store:
        started = time.perf_counter()
        report = index_folder(store, dataset)
        first = time.perf_counter() - started

        started = time.perf_counter()
        index_folder(store, dataset)
        unchanged = time.perf_counter() - started

        changed = modify_some(dataset, 0.01, seed=size)
        started = time.perf_counter()
        update_report = index_folder(store, dataset)
        incremental = time.perf_counter() - started

        latencies = {}
        for label, (query, filters) in QUERIES.items():
            search(store, query, 20, filters)  # warm the page cache
            samples = []
            for _ in range(SEARCH_REPEATS):
                started = time.perf_counter()
                search(store, query, 20, filters)
                samples.append((time.perf_counter() - started) * 1000)
            latencies[label] = {
                "median_ms": round(statistics.median(samples), 2),
                "p95_ms": round(percentile(samples, 0.95), 2),
            }

    results.update(
        {
            "indexed": report.added,
            "failed": len(report.failed),
            "first_index_seconds": round(first, 2),
            "files_per_second": round(report.added / first) if first else None,
            "unchanged_reindex_seconds": round(unchanged, 2),
            "changed_files": changed,
            "changed_updated": update_report.updated,
            "incremental_reindex_seconds": round(incremental, 2),
            "search": latencies,
            "index_size_mb": round(db_path.stat().st_size / 1024**2, 1),
            "peak_memory_mb": round(peak_memory_bytes() / 1024**2, 1),
        }
    )
    return results


def print_table(all_results: list[dict]) -> None:
    rows = [
        ("Files", lambda r: f"{r['files']:,}"),
        (
            "First index",
            lambda r: f"{r['first_index_seconds']:.2f} s ({r['files_per_second']:,}/s)",
        ),
        ("Re-index, nothing changed", lambda r: f"{r['unchanged_reindex_seconds']:.2f} s"),
        (
            "Re-index, 1% of files changed",
            lambda r: f"{r['incremental_reindex_seconds']:.2f} s ({r['changed_updated']} updated)",
        ),
    ]
    for label in QUERIES:
        rows.append(
            (
                f"Search: {label} (median / p95)",
                lambda r, label=label: (
                    f"{r['search'][label]['median_ms']:.1f} / {r['search'][label]['p95_ms']:.1f} ms"
                ),
            )
        )
    rows += [
        ("Index size", lambda r: f"{r['index_size_mb']:.1f} MB"),
        ("Peak memory", lambda r: f"{r['peak_memory_mb']:.0f} MB"),
        ("Extraction failures", lambda r: str(r["failed"])),
    ]
    label_width = max(len(label) for label, _ in rows)
    column_width = max(18, *(len(fmt(r)) for _, fmt in rows for r in all_results))
    for label, fmt in rows:
        cells = "".join(f"{fmt(r):>{column_width + 2}}" for r in all_results)
        print(f"{label:<{label_width}}{cells}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sizes", type=int, nargs="+", default=list(DEFAULT_SIZES))
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(tempfile.gettempdir()) / "filelens-benchmarks",
        help="Where generated datasets and indexes are kept (default: system temp)",
    )
    parser.add_argument(
        "--cold",
        action="store_true",
        help="Skip the warm-up read, so timings include OS caching and antivirus scans",
    )
    parser.add_argument("--json", type=Path, help="Also write the results to this file")
    parser.add_argument("--child", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    args.data_dir.mkdir(parents=True, exist_ok=True)

    if args.child:
        print(json.dumps(run_size(args.child, args.data_dir, args.cold)))
        return 0

    all_results = []
    for size in args.sizes:
        print(f"Benchmarking {size:,} files…", file=sys.stderr, flush=True)
        command = [sys.executable, __file__, "--child", str(size)]
        command += ["--data-dir", str(args.data_dir)]
        if args.cold:
            command.append("--cold")
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode != 0:
            print(completed.stderr, file=sys.stderr)
            return completed.returncode
        all_results.append(json.loads(completed.stdout.strip().splitlines()[-1]))

    print_table(all_results)
    if args.json:
        args.json.write_text(json.dumps(all_results, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
