"""What the prompt actually costs, in tokens, against the configured window.

Every decision about hiding a tool or splitting a policy has been argued from an
estimate. This counts. Token counts come from Ollama's own tokenizer via
/api/embed when available and fall back to chars/4.

    python scripts/measure_prompt_budget.py
"""

from __future__ import annotations

import argparse
import json


def _tok(text: str) -> int:
    """chars/4. Good enough to compare parts of one prompt against each other."""
    return len(text) // 4


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--num-ctx", type=int, default=0)
    args = ap.parse_args()

    from arelis.config import load_config, load_persona
    from arelis.core.agent_loop import STATIC_TOOL_POLICY
    from arelis.core.skills import SKILL_CARDS, SKILL_CORE, assemble_tool_policy
    from arelis.tools import build_tool_registry

    config = load_config()
    num_ctx = args.num_ctx or int(
        ((config.get("ollama") or {}).get("num_ctx")) or 16384
    )

    persona = load_persona(config)
    registry = build_tool_registry(config)
    schemas = registry.ollama_tools()
    schema_json = json.dumps(schemas)

    essay_union = assemble_tool_policy(force_all=True)
    rows: list[tuple[str, int]] = [
        ("persona (unchanged)", _tok(persona)),
        ("SKILL_CORE (cards only, not shipped)", _tok(SKILL_CORE)),
        ("STATIC_TOOL_POLICY (telegraph)", _tok(STATIC_TOOL_POLICY)),
        ("essay union (not shipped)", _tok(essay_union)),
        (f"tool schemas ({len(schemas)} tools)", _tok(schema_json)),
    ]

    print(f"configured num_ctx: {num_ctx:,} tokens\n")
    print(f"{'part':<38}{'tokens':>9}{'% window':>10}")
    print("-" * 57)
    for name, n in rows:
        print(f"{name:<38}{n:>9,}{n / num_ctx * 100:>9.1f}%")

    print()
    biggest = max(_tok(c.body) for c in SKILL_CARDS.values())
    total_cards = sum(_tok(c.body) for c in SKILL_CARDS.values())
    print(f"{len(SKILL_CARDS)} skill cards, {total_cards:,} tokens total, "
          f"largest {biggest:,}")

    live = _tok(persona) + _tok(STATIC_TOOL_POLICY) + _tok(schema_json)
    old = _tok(persona) + _tok(essay_union) + _tok(schema_json)
    print()
    print(f"{'today (persona + telegraph + schemas)':<38}{live:>9,}{live / num_ctx * 100:>9.1f}%")
    print(f"{'old essay union + fat schemas (ref)':<38}{old:>9,}{old / num_ctx * 100:>9.1f}%")
    print(f"{'left for history and reply':<38}{num_ctx - live:>9,}"
          f"{(num_ctx - live) / num_ctx * 100:>9.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
