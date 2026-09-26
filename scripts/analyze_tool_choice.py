"""Which utterances fail every time, and which just flicker?

`measure_tool_choice.py` prints a score per run. A score is the wrong unit to
act on: re-running one arm across three seeds moved it by two picks on sampling
alone, so a two-pick difference between configs means nothing, and chasing it
wastes the week.

What survives re-seeding is *which* cases fail. A case that misses in all
twelve runs is a defect with a cause you can go and find. A case that misses in
four of twelve is the model being a model.

    python scripts/measure_tool_choice.py --arm full --seed 1 --guarded \
        --json outputs/eval/tc_full_g1.json
    python scripts/analyze_tool_choice.py outputs/eval/tc_*.json

Reads the JSON any number of runs wrote and sorts by how stubborn each miss is.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

# Above this share of runs, a miss is a defect rather than sampling noise.
STUBBORN = 0.99
FLICKER = 0.25


def load(paths: list[Path]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for path in paths:
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"skipped {path}: {exc}")
            continue
        # measure_tool_choice writes a list of arm results per invocation.
        runs.extend(blob if isinstance(blob, list) else [blob])
    return runs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    paths: list[Path] = []
    for raw in args.paths:
        # Windows shells do not glob for us.
        paths.extend(sorted(raw.parent.glob(raw.name)) if "*" in raw.name else [raw])

    runs = load(paths)
    if not runs:
        print("no runs found")
        return 1

    misses: dict[str, int] = defaultdict(int)
    seen: dict[str, int] = defaultdict(int)
    picks: dict[str, set[str]] = defaultdict(set)
    wanted: dict[str, tuple[str, ...]] = {}
    by_config: dict[str, set[str]] = defaultdict(set)

    for run in runs:
        arm = str(run.get("arm") or "?")
        for row in run.get("rows") or []:
            utterance = str(row.get("utterance") or "")
            if not utterance:
                continue
            seen[utterance] += 1
            wanted[utterance] = tuple(row.get("accepts") or ())
            if not row.get("hit"):
                misses[utterance] += 1
                picks[utterance].add(str(row.get("picked") or "nothing"))
                by_config[utterance].add(arm)

    configs = sorted({str(r.get("arm") or "?") for r in runs})
    print(f"{len(runs)} runs across {len(configs)} configs: {', '.join(configs)}")
    print(f"{len(seen)} cases\n")

    ranked = sorted(
        ((u, misses.get(u, 0), seen[u]) for u in seen),
        key=lambda t: (-t[1], t[0]),
    )

    print("=" * 74)
    print("ALWAYS WRONG — a defect with a cause, worth going to find")
    print("=" * 74)
    any_stubborn = False
    for utterance, bad, total in ranked:
        if total and bad / total >= STUBBORN:
            any_stubborn = True
            print(f"\n  {utterance!r}")
            print(f"    missed {bad}/{total}  wanted {', '.join(wanted[utterance])}")
            print(f"    called {', '.join(sorted(picks[utterance]))}")
    if not any_stubborn:
        print("\n  none")

    print("\n" + "=" * 74)
    print("FLICKERS — sampling, not a defect. Do not chase these.")
    print("=" * 74)
    flickers = [(u, b, t) for u, b, t in ranked if t and FLICKER <= b / t < STUBBORN]
    for utterance, bad, total in flickers:
        armlist = ", ".join(sorted(by_config[utterance]))
        print(f"\n  {utterance!r}")
        print(f"    missed {bad}/{total}  called {', '.join(sorted(picks[utterance]))}")
        print(f"    in: {armlist}")
    if not flickers:
        print("\n  none")

    rare = sum(1 for _, b, t in ranked if t and 0 < b / t < FLICKER)
    clean = sum(1 for _, b, _ in ranked if b == 0)
    print(f"\n{clean} cases never missed, {rare} missed rarely.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
