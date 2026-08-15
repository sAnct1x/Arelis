"""Profile cold vs warm TTFT from logs/turns.log (M3).

keep_alive / warm_on_start are already configured. This script answers *why*
a turn still paid 40-60s prefill: model unload (vision/research), idle past
keep_alive, or first request before pin.

Usage:
  python scripts/profile_ttft.py
  python scripts/profile_ttft.py --log logs/turns.log
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DONE_RE = re.compile(
    r"turn\s+\S+\s+done\s+.*?total_ms=(?P<total>\d+).*?"
    r"(?:model_prefill_ms=(?P<prefill>\d+)|prefill_ms=(?P<prefill2>\d+))?.*?"
    r"(?:ttft_ms=(?P<ttft>\d+))?"
)
# Thinking-line style also lands in events; turns.log uses structured fields.
ALT_RE = re.compile(
    r"done\s+.*?total_ms=(?P<total>\d+).*?ttft_ms=(?P<ttft>\d+)"
    r"(?:.*?model_prefill_ms=(?P<prefill>\d+))?"
)


def _parse_line(line: str) -> dict[str, int] | None:
    for pattern in (DONE_RE, ALT_RE):
        m = pattern.search(line)
        if not m:
            continue
        total = int(m.group("total"))
        ttft = m.groupdict().get("ttft")
        prefill = m.groupdict().get("prefill") or m.groupdict().get("prefill2")
        out = {"total_ms": total}
        if ttft:
            out["ttft_ms"] = int(ttft)
        if prefill:
            out["prefill_ms"] = int(prefill)
        return out
    # Fallback: loose field scrape
    if " done " not in line and not line.strip().startswith("turn "):
        return None
    if "total_ms=" not in line:
        return None
    fields = dict(re.findall(r"(total_ms|ttft_ms|model_prefill_ms|model_ms)=(\d+)", line))
    if "total_ms" not in fields:
        return None
    out = {"total_ms": int(fields["total_ms"])}
    if "ttft_ms" in fields:
        out["ttft_ms"] = int(fields["ttft_ms"])
    if "model_prefill_ms" in fields:
        out["prefill_ms"] = int(fields["model_prefill_ms"])
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log",
        type=Path,
        default=ROOT / "logs" / "turns.log",
        help="Path to turns.log",
    )
    parser.add_argument(
        "--cold-ms",
        type=int,
        default=20000,
        help="ttft_ms / prefill_ms at or above this counts as cold",
    )
    args = parser.parse_args()
    path: Path = args.log
    if not path.is_file():
        print(f"No log at {path}")
        return 1

    rows: list[dict[str, int]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parsed = _parse_line(line)
        if parsed:
            rows.append(parsed)

    if not rows:
        print(f"No done rows parsed from {path}")
        return 1

    cold = []
    warm = []
    for row in rows:
        metric = row.get("prefill_ms") or row.get("ttft_ms") or row["total_ms"]
        if metric >= args.cold_ms:
            cold.append(row)
        else:
            warm.append(row)

    print(f"Parsed {len(rows)} done rows from {path}")
    print(f"Cold (>= {args.cold_ms} ms prefill/ttft/total): {len(cold)}")
    print(f"Warm: {len(warm)}")
    if cold:
        cold_ttft = [r.get("ttft_ms") or r.get("prefill_ms") or r["total_ms"] for r in cold]
        print(
            f"Cold metric min/median/max ms: "
            f"{min(cold_ttft)} / {sorted(cold_ttft)[len(cold_ttft)//2]} / {max(cold_ttft)}"
        )
    if warm:
        warm_ttft = [r.get("ttft_ms") or r.get("prefill_ms") or r["total_ms"] for r in warm]
        print(
            f"Warm metric min/median/max ms: "
            f"{min(warm_ttft)} / {sorted(warm_ttft)[len(warm_ttft)//2]} / {max(warm_ttft)}"
        )

    print()
    print("Likely eviction causes (code-backed checklist):")
    print("  1. vision tool: unload chat -> VL -> unload VL -> delayed fast rewarm")
    print("  2. research/code role: non-default keep_alive (5m) then rewarm_delay")
    print("  3. idle past router.default_keep_alive (30m)")
    print("  4. embed model (nomic) briefly on card during recall/index")
    print("  5. first turn before warm_on_start pin completes")
    print()
    print("See docs/voice-ttft.md for the sensing-vs-model split.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
