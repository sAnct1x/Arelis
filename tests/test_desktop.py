"""Desktop tool: sanctuary, policy, preflight, mocked session — no SendInput."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from arelis.desktop.sanctuary import (
    is_denied_exe,
    looks_like_raw_path,
    refuse_launch_target,
)
from arelis.desktop.session import DeskResult, DesktopSession
from arelis.tools.desktop_tool import DesktopTool
from arelis.tools.policy import (
    action_is_destructive,
    evaluate_capability,
    evaluate_confirm,
    set_confirm_mode,
)


def test_sanctuary_refuses_shells_and_raw_paths() -> None:
    assert is_denied_exe("powershell.exe")
    assert is_denied_exe("cmd")
    assert is_denied_exe("regedit")
    assert not is_denied_exe("notepad.exe")
    assert looks_like_raw_path(r"C:\Windows\System32\cmd.exe")
    assert looks_like_raw_path(r"D:\tools\foo.exe")
    assert not looks_like_raw_path("notepad")
    assert refuse_launch_target("cmd") is not None
    assert refuse_launch_target(r"C:\Windows\System32\notepad.exe") is not None
    assert refuse_launch_target("notepad") is None


def test_policy_desktop_confirm_and_destructive() -> None:
    set_confirm_mode("card")
    assert evaluate_capability("desktop", {"action": "open"}) == "SIDE_EFFECT_LOCAL"
    assert evaluate_confirm(
        "desktop", {"action": "open", "target": "notepad"}, risk="side_effect"
    )
    assert not evaluate_confirm(
        "desktop",
        {"action": "open", "target": "notepad"},
        asked=True,
        risk="side_effect",
    )
    assert action_is_destructive(
        "desktop", {"action": "click", "text": "Empty Recycle Bin"}
    )
    assert action_is_destructive("desktop", {"action": "click", "text": "Pay now"})
    assert not action_is_destructive(
        "desktop", {"action": "open", "target": "notepad"}
    )
    assert evaluate_confirm(
        "desktop",
        {"action": "click", "text": "Delete"},
        asked=True,
        risk="side_effect",
    )
    set_confirm_mode("voice")
    assert not evaluate_confirm(
        "desktop", {"action": "open", "target": "notepad"}, risk="side_effect"
    )
    assert evaluate_confirm(
        "desktop", {"action": "click", "text": "Uninstall"}, risk="side_effect"
    )
    set_confirm_mode("card")


@pytest.mark.asyncio
async def test_desktop_tool_unknown_and_refuse_cmd() -> None:
    session = DesktopSession()
    session.open = AsyncMock(  # type: ignore[method-assign]
        return_value=DeskResult(ok=False, output="cmd.exe is not something I start.")
    )
    tool = DesktopTool(session)
    miss = await tool.run(action="explode")
    assert not miss.ok
    assert "Unknown action" in miss.output
    blocked = await tool.run(action="open", target="cmd")
    assert not blocked.ok


@pytest.mark.asyncio
async def test_pixel_click_gated_until_vision() -> None:
    session = DesktopSession()
    session.click = AsyncMock(  # type: ignore[method-assign]
        return_value=DeskResult(ok=False, output="x,y needs screenshot")
    )
    tool = DesktopTool(session)
    tool.pixel_ok = False
    result = await tool.run(action="click", x=10, y=20)
    assert not result.ok
    session.click.assert_awaited()
    assert session.click.await_args.kwargs["pixel_ok"] is False


# --- Desk-look corpus (intended product). Write before changing the regex. ---

DESK_LOOK_YES = (
    "look at my right monitor",
    "look at my left monitor",
    "look at the screen",
    "look at my monitor",
    "look at my second display",
    "what's on my other screen",
    "what's on the screen",
    "what's on my screen",
    "do you see the 2nd paragraph?",
    "can you see problem 2.22? how do I solve this?",
    "look at the book on that monitor",
    "look at the book",
    "look at my homework",
    "look at this pdf",
    "look at the textbook",
    "read the homework on the left",
    "read the book",
    "describe what's on the screen",
    "on my other monitor",
    "can you explain the 2nd paragraph",
    "do you see question 3.1",
    "look at my vertical monitor",
    "look at the screen above",
    "what's on the monitor above",
    "what's the second paragraph about?",
    "read the homework on the left monitor",
    "screenshot my primary monitor",
    "screenshot my primary monitor and tell me what you can see",
    "take a screenshot of my left monitor",
    "screenshot the screen",
)

DESK_LOOK_NO = (
    "look at this",
    "look at the camera",
    "look at the webcam",
    "look at the desk camera",
    "look at the room webcam",
    "do you see problem 2.22 on the camera",
    "what do you see",
    "what am I looking at",
    "Screenshot this page and tell me what you see",
    "screenshot this tab",
    "screenshot the site",
    "what's on this page",
    "what's on this tab",
    "look at this in my browser",
    "look at this screenshot",
    "look at this image",
    "look at the files",
    "pause",
    "pause the simulation",
    "span 2",
    "use 2 monitors",
    "2 monitors",
    "filament 2",
    "open youtube",
    "delete this",
    "forget that",
    "Pay now",
    "can you explain that",
    "how do I solve this",
    "now the third paragraph",
    "and problem 2.23",
    "solve problem 2.23",
    "explain that paragraph",
)

DESK_LOOK_FOLLOWUP = (
    "now the third paragraph",
    "and problem 2.23",
    "what's the second paragraph about?",
    "solve problem 2.23",
    "explain that paragraph",
    "can you explain that",
    "how do I solve this",
)

DESK_LOOK_PRIOR = [
    {"role": "user", "content": "look at the book on my right monitor"},
    {"role": "assistant", "content": "I see a page of exercises."},
]


# Session 2026-10-04: a declined or complaining message must not look at the
# desk, and must not count as the user asking for it (no Allow card skip).
DESK_LOOK_DECLINED = (
    "no need to look at the book, its just crazy that she wrote a scenario",
    "no need to look at the book",
    "why did you look at my screen",
    "I don't want you to look at the book",
    "you shouldn't have looked at my screen",
)


