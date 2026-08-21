"""The prompt we always send must fit in the smallest window we ever pin.

The whole tool policy now ships on every turn, which is only safe while the
window is genuinely large. When it is not, Ollama drops the overflow from the
*front* — the persona and the policy go first, silently, and the model answers
the rest of the session with no identity and no rules. There is no exception and
no error; the reply just gets worse.

So this is a budget test, not a style test. If someone adds a tool or a policy
section large enough to breach the floor, this fails here rather than in a
stranger's conversation.
"""

from __future__ import annotations

import json

import pytest

from arelis.config import load_config, shipped_num_ctx
from arelis.core.agent_loop import STATIC_TOOL_POLICY, static_prefix_text
from arelis.setup.context import _MIN_PINNED
from arelis.tools import build_tool_registry

# The same ratio the agent's own budget uses. Deliberately pessimistic against
# English prose, which runs nearer 4.5.
_CHARS_PER_TOKEN = 4

# What must be left over for history, the tool results, and the reply. A prompt
# that fits with nothing to spare does not fit.
_MIN_ROOM_FOR_CONVERSATION = 8000


def _tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


@pytest.fixture(scope="module")
def parts() -> dict[str, int]:
    config = load_config()
    persona_and_policy = static_prefix_text(
        (config.get("persona_text") or "") or "You are Arelis."
    )
    schemas = build_tool_registry(config).ollama_tools()
    return {
        "prefix": _tokens(persona_and_policy),
        "schemas": _tokens(json.dumps(schemas)),
        "tools": len(schemas),
    }


def test_the_shipped_window_holds_the_prompt(parts: dict[str, int]) -> None:
    total = parts["prefix"] + parts["schemas"]
    window = shipped_num_ctx()
    assert total < window, (
        f"prefix {parts['prefix']:,} + schemas {parts['schemas']:,} "
        f"= {total:,} tokens does not fit in num_ctx {window:,}"
    )


def test_the_smallest_pinned_window_holds_the_prompt(parts: dict[str, int]) -> None:
    """The floor is what an unreadable card gets. It has to work too."""
    total = parts["prefix"] + parts["schemas"]
    assert total < _MIN_PINNED, (
        f"{total:,} tokens does not fit in the floor of {_MIN_PINNED:,}"
    )


def test_the_smallest_window_leaves_room_to_talk(parts: dict[str, int]) -> None:
    spare = _MIN_PINNED - parts["prefix"] - parts["schemas"]
    assert spare >= _MIN_ROOM_FOR_CONVERSATION, (
        f"only {spare:,} tokens left for history and the reply at the "
        f"{_MIN_PINNED:,} floor; raise the floor or shrink the policy"
    )


def test_the_policy_is_the_smaller_half_of_the_prompt(parts: dict[str, int]) -> None:
    """A sanity bound on prose.

    The schemas are generated and the policy is written by hand, so the policy
    is the half that grows by accident. If it ever outweighs the schemas,
    somebody is writing an essay where a rule belongs.
    """
    assert _tokens(STATIC_TOOL_POLICY) < parts["schemas"]
