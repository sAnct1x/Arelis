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
    from arelis.core.agent_loop import STATIC_TOOL_POLICY, TOOL_POLICY
    from arelis.core.skills import SKILL_CARDS, SKILL_CORE
    from arelis.tools import build_tool_registry

    config = load_config()
    num_ctx = args.num_ctx or int(
        ((config.get("ollama") or {}).get("num_ctx")) or 16384
    )

    persona = load_persona(config)
    registry = build_tool_registry(config)
    schemas = registry.ollama_tools()
    schema_json = json.dumps(schemas)

    rows: list[tuple[str, int]] = [
        ("persona", _tok(persona)),
        ("SKILL_CORE (shipped every turn)", _tok(SKILL_CORE)),
        ("STATIC_TOOL_POLICY (live prefix)", _tok(STATIC_TOOL_POLICY)),
        ("TOOL_POLICY (full union)", _tok(TOOL_POLICY)),
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

    # What a turn costs if the whole policy ships statically.
    full = _tok(persona) + _tok(TOOL_POLICY) + _tok(schema_json)
    live = _tok(persona) + _tok(STATIC_TOOL_POLICY) + _tok(schema_json)
    print()
    print(f"{'today (core + schemas + persona)':<38}{live:>9,}{live / num_ctx * 100:>9.1f}%")
    print(f"{'full policy shipped statically':<38}{full:>9,}{full / num_ctx * 100:>9.1f}%")
    print(f"{'left for history and reply':<38}{num_ctx - full:>9,}"
          f"{(num_ctx - full) / num_ctx * 100:>9.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
