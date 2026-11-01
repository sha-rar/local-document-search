"""Smoke test: the benchmark script still runs end to end on a tiny dataset."""

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "benchmarks" / "run_benchmarks.py"


def load_benchmarks():
    spec = importlib.util.spec_from_file_location("run_benchmarks", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_size_reports_measurements(tmp_path):
    bench = load_benchmarks()
    result = bench.run_size(60, tmp_path)
    assert result["indexed"] == 60 and result["failed"] == 0
    assert result["changed_updated"] == result["changed_files"] >= 1
    assert set(result["search"]) == set(bench.QUERIES)
    assert result["peak_memory_mb"] > 0

    # The dataset is reused rather than regenerated.
    marker = tmp_path / "docs-60" / ".complete"
    before = marker.stat().st_mtime_ns
    bench.generate_dataset(tmp_path / "docs-60", 60)
    assert marker.stat().st_mtime_ns == before


def test_main_runs_each_size_in_a_subprocess(tmp_path, capsys):
    bench = load_benchmarks()
    out_file = tmp_path / "results.json"
    code = bench.main(["--sizes", "20", "--data-dir", str(tmp_path), "--json", str(out_file)])
    assert code == 0
    assert "First index" in capsys.readouterr().out
    assert json.loads(out_file.read_text(encoding="utf-8"))[0]["files"] == 20
