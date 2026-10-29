"""Asking what theme is on must name the one on the screen.

Night screenshots asked "what theme am I on right now?" and got "I don't know".
The palette was already installed. Nothing on the turn told her which one,
so the honest refusal was a lie about the room she was standing in.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from arelis.core.no_call_finish import run_finish_steps
from arelis.core.prompt_sections import append_delivery_context
from arelis.ui.theme import THEME_CHOICES, apply_theme
from arelis.ui.theme_tokens import theme_spoken_name
from tests.test_no_call_path import _ctx, _FakeLoop, _scratch

_ASK = "what theme am I on right now?"
_LABELS = dict(THEME_CHOICES)


def _delivery_blob() -> str:
    messages: list[dict[str, str]] = []
    append_delivery_context(messages, SimpleNamespace(config={}), speak=False)
    return "\n".join(message["content"] for message in messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("theme_id", list(_LABELS))
async def test_i_dont_know_on_a_theme_ask_names_the_live_theme(theme_id: str) -> None:
    apply_theme(theme_id)
    loop = _FakeLoop()
    scratch = _scratch(text=_ASK, content="I don't know")
    ctx = _ctx(text=_ASK)
    assert await run_finish_steps(loop, ctx, scratch, 0) == "finish"
    assert loop.finished is not None
    assert loop.finished[0] == f"You're on {theme_spoken_name(theme_id)}."


@pytest.mark.asyncio
async def test_a_legacy_theme_is_spoken_without_the_legacy_tag() -> None:
    apply_theme("sodium")
    assert _LABELS["sodium"] == "Sodium (legacy)"
    assert "(legacy)" not in _delivery_blob()
    loop = _FakeLoop()
    scratch = _scratch(text=_ASK, content="You're on Sodium (legacy).")
    ctx = _ctx(text=_ASK)
    assert await run_finish_steps(loop, ctx, scratch, 0) == "finish"
    assert loop.finished is not None
    assert loop.finished[0] == "You're on Sodium."


@pytest.mark.asyncio
async def test_an_invented_theme_is_replaced_with_the_live_one() -> None:
    apply_theme("night")
    loop = _FakeLoop()
    scratch = _scratch(text=_ASK, content="You're on sodium.")
    ctx = _ctx(text=_ASK)
    assert await run_finish_steps(loop, ctx, scratch, 0) == "finish"
    assert loop.finished is not None
    assert loop.finished[0] == "You're on Night."


