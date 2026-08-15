"""Measure what the deterministic layer buys us on the models we actually run.

Two modes, both read-only.

``--mine`` attributes every tool run in logs/turns.log to a source (chat, voice,
soak, bench) and to an origin (the model asked for it, or the loop injected it).
The JSONL turn records name the tools that ran but not who chose them, so origin
comes from the gate marks the loop writes on the same turn id.

``--ab`` asks a live model for one tool call per utterance under four prompt and
schema conditions, so the cost of preflight nudges, skill focus cards and the
per-turn tool subset can be read as a delta rather than assumed. No tool is ever
executed here: the run stops at the tool call, which is also why it cannot send
a text or an email even by accident.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from arelis.eval.tool_choice import CHOICE_CASES

# Gate name -> the tool that gate injects. The loop logs the gate, not the tool.
GATE_TOOL = {
    "sms_force": "send_sms",
    "sms_redirect": "send_sms",
    "email_force": "send_email",
    "email_redirect": "send_email",
    "agenda_force": "agenda",
    "agenda_redirect": "agenda",
    "image_force": "image",
    "tasks_force": "tasks",
    "goals_force": "goals",
    "weather_once": "weather",
    "weather_redirect": "weather",
}

# The corpus itself lives in arelis/eval/tool_choice.py, where the test suite
# checks every named tool against the registry. Kept here it drifted silently:
# three cases still named briefing and attention hours after both were deleted,
# and a case naming a tool that is not offered can never pass.
CASES: list[tuple[str, tuple[str, ...]]] = [
    (case.utterance, case.accepts) for case in CHOICE_CASES
]

ARMS = ("bare", "core", "prod_full", "prod")


def _load_turn_log(path: Path) -> dict[str, dict[str, Any]]:
    """Group turns.log lines by turn id, keeping source and tool provenance."""
    turns: dict[str, dict[str, Any]] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = raw.split()
        if len(parts) < 4:
            continue
        event = parts[2]
        fields = dict(
            kv.split("=", 1) for kv in parts[3:] if "=" in kv
        )
        turn_id = fields.get("id") or "-"
        if turn_id == "-":
            continue
        rec = turns.setdefault(
            turn_id,
            {"source": "?", "tools": [], "injected": set(), "gates": []},
        )
        if event == "start":
            rec["source"] = fields.get("source") or "?"
        elif event == "tool":
            name = fields.get("name") or ""
            if name:
                rec["tools"].append(name)
        elif event in {"exactness", "verify", "look", "weather_once"}:
            gate = fields.get("gate") or event
            action = fields.get("action") or ""
            rec["gates"].append(f"{gate}:{action or '-'}")
            if action in {"inject", "preinject"}:
                tool = fields.get("tool") or GATE_TOOL.get(gate)
                if tool:
                    rec["injected"].add(tool)
    return turns


def mine(log_path: Path) -> None:
    turns = _load_turn_log(log_path)
    by_source: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    injected = collections.Counter()
    chosen = collections.Counter()
    live_sources = {"chat", "voice"}
    for rec in turns.values():
        source = str(rec["source"])
        for name in rec["tools"]:
            by_source[source][name] += 1
            if source not in live_sources:
                continue
            if name in rec["injected"]:
                injected[name] += 1
            else:
                chosen[name] += 1

    print(f"turns in log: {len(turns)}")
    print(f"sources: {dict(collections.Counter(r['source'] for r in turns.values()))}")
    print()
    print("tool runs by source")
    all_tools = sorted({n for c in by_source.values() for n in c})
    sources = sorted(by_source)
    head = "tool".ljust(18) + "".join(s.ljust(9) for s in sources)
    print(head)
    for name in all_tools:
        row = name.ljust(18)
        for source in sources:
            row += str(by_source[source][name] or "-").ljust(9)
        print(row)
    print()
    print("attended turns only (chat + voice): model-chosen vs loop-injected")
    print("tool".ljust(18) + "chosen".ljust(9) + "injected".ljust(10) + "verdict")
    for name in all_tools:
        c, i = chosen[name], injected[name]
        if not c and not i:
            verdict = "never ran on an attended turn"
        elif not c:
            verdict = "ONLY ever ran because we forced it"
        elif not i:
            verdict = "model picks it unaided"
        else:
            verdict = "mixed"
        print(name.ljust(18) + str(c).ljust(9) + str(i).ljust(10) + verdict)
    print()
    gate_counts = collections.Counter(
        g for rec in turns.values() for g in rec["gates"]
    )
    print("gate:action census")
    for gate, n in gate_counts.most_common():
        print(f"  {gate:34s} {n}")


def _first_call(calls: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    if not calls:
        return "", {}
    fn = calls[0].get("function") or calls[0]
    name = str(fn.get("name") or "")
    args = fn.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return name, args if isinstance(args, dict) else {}


def _build_arm(
    arm: str,
    text: str,
    *,
    persona: str,
    all_names: set[str],
    subset: set[str],
    focus: str,
    nudge: str | None,
) -> tuple[list[dict[str, str]], set[str]]:
    from arelis.core.agent_loop import now_line, static_system_prefix

    if arm == "bare":
        return [{"role": "system", "content": persona}], set(all_names)
    system = static_system_prefix(persona)
    if arm == "core":
        return [*system, {"role": "system", "content": now_line()}], set(all_names)
    if focus:
        system.append({"role": "system", "content": focus})
    if nudge:
        system.append({"role": "system", "content": nudge})
    # The clock trails everything, as it does in the loop. Ahead of the focus
    # card it re-prefilled every line behind it once a minute.
    system.append({"role": "system", "content": now_line()})
    return system, set(all_names) if arm == "prod_full" else set(subset)


def _turn_inputs(text: str, config: dict[str, Any], all_names: set[str]):
    from arelis.core.preflight import preflight_system_message
    from arelis.core.skills import assemble_skill_focus
    from arelis.core.tool_subset import filter_tool_names

    agent_cfg = config.get("agent") or {}
    subset = filter_tool_names(
        all_names,
        role="fast",
        text=text,
        enabled=bool(agent_cfg.get("research_tool_subset", True)),
        skill_subset=bool(agent_cfg.get("skill_tool_subset", True)),
        history=[],
    )
    return subset, assemble_skill_focus(text, available_tools=subset), (
        preflight_system_message(text, history=[])
    )


def _setup(model: str):
    from arelis.config import load_config
    from arelis.llm import build_router
    from arelis.tools import build_tool_registry

    config = load_config()
    router = build_router(config)
    provider = router.provider
    registry = build_tool_registry(
        config, allow_send=True, provider=provider, router=router
    )
    persona = Path(config["_persona_path"]).read_text(encoding="utf-8")
    print(f"model={model} registered_tools={len(registry.names())}")
    return config, provider, registry, persona


def sizes(arms: tuple[str, ...], cases: list[tuple[str, tuple[str, ...]]]) -> None:
    """Offline prompt accounting. Characters, not prompt_eval_count.

    Ollama reports prompt_eval_count inconsistently once a prefix is cached, so
    the live A/B cannot be trusted for prompt size. Assembling the same messages
    here and measuring them is exact and costs nothing.
    """
    config, _provider, registry, persona = _setup("(offline)")
    all_names = set(registry.names())
    totals: dict[str, list[int]] = {a: [] for a in arms}
    tool_totals: dict[str, list[int]] = {a: [] for a in arms}
    counts: dict[str, list[int]] = {a: [] for a in arms}
    for text, _expected in cases:
        subset, focus, nudge = _turn_inputs(text, config, all_names)
        for arm in arms:
            system, offer = _build_arm(
                arm,
                text,
                persona=persona,
                all_names=all_names,
                subset=subset,
                focus=focus,
                nudge=nudge,
            )
            tools = registry.ollama_tools(set(offer))
            sys_chars = sum(len(m["content"]) for m in system)
            tool_chars = len(json.dumps(tools))
            totals[arm].append(sys_chars + tool_chars + len(text))
            tool_totals[arm].append(tool_chars)
            counts[arm].append(len(tools))
    print()
    print(
        "arm".ljust(12)
        + "mean prompt chars".ljust(20)
        + "mean schema chars".ljust(20)
        + "mean tools".ljust(12)
        + "approx tokens (chars/4)"
    )
    for arm in arms:
        n = len(totals[arm]) or 1
        mean_all = sum(totals[arm]) // n
        mean_tool = sum(tool_totals[arm]) // n
        mean_n = sum(counts[arm]) / n
        print(
            arm.ljust(12)
            + str(mean_all).ljust(20)
            + str(mean_tool).ljust(20)
            + f"{mean_n:.1f}".ljust(12)
            + str(mean_all // 4)
        )


async def ab(
    model: str,
    out_path: Path | None,
    arms: tuple[str, ...],
    cases: list[tuple[str, tuple[str, ...]]],
    repeat: int,
) -> None:
    config, provider, registry, persona = _setup(model)
    all_names = set(registry.names())
    num_ctx = int((config.get("ollama") or {}).get("num_ctx") or 8192)

    rows: list[dict[str, Any]] = []
    for text, expected in cases:
        subset, focus, nudge = _turn_inputs(text, config, all_names)
        for arm in arms:
            system, offer = _build_arm(
                arm,
                text,
                persona=persona,
                all_names=all_names,
                subset=subset,
                focus=focus,
                nudge=nudge,
            )
            messages = [*system, {"role": "user", "content": text}]
            tools = registry.ollama_tools(set(offer))
            for rep in range(repeat):
                t0 = time.perf_counter()
                calls: list[dict[str, Any]] = []
                metrics: dict[str, Any] = {}
                prose = 0
                try:
                    async for kind, payload in provider.stream_chat(
                        model,
                        messages,
                        keep_alive="5m",
                        options={"temperature": 0.1, "num_ctx": num_ctx},
                        tools=tools,
                    ):
                        if kind == "tool_calls":
                            calls = payload
                        elif kind == "metrics":
                            metrics = payload
                        elif kind == "token":
                            prose += len(str(payload))
                except Exception as exc:  # a failed arm is data, not a crash
                    rows.append(
                        {
                            "text": text,
                            "arm": arm,
                            "rep": rep,
                            "error": str(exc)[:200],
                        }
                    )
                    continue
                ms = int((time.perf_counter() - t0) * 1000)
                name, args = _first_call(calls)
                rows.append(
                    {
                        "text": text,
                        "expected": list(expected),
                        "arm": arm,
                        "rep": rep,
                        "tool": name or "-",
                        "hit": bool(name and name in expected),
                        "args": sorted(args),
                        "offered": len(tools),
                        "offered_names": sorted(offer),
                        "prose_chars": prose,
                        "prompt_tokens": metrics.get("prompt_eval_count"),
                        "ms": ms,
                    }
                )
                got = name or f"(prose {prose}c)"
                flag = "ok " if name and name in expected else "MISS"
                print(
                    f"{flag} {arm:10s} r{rep} {text[:40]:40s} -> {got:16s} "
                    f"tools={len(tools):2d} {ms}ms"
                )

    print()
    print("arm".ljust(12) + "hit".ljust(10) + "no-call".ljust(10) + "mean ms")
    for arm in arms:
        got = [r for r in rows if r.get("arm") == arm and "error" not in r]
        if not got:
            continue
        hits = sum(1 for r in got if r["hit"])
        nocall = sum(1 for r in got if r["tool"] == "-")
        mean_ms = sum(r["ms"] for r in got) // len(got)
        print(
            arm.ljust(12)
            + f"{hits}/{len(got)}".ljust(10)
            + str(nocall).ljust(10)
            + str(mean_ms)
        )
    if repeat > 1:
        print()
        print("per-case stability (tool picked on each repeat)")
        for text, _expected in cases:
            for arm in arms:
                got = [
                    r
                    for r in rows
                    if r.get("text") == text
                    and r.get("arm") == arm
                    and "error" not in r
                ]
                if not got:
                    continue
                picks = [r["tool"] for r in got]
                stable = "stable" if len(set(picks)) == 1 else "FLAPS"
                hits = sum(1 for r in got if r["hit"])
                print(
                    f"  {arm:10s} {hits}/{len(got)} {stable:7s} "
                    f"{text[:38]:38s} {picks}"
                )
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps({"model": model, "rows": rows}, indent=2), encoding="utf-8"
        )
        print(f"\nwrote {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mine", action="store_true", help="attribute logged tool runs")
    ap.add_argument("--ab", action="store_true", help="live tool-choice A/B")
    ap.add_argument("--sizes", action="store_true", help="offline prompt accounting")
    ap.add_argument("--model", default="qwen2.5:7b")
    ap.add_argument("--log", default=str(PROJECT_ROOT / "logs" / "turns.log"))
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument(
        "--only",
        default="",
        help="comma-separated substrings; keep only matching cases",
    )
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    arms = tuple(a.strip() for a in args.arms.split(",") if a.strip())
    cases = CASES
    if args.only:
        needles = [n.strip().lower() for n in args.only.split(",") if n.strip()]
        cases = [c for c in CASES if any(n in c[0].lower() for n in needles)]
        if not cases:
            ap.error("--only matched no cases")
    if args.mine:
        mine(Path(args.log))
    if args.sizes:
        sizes(arms, cases)
    if args.ab:
        out = Path(args.out) if args.out else None
        asyncio.run(ab(args.model, out, arms, cases, max(1, args.repeat)))
    if not args.mine and not args.ab and not args.sizes:
        ap.error("pick --mine, --sizes or --ab")


if __name__ == "__main__":
    main()
