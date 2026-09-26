"""Score the shipping tool-choice arm and fail below the live floor.

The measurement harness (`measure_tool_choice.py`) compares schema arms.
This is the nightly: skinny schema + preflight, the config that ships,
checked against `tests.eval_floors.CHOICE_LIVE_FLOOR`.

    python scripts/run_choice_board.py
    python scripts/run_choice_board.py --json choice-board.json

Needs Ollama up with the configured chat model. If the daemon is down,
exits 0 with a skip (GitHub-hosted runners will not have it). Set
`ARELIS_REQUIRE_LIVE=1` to turn that skip into a hard fail — the flag
for a real nightly on a desk that is supposed to have the model.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arelis.config import load_config
from arelis.setup.engine import ollama_reachable
from tests.eval_floors import CHOICE_LIVE_FLOOR


def _require_live() -> bool:
    return os.environ.get("ARELIS_REQUIRE_LIVE", "").strip() == "1"


def _base_url() -> str:
    ollama_cfg = load_config().get("ollama") or {}
    return str(ollama_cfg.get("base_url") or "http://127.0.0.1:11434")


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--json",
        type=Path,
        default=Path("choice-board.json"),
        help="write the report here (default choice-board.json)",
    )
    parser.add_argument("--limit", type=int, help="first N cases only (smoke)")
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="fixed sampling seed; default is production (unseeded)",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    base_url = _base_url()

    if not ollama_reachable(base_url):
        reason = f"Ollama is unreachable at {base_url}"
        payload = {
            "skipped": True,
            "reason": reason,
            "base_url": base_url,
            "arm": "skinny+preflight",
            "hits": None,
            "misses": [],
            "model": None,
            "timestamp": stamp,
            "floor": CHOICE_LIVE_FLOOR,
        }
        _write_report(args.json, payload)
        if _require_live():
            print(f"FAIL: {reason} (ARELIS_REQUIRE_LIVE=1)")
            return 1
        print(f"SKIP: {reason}. Nightly board not scored.")
        return 0

    from scripts.measure_tool_choice import run_arm

    result = asyncio.run(
        run_arm(
            "skinny",
            limit=args.limit,
            seed=args.seed,
            quiet=args.quiet,
            guarded=True,
        )
    )

    hits = int(result["hits"])
    cases = int(result["cases"])
    payload = {
        "skipped": False,
        "arm": result["arm"],
        "schema": result["schema"],
        "guarded": result["guarded"],
        "hits": hits,
        "cases": cases,
        "misses": result["misses"],
        "model": result["model"],
        "timestamp": stamp,
        "floor": CHOICE_LIVE_FLOOR,
        "seconds_total": result["seconds_total"],
        "rows": result["rows"],
    }
    _write_report(args.json, payload)

    line = f"choice board  {hits}/{cases}  floor {CHOICE_LIVE_FLOOR}  model {result['model']}"
    if hits < CHOICE_LIVE_FLOOR:
        print(f"FAIL: {line}")
        for miss in result["misses"]:
            print(f"  {miss}")
        return 1
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
