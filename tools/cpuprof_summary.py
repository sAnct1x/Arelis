"""Summarise a cpuprof_atria.ps1 run: GUI wakeup lateness, frame pacing and py-spy hot stacks.

Reads, from the run folder: phases.csv (config,phase,start_ms,end_ms), wake_<config>.csv
(ARELIS_WAKE_LOG), frames_<config>.csv (ARELIS_FRAMETIME_LOG: t_epoch_ms,frame_ms) and
pyspy_<config>.txt (py-spy --format raw: collapsed stacks, one per line, with thread names).
Writes summary.csv and pyspy_top.txt beside them.

The "tick" columns test the 15.6 ms timer theory: the share of frame intervals within 2 ms
of a multiple of 15.625 ms (pure chance for intervals spread evenly is about 26%).

    python tools/cpuprof_summary.py <run folder>
"""

from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

TICK = 15.625


def pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, round(q * (len(s) - 1)))]


def fmt(v: float | None) -> str:
    return "" if v is None else f"{v:.2f}"


def share(xs: list[float], pred) -> str:
    return f"{sum(1 for x in xs if pred(x)) / len(xs):.3f}" if xs else ""


def on_tick(ms: float) -> bool:
    k = round(ms / TICK)
    return k >= 1 and abs(ms - k * TICK) <= 2.0


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def summarise(run: Path) -> list[dict[str, str]]:
    out = []
    for ph in _rows(run / "phases.csv"):
        a, b, cfg = float(ph["start_ms"]), float(ph["end_ms"]), ph["config"]
        late = [
            float(r["late_ms"])
            for r in _rows(run / f"wake_{cfg}.csv")
            if a <= float(r["t_epoch_ms"]) < b
        ]
        gaps = [
            float(r["frame_ms"])
            for r in _rows(run / f"frames_{cfg}.csv")
            if a <= float(r["t_epoch_ms"]) < b
        ]
        out.append(
            {
                "config": cfg,
                "phase": ph["phase"],
                "wake_n": str(len(late)),
                "wake_late_p50": fmt(pct(late, 0.5)),
                "wake_late_p95": fmt(pct(late, 0.95)),
                "wake_late_p99": fmt(pct(late, 0.99)),
                "wake_late_max": fmt(max(late) if late else None),
                "wake_over_2ms": share(late, lambda x: x > 2),
                "wake_over_10ms": share(late, lambda x: x > 10),
                "frames": str(len(gaps)),
                "frame_p50": fmt(pct(gaps, 0.5)),
                "frame_p95": fmt(pct(gaps, 0.95)),
                "frame_over_33ms": share(gaps, lambda x: x > 33),
                "frame_on_15.6_tick": share(gaps, on_tick),
            }
        )
    return out


def pyspy_top(path: Path, n: int = 25) -> str:
    """Per thread: samples, idle share, and the hottest leaf frames."""
    if not path.exists():
        return f"{path.name}: missing\n"
    leaf: dict[str, Counter] = defaultdict(Counter)
    total: Counter = Counter()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stack, _, count = line.rpartition(" ")
        if not stack or not count.isdigit():
            continue
        frames = stack.split(";")
        thread = frames[0]
        total[thread] += int(count)
        leaf[thread][frames[-1]] += int(count)
    lines = [f"== {path.name}"]
    for thread, t in total.most_common():
        lines.append(f"-- {thread}: {t} samples")
        for fr, c in leaf[thread].most_common(n):
            lines.append(f"   {100 * c / t:5.1f}%  {fr}")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    run = Path(argv[1])
    rows = summarise(run)
    with open(run / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["config"])
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(",".join(r.values()))
    top = "".join(pyspy_top(p) for p in sorted(run.glob("pyspy_*.txt")))
    (run / "pyspy_top.txt").write_text(top, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
