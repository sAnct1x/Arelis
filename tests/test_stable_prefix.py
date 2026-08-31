"""The front of the prompt must be identical on every turn, and must be whole.

Two properties, both about cost rather than wording:

Byte-stability, because Ollama's prefix cache is matched by prefix. Anything
that varies per turn has to sit *behind* the static block, or every turn
re-prefills the conversation behind it.

Completeness, because the alternative was selecting which rules to ship by
keyword, and a miss meant the model called a tool whose rules it had never been
given. The telegraph names every governed tool. These tests do not pin card
essays — a test that pins wording makes every prompt improvement look like a
regression.
"""

from __future__ import annotations

from arelis.core.agent_loop import (
    STATIC_TOOL_POLICY,
    TOOL_POLICY,
    static_prefix_text,
    static_system_prefix,
)
from arelis.core.skills import SKILL_CARDS


def test_static_prefix_identical_across_assemblies() -> None:
    persona = "You are Arelis, a local assistant."
    assert static_prefix_text(persona) == static_prefix_text(persona)


def test_static_prefix_is_persona_then_the_whole_policy() -> None:
    persona = "Persona line."
    msgs = static_system_prefix(persona)
    assert len(msgs) == 2
    assert msgs[0] == {"role": "system", "content": persona}
    assert msgs[1] == {"role": "system", "content": STATIC_TOOL_POLICY}
    assert static_prefix_text(persona).startswith(persona)


def test_the_shipped_policy_is_the_whole_policy() -> None:
    """No selection step between compact_tool_policy and the prefix."""
    assert STATIC_TOOL_POLICY == TOOL_POLICY


def test_every_named_tool_reaches_the_prompt() -> None:
    """A card's tool must be named in the telegraph. Essays stay in skills.py."""
    for card_id, card in SKILL_CARDS.items():
        tool = card.requires_tool
        if not tool:
            continue
        assert tool in STATIC_TOOL_POLICY, f"{card_id} tool {tool} is not named"


def test_the_shared_preamble_reaches_the_prompt() -> None:
    """Core call/fallback rules, not the SKILL_CORE essay."""
    text = STATIC_TOOL_POLICY.lower()
    assert "would you like me to proceed" in text
    assert '{"tool":' in STATIC_TOOL_POLICY
    assert '{"final":' in STATIC_TOOL_POLICY
    assert "attach" in text


def test_nothing_turn_specific_is_in_the_prefix() -> None:
    """The prefix must not carry a clock, a date, or a per-turn focus block.

    Do not assert on a bare weekday name. The shipped policy uses examples
    like "next Friday", and that is static. The live clock is
    ``now_line()``: "Friday, 21 August 2026, 00:33".
    """
    from datetime import datetime

    prefix = static_prefix_text("You are Arelis.")
    now = datetime.now().astimezone()
    stamp = now.strftime("%A, %d %B %Y").replace(" 0", " ")
    assert now.strftime("%H:%M") not in prefix
    assert stamp not in prefix
    assert now.strftime("%Y-%m-%d") not in prefix
    assert "### This turn" not in prefix
    assert "Right now it is" not in prefix
