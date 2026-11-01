"""Summarise a gpuprof_atria.ps1 run: GPU ms and frame interval per configuration and phase.

Reads, from the run folder: phases.csv (config,phase,start_ms,end_ms), frames_<config>.csv
(ARELIS_GPU_PROFILE_LOG lines: t_epoch_ms,gpu_ms,interval_ms) and gpu_util.csv
(t_epoch_ms,llama_util,app_util, one sample a second). Writes summary.csv beside them.

    python tools/gpuprof_summary.py <run folder>
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path


def pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, round(q * (len(s) - 1)))]


def fmt(v: float | None) -> str:
    return "" if v is None else f"{v:.2f}"


def summarise(run: Path) -> list[dict[str, str]]:
    util = []
    if (run / "gpu_util.csv").exists():
        with open(run / "gpu_util.csv", newline="") as f:
            util = [
                (float(r["t_epoch_ms"]), float(r["llama_util"] or 0), float(r["app_util"] or 0))
                for r in csv.DictReader(f)
            ]
    rows = []
    with open(run / "phases.csv", newline="") as f:
        phases = list(csv.DictReader(f))
    for ph in phases:
        a, b = float(ph["start_ms"]), float(ph["end_ms"])
        frames_csv = run / f"frames_{ph['config']}.csv"
        frames = []
        if frames_csv.exists():
            with open(frames_csv, newline="") as f:
                frames = [r for r in csv.DictReader(f) if a <= float(r["t_epoch_ms"]) < b]
        gpu = [float(r["gpu_ms"]) for r in frames if float(r["gpu_ms"]) > 0]
        gaps = [float(r["interval_ms"]) for r in frames if float(r["interval_ms"]) > 0]
        u = [x for x in util if a <= x[0] < b]
        rows.append(
            {
                "config": ph["config"],
                "phase": ph["phase"],
                "seconds": f"{(b - a) / 1000:.1f}",
                "frames": str(len(frames)),
                "fps": f"{len(frames) * 1000 / (b - a):.1f}" if b > a else "",
                "gpu_ms_p50": fmt(pct(gpu, 0.5)),
                "gpu_ms_p95": fmt(pct(gpu, 0.95)),
                "interval_ms_p50": fmt(pct(gaps, 0.5)),
                "interval_ms_p95": fmt(pct(gaps, 0.95)),
                "share_over_33ms": f"{sum(g > 33 for g in gaps) / len(gaps):.3f}" if gaps else "",
                "llama_util_mean": fmt(sum(x[1] for x in u) / len(u)) if u else "",
                "app_util_mean": fmt(sum(x[2] for x in u) / len(u)) if u else "",
            }
        )
    return rows


def main(argv: list[str]) -> int:
    run = Path(argv[1])
    rows = summarise(run)
    with open(run / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["config"])
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(",".join(r.values()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
