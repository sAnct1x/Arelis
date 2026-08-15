"""Smoke: latency suite runs offline with --mock."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_bench_latency_mock(tmp_path: Path) -> None:
    out = tmp_path / "latency_bench.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "bench_latency.py"),
            "--mock",
            "--out",
            str(out),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert out.is_file()
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["mock"] is True
    assert report["engine"]
    assert "cache" in report
    assert report["cache"].get("turn1_was_full_prefill") is True
    assert (report["cache"].get("prefix_chars") or 0) > 5000
    assert "arelis" in report
    assert "tool_open_with_history" in report["arelis"]
    assert "evaluation" in report
    assert "gates" in report["evaluation"]
    for key in ("A", "B", "C", "C_hist", "D", "E", "F"):
        assert key in report["evaluation"]["gates"]
    # Mock must show a real cache differential, not a null "already fast" pass.
    assert report["evaluation"]["gates"]["D"].get("hard_pass") is True
    assert report["evaluation"]["gates"]["C_hist"].get("pass") is True
    assert report["evaluation"]["gates"]["F"].get("pass") is True
    assert report.get("history_growth", {}).get("points")
