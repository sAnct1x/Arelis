"""Local model matrix for foundation scenarios (optional live Ollama).

Offline (default): runs scripted eval plus the skill-retrieval paraphrase
board — no GPU needed.

Live:
  .\\.venv\\Scripts\\python.exe scripts\\bench_foundation.py --live \\
      --models qwen2.5:7b,qwen2.5:14b

Live mode calls Ollama for real tool-routing. It does not send SMS/email;
tools are stubs. Expect long wall-clock on a 12GB card.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.preflight import detect_intents
from arelis.core.skills import select_skill_ids
from arelis.eval.harness import (
    EvalResult,
    foundation_registry,
    parse_agent_overrides,
    run_all_scripted,
)
from arelis.eval.scenarios import SCENARIOS, Scenario, scenario_category
from arelis.eval.skill_retrieval import run_retrieval_board
from arelis.llm.ollama import OllamaProvider
from arelis.llm.router import ModelRouter


async def _run_live(scenario: Scenario, model: str, base_url: str) -> EvalResult:
    bus = EventBus()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    for et in (EventType.TOOL_START, EventType.TOOL_RESULT, EventType.ASSISTANT_DONE):
        bus.subscribe(et, capture)

    provider = OllamaProvider(base_url=base_url, timeout_s=300)
    router = ModelRouter(
        provider,
        {"fast": model, "research": model, "code": model},
        keep_alive="0",
        default_role="fast",
        options={"num_ctx": 8192},
    )
    tools = foundation_registry()

    async def _confirm(*_a: Any, **_k: Any) -> str:
        return "allow"

    loop = AgentLoop(
        bus,
        router,
        tools,
        SessionMemory(),
        persona="You are Arelis. Call tools when needed. Be brief.",
        config={
            "agent": {
                "max_rounds": 6,
                "tool_output_chars": 4000,
                "confirm_send": True,
                "json_fallback": True,
                "skill_cards": True,
                "intent_preflight": True,
                "lessons": True,
                "scrape_after_search": True,
                "sms_force_call": True,
                "exactness": True,
                "numeric_gate": True,
                "evidence_gate": True,
                "research_dual_hit": True,
                "turn_telemetry": False,
            },
            "ollama": {"num_ctx": 8192},
        },
        request_confirm=_confirm,
        is_cancelled=lambda: False,
    )

    t0 = time.perf_counter()
    bus_task = asyncio.create_task(bus.run())
    try:
        await loop.run(scenario.user, "fast", source="bench")
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
        try:
            await bus_task
        except asyncio.CancelledError:
            pass
    elapsed = time.perf_counter() - t0

    starts = [e for e in events if e.type == EventType.TOOL_START]
    tools_called = [str(e.payload.get("tool") or "") for e in starts]
    first_args: dict[str, Any] = {}
    if starts and isinstance(starts[0].payload.get("args"), dict):
        first_args = dict(starts[0].payload["args"])
    done = next((e for e in events if e.type == EventType.ASSISTANT_DONE), None)
    final = str((done.payload.get("text") if done else "") or "")
    reasons: list[str] = []
    if not tools_called:
        reasons.append("no tool calls")
    elif tools_called[0] not in scenario.expect_tools:
        reasons.append(f"first tool {tools_called[0]!r}")
    for key in scenario.require_args:
        match = first_args
        for e in starts:
            if e.payload.get("tool") in scenario.expect_tools and isinstance(
                e.payload.get("args"), dict
            ):
                match = e.payload["args"]
                break
        if key not in match or match.get(key) in (None, ""):
            reasons.append(f"missing arg {key}")
    return EvalResult(
        scenario_id=scenario.id,
        ok=not reasons,
        reasons=[*reasons, f"wall_s={elapsed:.1f}"],
        tools_called=tools_called,
        first_args=first_args,
        final_text=final[:200],
        skill_ids=select_skill_ids(scenario.user, available_tools=set(tools.names())),
        preflight_kinds=[h.kind for h in detect_intents(scenario.user)],
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call local Ollama (slow). Default is offline scripted eval.",
    )
    parser.add_argument(
        "--models",
        default="qwen2.5:7b",
        help="Comma-separated Ollama model tags for --live",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:11434",
        help="Ollama base URL",
    )
    parser.add_argument(
        "--agent-json",
        default="",
        help=(
            "Agent config overrides applied to every scenario, as JSON or as "
            "key=value pairs: skill_tool_subset=false,max_rounds=4. Wins over a "
            "scenario's own agent_config, so a gate can be measured off across "
            "the whole board."
        ),
    )
    args = parser.parse_args()

    try:
        overrides = parse_agent_overrides(args.agent_json)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"--agent-json could not be read: {exc}")
        return 2
    if overrides:
        print(f"agent overrides: {overrides}")

    if not args.live:
        results = await run_all_scripted(agent_overrides=overrides)
        ok = sum(1 for r in results if r.ok)
        by_id = {s.id: s for s in SCENARIOS}
        by_cat: dict[str, list[bool]] = {}
        for r in results:
            cat = scenario_category(by_id[r.scenario_id]) if r.scenario_id in by_id else "?"
            by_cat.setdefault(cat, []).append(r.ok)
        print(f"offline scripted: {ok}/{len(results)} passed")
        print("scorecard by category:")
        scorecard: dict[str, Any] = {
            "overall": {"passed": ok, "total": len(results)},
            "categories": {},
            "scenarios": [],
        }
        for cat in sorted(by_cat):
            vals = by_cat[cat]
            passed = sum(1 for v in vals if v)
            pct = 100.0 * passed / len(vals) if vals else 0.0
            print(f"  {cat}: {passed}/{len(vals)} ({pct:.0f}%)")
            scorecard["categories"][cat] = {
                "passed": passed,
                "total": len(vals),
                "pct": round(pct, 1),
            }
        for r in results:
            status = "PASS" if r.ok else "FAIL"
            cat = scenario_category(by_id[r.scenario_id]) if r.scenario_id in by_id else "?"
            print(
                f"  {status} [{cat}] {r.scenario_id} "
                f"tools={r.tools_called} {r.reasons}"
            )
            scorecard["scenarios"].append(
                {
                    "id": r.scenario_id,
                    "category": cat,
                    "ok": r.ok,
                    "tools": r.tools_called,
                    "reasons": r.reasons,
                }
            )
        retrieval = run_retrieval_board()
        scorecard["skill_retrieval"] = retrieval
        print(
            "skill_retrieval: "
            f"{retrieval['passed']}/{retrieval['total']} passed "
            f"P={retrieval['macro_precision']} R={retrieval['macro_recall']} "
            f"FP={retrieval['false_positive_rate']}"
        )
        for row in retrieval["cases"]:
            status = "PASS" if row["ok"] else "FAIL"
            print(
                f"  {status} {row['id']} skills={row['skill_ids']} {row['reasons']}"
            )
        out = ROOT / "logs" / "foundation_scorecard.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(scorecard, indent=2), encoding="utf-8")
        print(f"\nwrote {out}")
        retrieval_ok = retrieval["passed"] == retrieval["total"]
        return 0 if ok == len(results) and retrieval_ok else 1

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    report: dict[str, Any] = {"models": {}}
    for model in models:
        print(f"\n=== {model} ===")
        rows = []
        for scenario in SCENARIOS:
            if scenario.offline_only:
                continue
            try:
                result = await _run_live(scenario, model, args.base_url)
            except Exception as exc:
                result = EvalResult(
                    scenario_id=scenario.id,
                    ok=False,
                    reasons=[f"error: {exc}"],
                )
            status = "PASS" if result.ok else "FAIL"
            print(
                f"  {status} {result.scenario_id} tools={result.tools_called} "
                f"{result.reasons}"
            )
            rows.append(
                {
                    "id": result.scenario_id,
                    "ok": result.ok,
                    "tools": result.tools_called,
                    "reasons": result.reasons,
                }
            )
        passed = sum(1 for r in rows if r["ok"])
        report["models"][model] = {
            "passed": passed,
            "total": len(rows),
            "scenarios": rows,
        }
        print(f"  -> {passed}/{len(rows)}")

    out = ROOT / "logs" / "foundation_bench.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
