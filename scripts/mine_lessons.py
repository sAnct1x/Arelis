"""Mine logs/turns.log for tool failures and append curated lessons.

Examples:

  .\\.venv\\Scripts\\python.exe scripts\\mine_lessons.py
  .\\.venv\\Scripts\\python.exe scripts\\mine_lessons.py --write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arelis.core.lesson_mine import mine_turns_log


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Append proposed catalog lessons into data/lessons.yaml (by id)",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Path to turns.log (default: logs/turns.log)",
    )
    parser.add_argument(
        "--lessons",
        type=Path,
        default=None,
        help="Path to lessons.yaml (default: data/lessons.yaml)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable report",
    )
    args = parser.parse_args()

    report = mine_turns_log(
        log_path=args.log,
        lessons_path=args.lessons,
        write=bool(args.write),
    )
    payload = {
        "lines_scanned": report.lines_scanned,
        "tool_fail_counts": report.tool_fail_counts,
        "tool_ok_counts": report.tool_ok_counts,
        "proposed_ids": list(report.proposed_ids),
        "already_present": list(report.already_present),
        "appended_ids": list(report.appended_ids),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"scanned {report.lines_scanned} lines")
        print(f"fails: {report.tool_fail_counts or '{}'}")
        print(f"oks:   {report.tool_ok_counts or '{}'}")
        print(f"proposed: {list(report.proposed_ids) or '—'}")
        print(f"already in playbook: {list(report.already_present) or '—'}")
        if args.write:
            print(f"appended: {list(report.appended_ids) or '—'}")
        else:
            print("(dry run - pass --write to append missing catalog entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
