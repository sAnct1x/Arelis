"""Does hiding tools actually save prefill, once the prefix cache is involved?

Subsetting removes schema tokens from the prompt, which looks like a saving when
you count tokens. But Ollama renders the tools array near the *front* of the
prompt, so a tools array that changes shape from turn to turn changes the prefix
— and a changed prefix cannot be reused, which means the persona, the policy and
the whole conversation behind it are prefilled again.

This measures both effects against a live Ollama, reporting prompt_eval_count
(how many tokens were actually processed rather than reused) and
prompt_eval_duration.

    python scripts/measure_tool_surface_prefill.py
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request

NS = 1_000_000_000


def _chat(base: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{base}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _run(base: str, model: str, messages: list[dict], tools: list[dict],
         num_ctx: int) -> tuple[int, float]:
    body: dict = {
        "model": model,
        "messages": messages,
        "stream": False,
        "keep_alive": "5m",
        "options": {"num_ctx": num_ctx, "num_predict": 1, "temperature": 0},
    }
    if tools:
        body["tools"] = tools
    started = time.perf_counter()
    data = _chat(base, body)
    wall = time.perf_counter() - started
    processed = int(data.get("prompt_eval_count") or 0)
    dur = float(data.get("prompt_eval_duration") or 0) / NS
    return processed, dur or wall


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3.5:9b")
    ap.add_argument("--base", default="http://127.0.0.1:11434")
    args = ap.parse_args()

    from arelis.config import load_config, load_persona, shipped_num_ctx
    from arelis.core.agent_loop import STATIC_TOOL_POLICY
    from arelis.tools import build_tool_registry

    config = load_config()
    num_ctx = shipped_num_ctx()
    registry = build_tool_registry(config)
    all_tools = registry.ollama_tools()
    names = sorted(registry.names())

    # Two plausible per-turn subsets, the way _skill_subset would produce them.
    subset_a = registry.ollama_tools({n for n in names if n in {
        "weather", "user_location", "web_fetch", "calculator", "cas", "units"}})
    subset_b = registry.ollama_tools({n for n in names if n in {
        "workspace", "git_info", "analyze", "calculator", "cas", "units"}})

    system = [
        {"role": "system", "content": load_persona(config)},
        {"role": "system", "content": STATIC_TOOL_POLICY},
    ]
    # A few turns of history, so "re-prefill everything behind the tools" has
    # something behind it to be worth measuring.
    history: list[dict] = []
    for i in range(6):
        history.append({"role": "user", "content": f"Question number {i} about the project."})
        history.append({"role": "assistant", "content": f"Answer number {i}. " * 40})

    def turn(q: str) -> list[dict]:
        return [*system, *history, {"role": "user", "content": q}]

    print(f"model={args.model}  num_ctx={num_ctx:,}")
    print(f"full surface: {len(all_tools)} tools; subsets: "
          f"{len(subset_a)} and {len(subset_b)} tools\n")

    print("A. constant full surface, same shape every turn")
    for i, q in enumerate(["What's the weather?", "Summarise the readme.",
                           "What's the weather?"]):
        processed, dur = _run(args.base, args.model, turn(q), all_tools, num_ctx)
        print(f"   turn {i + 1}: prefilled {processed:>6,} tokens in {dur:>6.2f}s")

    print("\nB. subset that changes shape each turn")
    for i, (q, tools) in enumerate(
        [
            ("What's the weather?", subset_a),
            ("Summarise the readme.", subset_b),
            ("What's the weather?", subset_a),
        ]
    ):
        processed, dur = _run(args.base, args.model, turn(q), tools, num_ctx)
        print(f"   turn {i + 1}: prefilled {processed:>6,} tokens in {dur:>6.2f}s")

    print(
        "\nprompt_eval_count is tokens actually processed. A number far below the\n"
        "prompt size means the prefix cache was reused; a number near it means\n"
        "the whole prompt was prefilled again."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
