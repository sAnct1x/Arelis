"""Production multi-tool bounce soak.

Exercises SMS → calendar → SMS → weather → delete → create → image → vision →
email → adversarial SMS-inject under one shared AgentLoop session, with
per-turn latency and a JSON + markdown report.

Default is offline (scripted model + stub tools). Pass --live to drive qwen
via Ollama while keeping stub side-effect tools.

  .\\.venv\\Scripts\\python.exe scripts\\soak_tools.py
  .\\.venv\\Scripts\\python.exe scripts\\soak_tools.py --fail-fast
  .\\.venv\\Scripts\\python.exe scripts\\soak_tools.py --live
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arelis.config import PROJECT_ROOT, load_config
from arelis.eval.conversation import format_markdown_report, run_conversation_soak
from arelis.eval.harness import parse_agent_overrides
from arelis.eval.soak_scenarios import production_bounce_turns


def _write_reports(report: Any, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "soak_tools.json"
    md_path = out_dir / "soak_tools.md"
    json_path.write_text(
        json.dumps(report.to_dict(), indent=2, default=str),
        encoding="utf-8",
    )
    md_path.write_text(format_markdown_report(report), encoding="utf-8")
    return json_path, md_path


async def _run(args: argparse.Namespace) -> int:
    turns = production_bounce_turns()
    live_router = None
    mode = "live" if args.live else "mock"
    if args.live:
        from arelis.llm import build_router

        cfg = load_config()
        live_router = build_router(cfg)

    try:
        overrides = parse_agent_overrides(getattr(args, "agent_json", ""))
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"--agent-json could not be read: {exc}")
        return 2
    if overrides:
        print(f"agent overrides: {overrides}")

    report = await run_conversation_soak(
        turns,
        soak_id="production_tool_bounce",
        mode=mode,
        fail_fast=bool(args.fail_fast),
        live_router=live_router,
        agent_cfg=overrides or None,
    )
    out_dir = Path(args.out) if args.out else (PROJECT_ROOT / "logs")
    json_path, md_path = _write_reports(report, out_dir)

    print(report.summary)
    print(format_markdown_report(report))
    print(f"\nWrote {json_path}")
    print(f"Wrote {md_path}")
    return 0 if report.ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Drive Ollama for model rounds; tools stay stubs (no real SMS/email).",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on first failing turn.",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Report directory (default: logs/).",
    )
    parser.add_argument(
        "--agent-json",
        default="",
        help=(
            "Agent config overrides, as JSON or as key=value pairs: "
            "sms_force_call=false. Merged over the soak defaults, so a gate can "
            "be measured off without editing the scenarios."
        ),
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
