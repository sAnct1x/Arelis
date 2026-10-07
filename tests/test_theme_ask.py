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
from arelis.core.skills import select_skill_ids_detailed
from arelis.ui.theme import THEME_CHOICES, apply_theme
from tests.test_no_call_path import _ctx, _FakeLoop, _scratch

_ASK = "what theme am I on right now?"
_LABELS = dict(THEME_CHOICES)


def _delivery_blob() -> str:
    messages: list[dict[str, str]] = []
    append_delivery_context(messages, SimpleNamespace(config={}), speak=False)
    return "\n".join(message["content"] for message in messages)


@pytest.mark.parametrize("theme_id", list(_LABELS))
def test_what_theme_am_i_on_sees_the_live_name(theme_id: str) -> None:
    """The turn she answers from names this theme, and not a different one."""
    apply_theme(theme_id)
    label = _LABELS[theme_id]
    blob = _delivery_blob()
    assert label in blob
    for other_id, other in _LABELS.items():
        if other_id == theme_id:
            continue
        assert other not in blob


@pytest.mark.parametrize(
    "utterance",
    [
        "what theme am I on right now?",
        "what skin am I on?",
        "what's my current theme",
        "which theme are you on",
    ],
)
def test_a_plain_theme_question_is_not_a_web_search(utterance: str) -> None:
    tools = {"web_search", "scrape", "web_fetch", "workspace"}
    ids, fallback = select_skill_ids_detailed(utterance, available_tools=tools)
    assert "web" not in ids
    assert fallback is False


def test_a_book_theme_is_not_the_screen() -> None:
    tools = {"web_search", "scrape", "web_fetch"}
    ids, fallback = select_skill_ids_detailed(
        "what's the theme of Hamlet",
        available_tools=tools,
    )
    assert ids == ["web"]
    assert fallback is True


@pytest.mark.asyncio
@pytest.mark.parametrize("theme_id", list(_LABELS))
async def test_i_dont_know_on_a_theme_ask_names_the_live_theme(theme_id: str) -> None:
    apply_theme(theme_id)
    label = _LABELS[theme_id]
    loop = _FakeLoop()
    scratch = _scratch(text=_ASK, content="I don't know")
    ctx = _ctx(text=_ASK)
    assert await run_finish_steps(loop, ctx, scratch, 0) == "finish"
    assert loop.finished is not None
    assert loop.finished[0] == f"You're on {label}."


@pytest.mark.asyncio
async def test_an_invented_theme_is_replaced_with_the_live_one() -> None:
    apply_theme("night")
    loop = _FakeLoop()
    scratch = _scratch(text=_ASK, content="You're on sodium.")
    ctx = _ctx(text=_ASK)
    assert await run_finish_steps(loop, ctx, scratch, 0) == "finish"
    assert loop.finished is not None
    assert loop.finished[0] == "You're on night."


@pytest.mark.asyncio
async def test_a_reply_that_already_names_the_theme_is_kept() -> None:
    apply_theme("night")
    kept = "You're on night."
    loop = _FakeLoop()
    scratch = _scratch(text=_ASK, content=kept)
    ctx = _ctx(text=_ASK)
    assert await run_finish_steps(loop, ctx, scratch, 0) == "finish"
    assert loop.finished is not None
    assert loop.finished[0] == kept


@pytest.mark.asyncio
async def test_a_theme_question_bundled_with_something_else_is_left_alone() -> None:
    """A second ask in the same sentence still belongs to the model."""
    apply_theme("night")
    loop = _FakeLoop()
    text = "what theme am I on right now, and what's the weather"
    scratch = _scratch(text=text, content="I don't know")
    ctx = _ctx(text=text)
    assert await run_finish_steps(loop, ctx, scratch, 0) == "finish"
    assert loop.finished is not None
    assert loop.finished[0] == "I don't know"


@pytest.mark.asyncio
async def test_i_dont_know_on_some_other_ask_is_left_alone() -> None:
    apply_theme("night")
    loop = _FakeLoop()
    scratch = _scratch(text="hello", content="I don't know")
    ctx = _ctx(text="hello")
    assert await run_finish_steps(loop, ctx, scratch, 0) == "finish"
    assert loop.finished is not None
    assert loop.finished[0] == "I don't know"


@pytest.mark.asyncio
async def test_native_tool_calling_still_names_the_theme() -> None:
    apply_theme("sodium")
    loop = _FakeLoop()
    scratch = _scratch(
        text="what skin am I on?",
        content="I don't know",
        agent_cfg={"native_tool_calling": True},
    )
    ctx = _ctx(text="what skin am I on?")
    assert await run_finish_steps(loop, ctx, scratch, 0) == "finish"
    assert loop.finished is not None
    assert loop.finished[0] == "You're on sodium."
