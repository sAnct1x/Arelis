"""Does she pick the right tool unaided, and what does telling her more cost?

Every other board under ``arelis/eval`` scripts the tool call, so the script
makes the choice and the model's judgement never enters the loop. That is fine
for testing the correction machinery and useless for answering the question
this repo is actually organised around: is the tool schema good enough?

``arelis/eval/tool_choice.py`` has held the corpus for that since August with
no runner attached. This is the runner.

It measures both halves of the trade at once, from the same responses:

  benefit   how many of the 47 utterances get a defensible tool call
  cost      prompt_eval_count, which is the prefill the tools array causes

Three arms, differing only in the tools array:

  skinny    what ships today. `skinny_description` one-liners, and
            `skinny_parameters` strips every parameter description.
  params    the same one-liners, with the source parameter schemas intact.
            This is the arm the roadmap is about: 253 descriptions are
            already written and none of them reach the model.
  full      source tool descriptions as well. The upper bound on telling
            her more.

Nothing in `arelis/` is modified. This reads the registry and builds the
arrays itself, so a bad result costs nothing to walk away from.

    python scripts/measure_tool_choice.py --arm skinny --arm params
    python scripts/measure_tool_choice.py --all --json out.json

Needs Ollama up with the configured chat model. Roughly 4-8s per case per
arm on the reference card, so a full three-arm run is 15-20 minutes.

The prompt here is the static prefix only — persona plus the compact tool
policy — with no preflight line, no clock, and no injected facts. That is
deliberate: those are the guard rails, and a measurement that includes them
cannot tell you whether the schema is carrying its own weight. The number
this prints is the floor the guard rails are currently making up for.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from arelis.config import load_config, load_persona
from arelis.core.agent_loop import static_system_prefix
from arelis.core.preflight import preflight_system_message
from arelis.eval.tool_choice import CHOICE_CASES, score
from arelis.llm.ollama import OllamaProvider
from arelis.tools import build_tool_registry

ARMS = ("skinny", "params", "full")


def _registry() -> Any:
    """Attended, with a router, which is how a real session builds it.

    Skip either and `vision` and `camera` go missing, which would quietly
    make two of the corpus cases unanswerable.
    """
    router = SimpleNamespace(provider=SimpleNamespace(list_models=None))
    return build_tool_registry(
        load_config(), allow_send=True, attended=True, router=router
    )


def tool_array(registry: Any, arm: str) -> list[dict[str, Any]]:
    """The tools array for one arm, in registry order so only content differs."""
    skinny = list(registry.ollama_tools())
    if arm == "skinny":
        return skinny

    out: list[dict[str, Any]] = []
    for spec in skinny:
        fn = spec.get("function") or {}
        name = str(fn.get("name") or "")
        tool = registry.get(name)
        source = getattr(tool, "parameters_schema", None) or {
            "type": "object",
            "properties": {},
        }
        authored = (getattr(tool, "description", "") or "").strip()
        out.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": (
                        authored if (arm == "full" and authored) else fn.get("description", "")
                    ),
                    "parameters": source,
                },
            }
        )
    return out


async def ask_one(
    provider: OllamaProvider,
    model: str,
    prefix: list[dict[str, str]],
    tools: list[dict[str, Any]],
    utterance: str,
    *,
    num_ctx: int,
    temperature: float,
    seed: int | None,
    nudge: str = "",
) -> dict[str, Any]:
    """One utterance. Returns the tool picked plus the cost of asking."""
    options: dict[str, Any] = {"temperature": temperature, "num_ctx": num_ctx}
    if seed is not None:
        options["seed"] = seed

    # Production order: byte-stable prefix, then everything turn-specific.
    turn: list[dict[str, str]] = []
    if nudge:
        turn.append({"role": "system", "content": nudge})
    messages = [*prefix, *turn, {"role": "user", "content": utterance}]
    picked = ""
    extra_calls: list[str] = []
    metrics: dict[str, Any] = {}
    started = time.perf_counter()

    async for kind, payload in provider.stream_chat(
        model,
        messages,
        options=options,
        tools=tools,
        keep_alive="10m",
    ):
        if kind == "metrics":
            metrics = dict(payload or {})
        elif kind == "tool_calls" and payload:
            names = [
                str((c.get("function") or {}).get("name") or "") for c in payload
            ]
            picked = names[0] if names else ""
            extra_calls = names[1:]

    return {
        "utterance": utterance,
        "picked": picked,
        "also_called": extra_calls,
        "prompt_eval_count": metrics.get("prompt_eval_count"),
        "eval_count": metrics.get("eval_count"),
        "seconds": round(time.perf_counter() - started, 2),
    }


async def run_arm(
    arm: str,
    *,
    limit: int | None,
    seed: int | None,
    quiet: bool,
    guarded: bool = False,
) -> dict[str, Any]:
    config = load_config()
    registry = _registry()
    tools = tool_array(registry, arm)
    prefix = list(static_system_prefix(load_persona(config)))

    ollama_cfg = config.get("ollama") or {}
    model = str((config.get("models") or {}).get("fast") or "")
    num_ctx = int(ollama_cfg.get("num_ctx") or 65536)
    temperature = float((config.get("agent") or {}).get("tool_round_temperature") or 0.1)
    provider = OllamaProvider(
        base_url=str(ollama_cfg.get("base_url") or "http://127.0.0.1:11434"),
        timeout_s=float(ollama_cfg.get("timeout_s") or 300),
    )

    cases = CHOICE_CASES[:limit] if limit else CHOICE_CASES
    schema_chars = len(json.dumps(tools))

    label = f"{arm}+preflight" if guarded else arm
    if not quiet:
        print(f"\n=== arm: {label} ===")
        print(f"model {model} · {len(tools)} tools · schema {schema_chars:,} chars")

    rows: list[dict[str, Any]] = []
    nudged = 0
    for index, case in enumerate(cases, start=1):
        nudge = (preflight_system_message(case.utterance) or "") if guarded else ""
        if nudge:
            nudged += 1
        row = await ask_one(
            provider,
            model,
            prefix,
            tools,
            case.utterance,
            num_ctx=num_ctx,
            temperature=temperature,
            seed=seed,
            nudge=nudge,
        )
        row["nudged"] = bool(nudge)
        row["accepts"] = list(case.accepts)
        row["hit"] = case.hit(row["picked"])
        rows.append(row)
        if not quiet:
            mark = "ok  " if row["hit"] else "MISS"
            got = row["picked"] or "nothing"
            print(
                f"  {index:>2}/{len(cases)} {mark} {got:<16} {row['seconds']:>5.1f}s  "
                f"{case.utterance[:52]}"
            )

    picks = {r["utterance"]: r["picked"] for r in rows}
    hits, misses = score(picks) if not limit else (
        sum(1 for r in rows if r["hit"]),
        [
            f"{r['utterance']!r}: called {r['picked'] or 'nothing'}, "
            f"wanted one of {', '.join(r['accepts'])}"
            for r in rows
            if not r["hit"]
        ],
    )

    prefills = [r["prompt_eval_count"] for r in rows if r["prompt_eval_count"]]
    seconds = [r["seconds"] for r in rows]

    return {
        "arm": label,
        "schema": arm,
        "guarded": guarded,
        "cases_nudged": nudged,
        "model": model,
        "tools": len(tools),
        "schema_chars": schema_chars,
        "cases": len(rows),
        "hits": hits,
        "misses": misses,
        "prefill_median": int(statistics.median(prefills)) if prefills else 0,
        "prefill_max": max(prefills) if prefills else 0,
        "seconds_median": round(statistics.median(seconds), 2) if seconds else 0,
        "seconds_total": round(sum(seconds), 1),
        "rows": rows,
    }


def report(results: list[dict[str, Any]]) -> None:
    print("\n" + "=" * 72)
    print("TOOL CHOICE, UNAIDED")
    print("=" * 72)
    header = f"{'arm':<10} {'hits':>9} {'schema':>10} {'prefill':>9} {'median':>8}"
    print(header)
    print("-" * 72)
    for r in results:
        print(
            f"{r['arm']:<10} {r['hits']:>4}/{r['cases']:<4} "
            f"{r['schema_chars']:>9,} {r['prefill_median']:>9,} "
            f"{r['seconds_median']:>7.1f}s"
        )

    base = next((r for r in results if r.get("schema") == "skinny"), None)
    if base:
        for r in results:
            if r is base:
                continue
            d_hits = r["hits"] - base["hits"]
            d_pre = r["prefill_median"] - base["prefill_median"]
            d_sec = r["seconds_median"] - base["seconds_median"]
            print(
                f"\n{r['arm']} vs skinny: {d_hits:+d} correct picks, "
                f"{d_pre:+,} prefill tokens, {d_sec:+.1f}s median"
            )

    for r in results:
        if r["misses"]:
            print(f"\n--- {r['arm']} missed {len(r['misses'])} ---")
            for miss in r["misses"]:
                print(f"  {miss}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--arm", action="append", choices=ARMS, help="repeatable; default skinny"
    )
    parser.add_argument("--all", action="store_true", help="run every arm")
    parser.add_argument("--limit", type=int, help="first N cases only (smoke)")
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="fixed sampling seed so an A/B measures the schema, not variance",
    )
    parser.add_argument(
        "--no-seed",
        action="store_true",
        help="sample like production does; use with repeated runs to see noise",
    )
    parser.add_argument(
        "--guarded",
        action="store_true",
        help=(
            "add the preflight nudge, as production does. The gap against the "
            "same arm unguarded is what the guard rails are actually buying."
        ),
    )
    parser.add_argument("--json", type=Path, help="write full results here")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    arms = list(ARMS) if args.all else (args.arm or ["skinny"])
    seed = None if args.no_seed else args.seed

    results = [
        asyncio.run(
            run_arm(
                arm,
                limit=args.limit,
                seed=seed,
                quiet=args.quiet,
                guarded=args.guarded,
            )
        )
        for arm in arms
    ]
    report(results)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
