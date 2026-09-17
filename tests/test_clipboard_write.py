"""The prompt advertised a clipboard write that did not exist.

Roadmap 4.4. `compact_prompt.py` told the model "read / write OS clipboard"
while `ClipboardTool.parameters_schema` had no action at all — only
`max_chars`. So "copy that to my clipboard" was a routing bug by construction:
the model was told the verb existed, picked the right tool, and there was
nothing there to call.

Same pattern as the other five verbs this phase: the plumbing was already
written. `_write_windows_clipboard` has been in this module the whole time,
carrying a docstring that said "used by tests and the live pass, not a tool
action". Somebody built it and never cut the door.

Two things a clipboard write has to get right, and both are tested below.
Writing calls EmptyClipboard first, so it destroys whatever the user had
copied — that is why it stays behind Allow like the read does. And the Allow
card has to say which one is about to happen; a write that shows "Read system
clipboard text" is asking the user to approve the wrong thing.
"""

from __future__ import annotations

from typing import Any

import pytest

from arelis.tools.base import capability_class
from arelis.tools.clipboard import ClipboardTool
from arelis.tools.confirm_copy import confirm_headline
from arelis.tools.policy import action_is_delete, confirm_toggle


class _Board:
    """Stands in for the OS clipboard."""

    def __init__(self, text: str = "") -> None:
        self.text = text
        self.writes: list[str] = []

    def read(self) -> str:
        return self.text

    def write(self, text: str) -> None:
        self.writes.append(text)
        self.text = text


def _tool(board: _Board, **kwargs: Any) -> ClipboardTool:
    return ClipboardTool(reader=board.read, writer=board.write, **kwargs)


# ------------------------------------------------------------------ the verb


def test_the_schema_offers_both_verbs() -> None:
    actions = ClipboardTool.parameters_schema["properties"]["action"]["enum"]
    assert sorted(actions) == ["read", "write"]
    assert "text" in ClipboardTool.parameters_schema["properties"]


@pytest.mark.asyncio
async def test_text_can_be_put_on_the_clipboard() -> None:
    board = _Board("old")
    result = await _tool(board).run(action="write", text="new thing")

    assert result.ok, result.output
    assert board.writes == ["new thing"]
    assert board.text == "new thing"


@pytest.mark.asyncio
async def test_reading_still_works_and_is_still_the_default() -> None:
    """No action means read. Breaking that would break every existing turn."""
    board = _Board("what was copied")
    result = await _tool(board).run()

    assert result.ok, result.output
    assert "what was copied" in result.output
    assert not board.writes


@pytest.mark.asyncio
async def test_a_write_with_no_text_is_refused_rather_than_clearing_it() -> None:
    """Writing "" would wipe the clipboard, which is not what was asked for."""
    board = _Board("do not lose me")
    result = await _tool(board).run(action="write")

    assert not result.ok
    assert "text" in result.output.lower()
    assert not board.writes
    assert board.text == "do not lose me"


@pytest.mark.asyncio
async def test_an_unknown_action_says_what_is_allowed() -> None:
    board = _Board()
    result = await _tool(board).run(action="paste")

    assert not result.ok
    assert "read" in result.output
    assert "write" in result.output
    assert not board.writes


@pytest.mark.asyncio
async def test_a_failing_write_does_not_report_success() -> None:
    board = _Board("kept")

    def _boom(_text: str) -> None:
        raise OSError("SetClipboardData failed (5)")

    tool = ClipboardTool(reader=board.read, writer=_boom)
    result = await tool.run(action="write", text="nope")

    assert not result.ok
    assert "clipboard" in result.output.lower()


@pytest.mark.asyncio
async def test_the_written_text_is_not_echoed_back_in_full() -> None:
    """The user just told her what it is; repeating a wall of it is noise."""
    board = _Board()
    result = await _tool(board).run(action="write", text="x" * 4000)

    assert result.ok, result.output
    assert len(result.output) < 300


# ------------------------------------------------------------------ the gate


def test_a_write_still_needs_allow() -> None:
    """It calls EmptyClipboard, so it destroys what the user had copied."""
    assert confirm_toggle("clipboard", {"action": "write"}) == "writes"
    assert confirm_toggle("clipboard", {"action": "read"}) == "writes"
    assert capability_class("clipboard", {"action": "write"}) == "SIDE_EFFECT_LOCAL"


def test_a_clipboard_write_is_not_classed_as_a_delete() -> None:
    assert not action_is_delete("clipboard", {"action": "write"})


def test_the_allow_card_says_which_one_is_about_to_happen() -> None:
    """A write showing "Read system clipboard text" asks for the wrong consent."""
    read_card = confirm_headline("clipboard", {"action": "read"})
    write_card = confirm_headline("clipboard", {"action": "write"})

    assert "read" in read_card.lower()
    assert read_card != write_card
    assert "replace" in write_card.lower() or "write" in write_card.lower()
    # The thing the user is actually giving up.
    assert "replace" in write_card.lower()


def test_the_model_is_told_the_verb_exists() -> None:
    from arelis.core.compact_prompt import _SHORT_DESC

    assert "write" in _SHORT_DESC["clipboard"]
    assert "write" in ClipboardTool.description.lower()
