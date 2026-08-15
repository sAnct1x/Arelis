"""Format approved facts for the system prompt.

Active facts are pinned alongside the location line. They are capped so a long
review history cannot crowd the persona out of the window.
"""

from __future__ import annotations

_MAX_FACTS = 24
_MAX_FACT_CHARS = 1200


def facts_prompt_line(facts: list[str]) -> str:
    """One system block listing approved facts, or empty when there are none."""
    cleaned: list[str] = []
    total = 0
    for raw in facts:
        text = " ".join(str(raw).split())
        if not text:
            continue
        # Keep individual lines short so one rambling fact cannot dominate.
        if len(text) > 200:
            text = text[:199].rstrip() + "…"
        if total + len(text) > _MAX_FACT_CHARS:
            break
        cleaned.append(text)
        total += len(text)
        if len(cleaned) >= _MAX_FACTS:
            break
    if not cleaned:
        return ""
    lines = [
        "Things you know about the user (approved facts; treat as durable, "
        "not guesses, and not a substitute for asking when unsure):"
    ]
    lines.extend(f"- {item}" for item in cleaned)
    return "\n".join(lines)
