"""The front of the prompt must be identical on every turn, and must be whole.

Two properties, both about cost rather than wording:

Byte-stability, because Ollama's prefix cache is matched by prefix. Anything
that varies per turn has to sit *behind* the static block, or every turn
re-prefills the conversation behind it.

Completeness, because the alternative was selecting which rules to ship by
keyword, and a miss meant the model called a tool whose rules it had never been
given. These tests deliberately do not assert on the policy's prose — a test
that pins wording makes every prompt improvement look like a regression.
"""

from __future__ import annotations

from arelis.core.agent_loop import (
    STATIC_TOOL_POLICY,
    TOOL_POLICY,
    static_prefix_text,
    static_system_prefix,
)
from arelis.core.skills import SKILL_CARDS, SKILL_CORE


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
    """No selection step between the cards and the prompt."""
    assert STATIC_TOOL_POLICY == TOOL_POLICY


def test_every_card_reaches_the_prompt() -> None:
    """A rule that exists but is not shipped is worse than no rule.

    Named per card so a failure says which capability lost its rules, rather
    than that a length changed.
    """
    for card_id, card in SKILL_CARDS.items():
        assert card.body in STATIC_TOOL_POLICY, f"{card_id} card is not shipped"


def test_the_shared_preamble_reaches_the_prompt() -> None:
    assert SKILL_CORE in STATIC_TOOL_POLICY


def test_nothing_turn_specific_is_in_the_prefix() -> None:
    """The prefix must not carry a clock, a date, or a per-turn focus block."""
    from datetime import datetime

    prefix = static_prefix_text("You are Arelis.")
    now = datetime.now().astimezone()
    assert now.strftime("%H:%M") not in prefix
    assert now.strftime("%A") not in prefix
    assert "### This turn" not in prefix
