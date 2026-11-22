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


def test_virtual_desktop_abs_coords_maps_multi_monitor_and_negative_x(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multi-monitor setups with a left monitor have negative X coordinates."""
    import types

    import arelis.desktop.input as input_mod

    metrics = {
        input_mod.SM_XVIRTUALSCREEN: -1920,
        input_mod.SM_YVIRTUALSCREEN: 0,
        input_mod.SM_CXVIRTUALSCREEN: 3840,
        input_mod.SM_CYVIRTUALSCREEN: 1080,
    }
    fake_user32 = types.SimpleNamespace(
        GetSystemMetrics=lambda idx: metrics.get(idx, 0)
    )
    monkeypatch.setattr(
        input_mod, "_win", lambda: (None, None, None, fake_user32)
    )
    # Far-left edge of the left monitor (-1920, 0) -> (0, 0)
    assert input_mod._abs_coords(-1920, 0) == (0, 0)
    # Primary monitor origin (0, 540) -> midpoint X, midpoint Y
    ax, ay = input_mod._abs_coords(0, 540)
    assert 32700 <= ax <= 32800
    assert 32700 <= ay <= 32800
    # Far-right edge (1919, 1079) -> (65535, 65535)
    assert input_mod._abs_coords(1919, 1079) == (65535, 65535)


def test_foreground_root_prefers_element_from_handle_over_leaf_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_foreground_root binds to GetForegroundWindow HWND so leaf focus doesn't hide siblings."""
    import ctypes
    import types

    import arelis.desktop.snapshot as snap_mod

    hwnd_root = object()
    leaf_focus = object()
    seen_hwnds: list[int] = []

    class _FakeUIA:
        def ElementFromHandle(self, hwnd: int) -> object:
            seen_hwnds.append(hwnd)
            return hwnd_root

        def GetFocusedElement(self) -> object:
            return leaf_focus

        def GetRootElement(self) -> object:
            return None

    fake_user32 = types.SimpleNamespace(GetForegroundWindow=lambda: 0x1234)
    monkeypatch.setattr(
        ctypes, "windll", types.SimpleNamespace(user32=fake_user32), raising=False
    )
    root = snap_mod._foreground_root(_FakeUIA())
    assert root is hwnd_root
    assert seen_hwnds == [0x1234]


def test_find_ref_prefers_exact_and_prefix_over_substring() -> None:
    """Clicking 'Save' must pick 'Save' over 'Don't Save' even if 'Don't Save' came first."""
    from arelis.desktop.snapshot import DeskRef, find_ref

    refs = {
        "d1": DeskRef(ref="d1", name="Don't Save", role="button", x=10, y=10, w=50, h=20),
        "d2": DeskRef(ref="d2", name="Save As…", role="button", x=70, y=10, w=50, h=20),
        "d3": DeskRef(ref="d3", name="Save", role="button", x=130, y=10, w=50, h=20),
    }
    hit = find_ref(refs, text="Save")
    assert hit is not None
    assert hit.ref == "d3"
    prefix_hit = find_ref({"d1": refs["d1"], "d2": refs["d2"]}, text="Save")
    assert prefix_hit is not None
    assert prefix_hit.ref == "d2"


@pytest.mark.asyncio
async def test_desktop_session_refreshes_stale_refs_and_pauses_on_walls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale refs auto-refresh on click/type; password or UAC walls set_paused(True)."""
    from arelis.browser.hold import is_paused, set_paused
    from arelis.desktop.snapshot import DeskRef

    session = DesktopSession()
    monkeypatch.setattr(session, "_hands", lambda: None)
    clicked_coords: list[tuple[float, float]] = []

    async def fake_click_xy(x: float, y: float) -> None:
        clicked_coords.append((x, y))

    monkeypatch.setattr("arelis.desktop.session.click_xy", fake_click_xy)
    monkeypatch.setattr(
        "arelis.desktop.session.foreground_title", lambda: "Untitled - Notepad"
    )
    monkeypatch.setattr("arelis.desktop.session.uia_available", lambda: False)

    fresh_refs = {
        "d1": DeskRef(ref="d1", name="File", role="menuitem", x=25, y=15, w=30, h=20),
        "d2": DeskRef(
            ref="d2",
            name="Password",
            role="edit",
            x=100,
            y=100,
            w=120,
            h=24,
            is_password=True,
        ),
    }

    async def fake_snapshot() -> DeskResult:
        session.refs = dict(fresh_refs)
        return DeskResult(ok=True, output="[d1] menuitem 'File'")

    monkeypatch.setattr(session, "snapshot", fake_snapshot)

    # Start with stale refs that lack 'File' -> click should auto-snapshot and find 'File'
    session.refs = {
        "d9": DeskRef(ref="d9", name="Old Button", role="button", x=1, y=1, w=10, h=10)
    }
    res = await session.click(text="File")
    assert res.ok
    assert clicked_coords == [(25, 15)]
    # Refs are invalidated after a click so the next step sees fresh UI state
    assert session.refs == {}

    # Typing into a password control sets the pause latch and returns SECRET_FIELD
    set_paused(False)
    try:
        pw_res = await session.type_into("hunter2", ref="d2")
        assert not pw_res.ok
        assert pw_res.data.get("code") == "SECRET_FIELD"
        assert is_paused()
    finally:
        set_paused(False)


def test_desktop_aliases_resolve_common_windows_apps() -> None:
    """Common desktop apps resolve cleanly and trigger user_asked_for_desktop."""
    from arelis.core.preflight import user_asked_for_desktop
    from arelis.desktop.aliases import resolve_app

    assert resolve_app("VS Code") == ("code", None)
    assert resolve_app("Excel") == ("excel", None)
    assert resolve_app("File Explorer") == ("explorer", None)
    assert user_asked_for_desktop("open VS Code on my computer")
    assert user_asked_for_desktop("launch Excel")
    assert user_asked_for_desktop("switch to File Explorer")


@pytest.mark.asyncio
async def test_turn_execute_pauses_on_desktop_your_turn_and_finishes_on_destructive_wall() -> None:
    """execute_call emits TURN_PAUSE on desktop YOUR_TURN/SECRET_FIELD and finishes on delete/uac."""
    from types import SimpleNamespace

    from arelis.browser.hold import set_paused
    from arelis.core.events import EventType
    from arelis.core.turn_context import TurnContext
    from arelis.core.turn_execute import execute_call
    from arelis.tools.base import ToolRegistry, ToolResult

    events: list[tuple[EventType, dict[str, object]]] = []
    awaited_walls: list[tuple[str, str]] = []
    finished_texts: list[str] = []

    class _Bus:
        async def publish(self, ev: object) -> None:
            events.append((ev.type, dict(ev.payload or {})))  # type: ignore[attr-defined]

    class _FakeDesktopTool:
        name = "desktop"
        description = "desk"
        parameters_schema: dict[str, object] = {"type": "object", "properties": {}}
        risk = "side_effect"

        def __init__(self, result: ToolResult) -> None:
            self._result = result

        async def run(self, **_kwargs: object) -> ToolResult:
            return self._result

    async def _run_case(tool_res: ToolResult) -> bool:
        events.clear()
        awaited_walls.clear()
        finished_texts.clear()
        reg = ToolRegistry()
        reg.register(_FakeDesktopTool(tool_res))  # type: ignore[arg-type]

        async def fake_await_your_turn(
            kind: str, *, tool_name: str = "browser"
        ) -> None:
            awaited_walls.append((kind, tool_name))
            set_paused(False)

        async def fake_finish(
            text: str, _sources: object, *, streamed: str = "", **_kw: object
        ) -> None:
            del streamed
            finished_texts.append(text)

        loop = SimpleNamespace(
            bus=_Bus(),
            tools=reg,
            memory=SimpleNamespace(messages=[], sink=None),
            max_rounds=6,
            tool_output_chars=4000,
            tools_used=set(),
            _drive_session=True,
            _painted="",
            _look=None,
            _timer=None,
            _trace=[],
            _receipts=[],
            _expected_tools={"desktop"},
            _think_off_next=False,
            _fail_replan_used=False,
            _await_your_turn=fake_await_your_turn,
            _finish=fake_finish,
            _tool_message=lambda n, c: {"role": "tool", "tool_name": n, "content": c},
        )
        ctx = TurnContext(text="open notepad and type password", role="fast")
        ctx.tool_names = {"desktop"}
        r = SimpleNamespace(
            text=ctx.text,
            agent_cfg={},
            available_all={"desktop"},
            available={"desktop"},
            visible={"desktop"},
            tool_names=ctx.tool_names,
            sources=ctx.sources,
            ledger=ctx.ledger,
            fail_counts=ctx.fail_counts,
            web_search_ok=ctx.web_search_ok,
            page_ok=ctx.page_ok,
            sms_sent=ctx.sms_sent,
            agenda_created=ctx.agenda_created,
            chat_tools=[],
            messages=ctx.messages,
            sms_draft=None,
            email_draft=None,
        )
        return await execute_call(
            loop,
            ctx,
            r,  # type: ignore[arg-type]
            "desktop",
            {"action": "type", "into": "password", "text": "secret"},
            summary="desktop(action=type)",
            call_fp="desktop|type",
            round_i=1,
            call_i=0,
            fanout_results=None,
        )

    # 1. Password field pauses and awaits user Go on the desktop tool
    ended_pw = await _run_case(
        ToolResult(
            ok=False,
            output="Your turn: I do not type passwords.",
            data={"code": "SECRET_FIELD", "wall": "password"},
        )
    )
    assert not ended_pw
    pause_events = [p for t, p in events if t == EventType.TURN_PAUSE]
    assert len(pause_events) == 1
    assert pause_events[0]["tool"] == "desktop"
    assert pause_events[0]["kind"] == "password"
    assert awaited_walls == [("password", "desktop")]

    # 2. Destructive / UAC wall emits TURN_PAUSE and finishes the turn immediately
    ended_uac = await _run_case(
        ToolResult(
            ok=False,
            output="Your turn: I never click Yes on User Account Control.",
            data={"code": "YOUR_TURN", "wall": "uac"},
        )
    )
    assert ended_uac
    assert finished_texts == ["Your turn: I never click Yes on User Account Control."]
    assert awaited_walls == []


@pytest.mark.asyncio
async def test_desktop_hotkey_stops_on_destructive_combos_and_dblclick_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """hotkey refuses shift+delete / alt+f4 via YOUR_TURN; dblclick and right_click work."""
    from arelis.browser.hold import is_paused, set_paused
    from arelis.desktop.snapshot import DeskRef

    session = DesktopSession()
    monkeypatch.setattr(session, "_hands", lambda: None)
    monkeypatch.setattr(
        "arelis.desktop.session.foreground_title", lambda: "File Explorer"
    )
    doubled: list[tuple[float, float]] = []
    righted: list[tuple[float, float]] = []

    async def fake_dbl(x: float, y: float) -> None:
        doubled.append((x, y))

    async def fake_right(x: float, y: float) -> None:
        righted.append((x, y))

    monkeypatch.setattr("arelis.desktop.session.dblclick_xy", fake_dbl)
    monkeypatch.setattr("arelis.desktop.session.right_click_xy", fake_right)

    set_paused(False)
    try:
        del_res = await session.hotkey("shift+delete")
        assert not del_res.ok
        assert del_res.data.get("code") == "YOUR_TURN"
        assert del_res.data.get("wall") == "delete"
        assert is_paused()

        set_paused(False)
        f4_res = await session.hotkey("alt+f4")
        assert not f4_res.ok
        assert f4_res.data.get("code") == "YOUR_TURN"
        assert f4_res.data.get("wall") == "delete"
        assert is_paused()
    finally:
        set_paused(False)

    session.refs = {
        "d1": DeskRef(ref="d1", name="Report.docx", role="listitem", x=40, y=50, w=80, h=20)
    }
    tool = DesktopTool(session)
    res_dbl = await tool.run(action="dblclick", text="Report.docx")
    assert res_dbl.ok
    assert doubled == [(40, 50)]
    assert "Double-clicked Report.docx" in res_dbl.output

    session.refs = {
        "d1": DeskRef(ref="d1", name="Report.docx", role="listitem", x=40, y=50, w=80, h=20)
    }
    res_right = await tool.run(action="right_click", ref="d1")
    assert res_right.ok
    assert righted == [(40, 50)]
    assert "Right-clicked Report.docx" in res_right.output


def test_desktop_and_extended_browser_actions_emit_receipts_and_drive_done() -> None:
    """action_receipt covers desktop mutations and extended browser verbs; format_drive_done formats them."""
    from arelis.browser.hold import format_drive_done
    from arelis.core.receipts import action_receipt

    desk_rec = action_receipt(
        "desktop",
        ok=True,
        args={"action": "open", "target": "notepad"},
        data={"target": "notepad"},
    )
    assert desk_rec is not None
    assert desk_rec["action"] == "desktop.open"
    assert desk_rec["title"] == "notepad"

    dl_rec = action_receipt(
        "browser",
        ok=True,
        args={"action": "download", "ref": "e12"},
        data={"path": "outputs/downloads/report.csv", "url": "https://example.com"},
    )
    assert dl_rec is not None
    assert dl_rec["action"] == "browser.download"

    assert format_drive_done("focus", {"target": "Notepad"}) == "focused Notepad"
    assert format_drive_done("hotkey", {"keys": "ctrl+s"}) == "pressed ctrl+s"
    assert format_drive_done("dblclick", {"text": "Folder"}) == "double-clicked Folder"
    assert format_drive_done("download", {}) == "downloaded"


@pytest.mark.asyncio
async def test_desktop_type_text_chunks_and_encodes_utf16_surrogate_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """type_text splits long strings into 32-char batches and encodes >U+FFFF via UTF-16LE pairs."""
    import arelis.desktop.input as input_mod

    sent_batches: list[list[tuple[int, int, int]]] = []

    def fake_key_event(
        vk: int,
        *,
        up: bool = False,
        unicode_char: str = "",
        scan_unit: int | None = None,
    ) -> tuple[int, int, int]:
        unit = (
            int(scan_unit)
            if scan_unit is not None
            else (input_mod._utf16_units(unicode_char)[0] if unicode_char else 0)
        )
        return (vk, unit, 1 if up else 0)

    monkeypatch.setattr(input_mod, "_key_event", fake_key_event)
    monkeypatch.setattr(input_mod, "_send", lambda evs: sent_batches.append(list(evs)))

    # 1. Surrogate pair character (🚀 U+1F680 -> 0xD83D, 0xDE80)
    units = input_mod._utf16_units("🚀")
    assert units == (0xD83D, 0xDE80)
    await input_mod.type_text("A🚀")
    assert len(sent_batches) == 1
    assert sent_batches[0] == [
        (0, ord("A"), 0),
        (0, ord("A"), 1),
        (0, 0xD83D, 0),
        (0, 0xDE80, 0),
        (0, 0xD83D, 1),
        (0, 0xDE80, 1),
    ]

    # 2. Long text (70 chars) is sent in 3 chunks (32, 32, 6)
    sent_batches.clear()
    await input_mod.type_text("x" * 70)
    assert [len(b) // 2 for b in sent_batches] == [32, 32, 6]


@pytest.mark.asyncio
async def test_desktop_auto_snapshot_and_uia_value_and_toggle_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DeskRef formats non-secret value and toggle state; open/focus/click append a quick snapshot."""
    from arelis.desktop.snapshot import DeskRef, read_window

    ref_edit = DeskRef(
        ref="d1",
        name="Text Editor",
        role="edit",
        x=100,
        y=100,
        w=300,
        h=200,
        value="Hello from Notepad",
    )
    ref_chk = DeskRef(
        ref="d2",
        name="Word Wrap",
        role="checkbox",
        x=50,
        y=20,
        w=20,
        h=20,
        state="checked",
    )
    ref_secret = DeskRef(
        ref="d3",
        name="PIN",
        role="edit",
        x=50,
        y=50,
        w=80,
        h=20,
        is_password=True,
        value="9999",
    )
    assert "value='Hello from Notepad'" in ref_edit.line()
    assert "state=checked" in ref_chk.line()
    assert "9999" not in ref_secret.line()

    refs = {"d1": ref_edit, "d2": ref_chk, "d3": ref_secret}
    read_out = read_window(refs)
    assert "Text Editor: Hello from Notepad" in read_out
    assert "9999" not in read_out

    session = DesktopSession()
    monkeypatch.setattr("arelis.desktop.session.uia_available", lambda: True)
    monkeypatch.setattr(
        "arelis.desktop.session.foreground_title", lambda: "Untitled - Notepad"
    )
    monkeypatch.setattr(
        "arelis.desktop.session.snapshot_window",
        lambda: ("\n".join(r.line() for r in refs.values()), dict(refs), None),
    )
    monkeypatch.setattr(
        "arelis.desktop.session.open_app",
        lambda target, aliases=None: (f"Opened {target}.", None),
    )
    opened = await session.open("notepad")
    assert opened.ok
    assert opened.data.get("snapshot") is True
    assert "window: Untitled - Notepad" in opened.output
    assert "value='Hello from Notepad'" in opened.output






