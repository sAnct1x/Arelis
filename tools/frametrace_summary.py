"""Summarise ARELIS_FRAME_TRACE captures: python tools/frametrace_summary.py <out_dir>.

Reads trace_<phase>.csv files and writes summary.csv: per phase and column, n, p50, p95, max
and the share of frames over 33 ms. With llama.csv (from frametrace_atria.ps1) it adds per phase
``llama_tok_s`` (n = tokens, p50_ms column = tokens/s over the phase) and ``llama_gen_tok_s``
(tokens per second of llama's own generation time) rows.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

COLS = (
    "wait_ms",
    "begin_ms",
    "sync_ms",
    "render_ms",
    "end_ms",
    "total_ms",
    "pickup_ms",
    "interval_ms",
)


def pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))]


def main(out: Path) -> None:
    rows = []
    for f in sorted(out.glob("trace_*.csv")):
        phase = f.stem[len("trace_") :]
        vals: dict[str, list[float]] = {c: [] for c in COLS}
        last = None
        with f.open(newline="") as fh:
            for r in csv.DictReader(fh):
                for c in COLS[:-1]:
                    if r.get(c):
                        vals[c].append(float(r[c]))
                if r["kind"] == "render":
                    t = int(r["t_ns"])
                    if last is not None:
                        vals["interval_ms"].append((t - last) / 1e6)
                    last = t
        for c, xs in vals.items():
            if xs:
                over = 100.0 * sum(x > 33.0 for x in xs) / len(xs)
                rows.append(
                    [
                        phase,
                        c,
                        len(xs),
                        f"{pct(xs, 0.5):.2f}",
                        f"{pct(xs, 0.95):.2f}",
                        f"{max(xs):.2f}",
                        f"{over:.2f}",
                    ]
                )
    llama = out / "llama.csv"
    if llama.exists():
        with llama.open(newline="") as fh:
            for r in csv.DictReader(fh):
                for col, key in (("llama_tok_s", "tok_s"), ("llama_gen_tok_s", "gen_tok_s")):
                    if r.get(key):
                        rows.append([r["phase"], col, r["tokens"], r[key], "", "", ""])
    with (out / "summary.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["phase", "column", "n", "p50_ms", "p95_ms", "max_ms", "pct_over_33ms"])
        w.writerows(rows)
    for r in rows:
        print(",".join(map(str, r)))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
