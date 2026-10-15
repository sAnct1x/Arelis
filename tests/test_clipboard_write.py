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

from arelis.tools.clipboard import ClipboardTool


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


@pytest.mark.asyncio
async def test_text_can_be_put_on_the_clipboard() -> None:
    board = _Board("old")
    result = await _tool(board).run(action="write", text="new thing")

    assert result.ok, result.output
    assert board.writes == ["new thing"]
    assert board.text == "new thing"


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


# ------------------------------------------------------------------ the gate


