"""Desktop tool: sanctuary, policy, preflight, mocked session — no SendInput."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from arelis.core.preflight import (
    detect_intents,
    looks_like_desktop_ask,
    looks_like_desktop_look,
    user_asked_for_desktop,
)
from arelis.desktop.aliases import resolve_app
from arelis.desktop.pixels import (
    DeskScreen,
    assign_sides,
    looks_like_monitor_token,
    resolve_screen,
)
from arelis.desktop.sanctuary import (
    is_denied_exe,
    looks_like_raw_path,
    refuse_launch_target,
)
from arelis.desktop.session import DeskResult, DesktopSession
from arelis.tools import build_tool_registry
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


def test_alias_resolve() -> None:
    key, err = resolve_app("notepad")
    assert err is None
    assert key == "notepad"
    key, err = resolve_app("calculator")
    assert key == "calc"
    key, err = resolve_app("File Explorer")
    assert key == "explorer"


def test_preflight_open_notepad_is_desktop_not_browser() -> None:
    assert looks_like_desktop_ask("open notepad and write hello")
    hints = detect_intents("open notepad and write hello")
    assert any(h.kind == "desktop" for h in hints)
    assert "desktop" in {t for h in hints for t in h.expected_tools}
    assert not any(h.kind == "browser" for h in hints)


def test_preflight_look_at_monitor_is_desktop_not_browser() -> None:
    for text in (
        "look at my right monitor",
        "do you see the 2nd paragraph?",
        "can you see problem 2.22? how do I solve this?",
        "what's on my other screen",
        "look at the book on that monitor",
    ):
        assert looks_like_desktop_look(text), text
        assert user_asked_for_desktop(text), text
        hints = detect_intents(text)
        assert any(h.kind == "desktop_look" for h in hints), text
        assert not any(h.kind == "browser_vision" for h in hints), text


def test_preflight_page_screenshot_stays_browser() -> None:
    assert not looks_like_desktop_look("Screenshot this page and tell me what you see")
    hints = detect_intents("Screenshot this page and tell me what you see")
    assert any(h.kind == "browser_vision" for h in hints)


def test_monitor_token_and_sides() -> None:
    assert looks_like_monitor_token("left")
    assert looks_like_monitor_token("2")
    assert looks_like_monitor_token("primary")
    assert not looks_like_monitor_token("Kindle")
    rows = assign_sides(
        [
            DeskScreen(1, "A", True, 0, 0, 1920, 1080, "center"),
            DeskScreen(2, "B", False, 1920, 0, 1920, 1080, "center"),
        ]
    )
    assert resolve_screen("left", rows) is not None
    assert resolve_screen("left", rows).index == 1
    assert resolve_screen("right", rows).index == 2
    assert resolve_screen("other", rows).index == 2
    assert resolve_screen("1", rows).index == 1


def test_preflight_open_youtube_stays_browser() -> None:
    assert not looks_like_desktop_ask("open youtube")
    hints = detect_intents("open youtube")
    assert any(h.kind == "browser" for h in hints)
    assert not any(h.kind == "desktop" for h in hints)


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


def test_jobs_omit_desktop() -> None:
    config = {"tools": {}, "agent": {}, "workspace": {"roots": ["."]}}
    jobs = build_tool_registry(config, allow_send=False, attended=False)
    assert "desktop" not in jobs.names()
    present = build_tool_registry(config, allow_send=False, attended=True)
    assert "desktop" in present.names()


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
async def test_desktop_tool_open_and_type_mocked() -> None:
    session = DesktopSession()
    session.open = AsyncMock(  # type: ignore[method-assign]
        return_value=DeskResult(ok=True, output="Opened notepad.", data={"target": "notepad"})
    )
    session.type_into = AsyncMock(  # type: ignore[method-assign]
        return_value=DeskResult(ok=True, output="Typed.")
    )
    tool = DesktopTool(session)
    opened = await tool.run(action="open", target="notepad")
    assert opened.ok
    typed = await tool.run(action="type", text="hello")
    assert typed.ok
    session.type_into.assert_awaited()


@pytest.mark.asyncio
async def test_screenshot_passes_monitor_target() -> None:
    session = DesktopSession()
    session.screenshot = AsyncMock(  # type: ignore[method-assign]
        return_value=DeskResult(ok=True, output="shot", data={"path": "x.png"})
    )
    session.monitors = AsyncMock(  # type: ignore[method-assign]
        return_value=DeskResult(ok=True, output="1|primary|1920x1080|only")
    )
    tool = DesktopTool(session)
    listed = await tool.run(action="monitors")
    assert listed.ok
    shot = await tool.run(action="screenshot", target="left")
    assert shot.ok
    session.screenshot.assert_awaited()
    assert session.screenshot.await_args.args[0] == "left"


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


def test_desk_look_corpus_should_match() -> None:
    missed = [text for text in DESK_LOOK_YES if not looks_like_desktop_look(text)]
    assert missed == [], missed


def test_desk_look_corpus_should_not_match() -> None:
    leaked = [text for text in DESK_LOOK_NO if looks_like_desktop_look(text)]
    assert leaked == [], leaked


def test_desk_look_corpus_not_browser_vision() -> None:
    for text in DESK_LOOK_YES:
        kinds = {h.kind for h in detect_intents(text)}
        assert "browser_vision" not in kinds, text
        if looks_like_desktop_look(text):
            assert "desktop_look" in kinds, text


def test_desk_look_page_tab_stay_out() -> None:
    for text in (
        "Screenshot this page and tell me what you see",
        "screenshot this tab",
        "what's on this page",
        "what's on this tab",
    ):
        assert not looks_like_desktop_look(text), text


def test_desk_look_followup_after_prior_look() -> None:
    """After a look, paragraph / problem fragments still route to the desk."""
    missed = []
    for text in DESK_LOOK_FOLLOWUP:
        if not looks_like_desktop_look(text, history=DESK_LOOK_PRIOR):
            missed.append(text)
        kinds = {h.kind for h in detect_intents(text, history=DESK_LOOK_PRIOR)}
        if "desktop_look" not in kinds:
            missed.append(f"hint:{text}")
    assert missed == [], missed


def test_desk_look_followup_alone_is_not_a_webcam() -> None:
    for text in DESK_LOOK_FOLLOWUP:
        from arelis.core.look import has_look_context

        assert not has_look_context(text, dock_live=True, history=DESK_LOOK_PRIOR), text


def test_look_ask_is_grant_offer_still_pauses() -> None:
    set_confirm_mode("card")
    assert user_asked_for_desktop("look at my right monitor")
    assert not evaluate_confirm(
        "desktop",
        {"action": "screenshot", "target": "right"},
        asked=True,
        risk="side_effect",
    )
    assert evaluate_confirm(
        "desktop",
        {"action": "screenshot", "target": "right"},
        asked=False,
        risk="side_effect",
    )
    assert evaluate_confirm(
        "desktop",
        {"action": "click", "text": "Delete"},
        asked=True,
        risk="side_effect",
    )
    set_confirm_mode("card")


def test_importing_look_and_preflight_both_orders() -> None:
    import importlib

    import arelis.core.look as look_mod
    import arelis.core.preflight as preflight_mod

    importlib.reload(look_mod)
    importlib.reload(preflight_mod)
    assert look_mod.has_look_context("look at the camera")
    assert preflight_mod.looks_like_desktop_look("look at my monitor")
    importlib.reload(preflight_mod)
    importlib.reload(look_mod)
    assert preflight_mod.looks_like_desktop_look("do you see problem 2.22")
    assert not look_mod.has_look_context(
        "do you see problem 2.22 on my right monitor?", dock_live=True
    )


def test_assign_sides_three_wide_and_other_is_ambiguous() -> None:
    rows = assign_sides(
        [
            DeskScreen(1, "A", True, 0, 0, 1920, 1080, "center"),
            DeskScreen(2, "B", False, 1920, 0, 1920, 1080, "center"),
            DeskScreen(3, "C", False, 3840, 0, 1920, 1080, "center"),
        ]
    )
    assert resolve_screen("left", rows) is not None
    assert resolve_screen("left", rows).index == 1
    assert resolve_screen("center", rows).index == 2
    assert resolve_screen("middle", rows).index == 2
    assert resolve_screen("right", rows).index == 3
    assert resolve_screen("other", rows) is None


def test_assign_sides_vertical_stack() -> None:
    rows = assign_sides(
        [
            DeskScreen(1, "A", True, 0, 0, 1920, 1080, "center"),
            DeskScreen(2, "B", False, 0, 1080, 1920, 1080, "center"),
        ]
    )
    assert resolve_screen("top", rows) is not None
    assert resolve_screen("top", rows).index == 1
    assert resolve_screen("above", rows).index == 1
    assert resolve_screen("bottom", rows).index == 2
    assert resolve_screen("below", rows).index == 2
    assert looks_like_monitor_token("vertical")
    assert looks_like_monitor_token("top")
    assert resolve_screen("vertical", rows) is not None
    assert resolve_screen("vertical", rows).index == 2


def test_match_window_the_book_is_not_kindle() -> None:
    from arelis.desktop.windows import DeskWindow, match_window

    rows = [
        DeskWindow(hwnd=11, title="Kindle", pid=1),
        DeskWindow(hwnd=12, title="homework.pdf — Adobe Acrobat", pid=2),
    ]
    assert match_window("the book", rows) is None
    assert match_window("Kindle", rows) is not None
    assert match_window("Adobe", rows) is not None
    from arelis.desktop.windows import match_reader_window

    book = match_reader_window("the book", rows)
    assert book is not None
    assert book.title == "Kindle"


@pytest.mark.asyncio
async def test_screenshot_unknown_window_does_not_grab_as_monitor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arelis.desktop import session as session_mod
    from arelis.desktop.windows import DeskWindow

    grabbed: list[str] = []

    def _no_screen(**kwargs: object) -> object:
        grabbed.append(str(kwargs.get("target") or ""))
        raise AssertionError("grab_screen must not run for a window title")

    monkeypatch.setattr(session_mod, "grab_screen", _no_screen)
    monkeypatch.setattr(session_mod, "match_reader_window", lambda _raw: None)
    monkeypatch.setattr(
        session_mod,
        "list_windows",
        lambda: [DeskWindow(hwnd=1, title="Kindle", pid=1)],
    )
    monkeypatch.setattr(session_mod, "looks_like_monitor_token", lambda _raw: False)
    out = await DesktopSession().screenshot("the book")
    assert not out.ok
    assert "Kindle" in out.output
    assert grabbed == []


def test_screen_covering_picks_the_window_display() -> None:
    from arelis.desktop.pixels import screen_covering

    rows = assign_sides(
        [
            DeskScreen(1, "A", True, 0, 0, 1920, 1080, "center", handle="primary"),
            DeskScreen(2, "B", False, 1920, 0, 1920, 1080, "center", handle="right"),
        ]
    )
    hit = screen_covering(2000, 40, rows)
    assert hit is not None
    assert hit.index == 2
    assert hit.handle == "right"


def test_grab_window_uses_the_window_screen(tmp_path, monkeypatch) -> None:
    from arelis.desktop import pixels as pix

    class FakePix:
        def __init__(self, *, empty: bool = False) -> None:
            self._empty = empty

        def isNull(self) -> bool:
            return self._empty

        def save(self, path: str, _fmt: str) -> bool:
            from pathlib import Path

            Path(path).write_bytes(b"png")
            return True

    class FakeScreen:
        def __init__(self, name: str) -> None:
            self.name = name
            self.calls: list[int] = []

        def grabWindow(self, hwnd: int) -> FakePix:
            self.calls.append(int(hwnd))
            return FakePix()

    primary = FakeScreen("primary")
    other = FakeScreen("other")
    rows = [
        DeskScreen(1, "A", True, 0, 0, 1920, 1080, "left", handle=primary),
        DeskScreen(2, "B", False, 1920, 0, 1920, 1080, "right", handle=other),
    ]
    dest = tmp_path / "win.png"
    path = pix.grab_window(42, dest, screens=rows, center=(2100, 80))
    assert path == dest
    assert dest.is_file()
    assert other.calls == [42]
    assert primary.calls == []


def test_empty_window_grab_fails_loud(tmp_path) -> None:
    from arelis.desktop import pixels as pix

    class EmptyPix:
        def isNull(self) -> bool:
            return True

    class FakeScreen:
        def grabWindow(self, _hwnd: int) -> EmptyPix:
            return EmptyPix()

    rows = [
        DeskScreen(1, "A", True, 0, 0, 1920, 1080, "only", handle=FakeScreen()),
    ]
    with pytest.raises(RuntimeError, match=r"empty|overlay|protected"):
        pix.grab_window(7, tmp_path / "empty.png", screens=rows, center=(10, 10))


def test_screen_for_window_falls_back_to_primary_when_rect_misses(
    monkeypatch,
) -> None:
    """Tool windows / offscreen pytest QScreens often have no GetWindowRect."""
    from arelis.desktop import pixels as pix

    rows = [
        DeskScreen(
            1, "", True, 0, 0, 800, 800, "only",
            handle="p", device=r"\\.\DISPLAY2",
        ),
    ]
    monkeypatch.setattr(pix, "monitor_device_for_hwnd", lambda _hwnd: None)
    monkeypatch.setattr(pix, "window_center", lambda _hwnd: None)
    hit = pix.screen_for_window(7, rows)
    assert hit is not None
    assert hit.primary
    assert hit.handle == "p"


def test_screen_for_window_device_beats_misleading_center() -> None:
    """HiDPI: GetWindowRect pixels ≠ QScreen.geometry(). Trust the OS name."""
    from arelis.desktop.pixels import screen_for_window

    rows = assign_sides(
        [
            DeskScreen(1, r"\\.\DISPLAY1", True, 0, 0, 1920, 1080, "left", handle="p"),
            DeskScreen(2, r"\\.\DISPLAY2", False, 1920, 0, 1920, 1080, "right", handle="o"),
        ]
    )
    hit = screen_for_window(
        9, rows, center=(100, 40), device=r"\\.\DISPLAY2"
    )
    assert hit is not None
    assert hit.index == 2
    assert hit.handle == "o"


def test_screen_for_window_device_when_model_names_collide() -> None:
    from arelis.desktop.pixels import screen_for_window

    rows = [
        DeskScreen(
            1, "Odyssey G5 (2)", True, 0, 0, 2560, 1440, "center",
            handle="p", device=r"\\.\DISPLAY2",
        ),
        DeskScreen(
            2, "Odyssey G5 (1)", False, 2560, 0, 2560, 1440, "right",
            handle="r", device=r"\\.\DISPLAY1",
        ),
        DeskScreen(
            3, "Odyssey G5 (2)", False, -2560, 0, 2560, 1440, "left",
            handle="l", device=r"\\.\DISPLAY3",
        ),
    ]
    hit = screen_for_window(1, rows, center=(80, 40), device=r"\\.\DISPLAY3")
    assert hit is not None
    assert hit.index == 3
    assert hit.handle == "l"


def test_look_needles_from_ordinary_asks() -> None:
    from arelis.desktop.observe import look_needles

    assert "2.22" in look_needles("can you see problem 2.22? how do I solve this?")
    assert any("second paragraph" in n for n in look_needles("what's the second paragraph about?"))
    assert look_needles("2.22") == ["2.22"]
    assert look_needles("left") == []


def test_tile_boxes_split_a_huge_page() -> None:
    from arelis.desktop.observe import tile_boxes

    boxes = tile_boxes(3840, 2160, max_edge=1600)
    assert len(boxes) > 1
    assert tile_boxes(800, 600, max_edge=1600) == [(0, 0, 800, 600)]
    xs = {b[0] for b in boxes}
    ys = {b[1] for b in boxes}
    assert 0 in xs and 0 in ys
    assert max(b[0] + b[2] for b in boxes) == 3840
    assert max(b[1] + b[3] for b in boxes) == 2160


def test_tiled_read_finds_needle_whole_page_missed(tmp_path) -> None:
    from PIL import Image

    from arelis.desktop.observe import read_still

    page = tmp_path / "huge.png"
    Image.new("RGB", (3200, 2000), "white").save(page)

    def ocr(path):
        with Image.open(path) as im:
            w, h = im.size
        if w >= 3200 and h >= 2000:
            return "Chapter 4 Exercises"
        return "2.22 wait for the limit"

    seen = read_still(page, needles=["2.22"], ocr=ocr)
    assert seen.tiled
    assert "2.22" in seen.found
    assert seen.missed == ()


def test_observe_miss_is_honest(tmp_path) -> None:
    from PIL import Image

    from arelis.desktop.observe import format_observe, read_still

    page = tmp_path / "blank.png"
    Image.new("RGB", (200, 100), "white").save(page)
    seen = read_still(page, needles=["2.22"], ocr=lambda _p: "header footer")
    assert seen.missed == ("2.22",)
    assert "Could not resolve: 2.22" in format_observe(seen)
    assert "will not invent" in format_observe(seen)


@pytest.mark.asyncio
async def test_screenshot_reads_the_still(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PIL import Image

    from arelis.desktop import session as session_mod

    dest = tmp_path / "desktop_page.png"
    Image.new("RGB", (80, 40), "white").save(dest)
    monkeypatch.setattr(session_mod, "grab_screen", lambda **_k: dest)
    hit = await DesktopSession().screenshot(
        "left", find="2.22", reader=lambda _p: "wait problem 2.22 here"
    )
    assert hit.ok
    assert "2.22" in hit.output
    assert "Found" in hit.output
    miss = await DesktopSession().screenshot(
        "left", find="2.22", reader=lambda _p: "chapter header"
    )
    assert miss.ok
    assert "Could not resolve: 2.22" in miss.output


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="HWND grab")
def test_grab_window_writes_real_pixels(tmp_path) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel

    from arelis.desktop.pixels import grab_window, list_screens

    app = QApplication.instance() or QApplication([])
    primary = next((s for s in list_screens() if s.primary), None)
    label = QLabel("problem 2.22")
    label.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    label.setWindowFlag(Qt.WindowType.Tool, True)
    label.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
    label.resize(240, 80)
    if primary is not None:
        label.move(primary.x + 16, primary.y + 16)
    label.show()
    app.processEvents()
    dest = tmp_path / "qt-look.png"
    path = grab_window(int(label.winId()), dest)
    label.close()
    assert path == dest
    assert dest.is_file()
    assert dest.stat().st_size > 80


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="live desk")
def test_list_screens_matches_this_desk() -> None:
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from arelis.desktop.pixels import list_screens

    _app = QApplication.instance() or QApplication([])
    assert _app is not None
    qt_n = len(QGuiApplication.screens() or [])
    rows = list_screens()
    assert len(rows) == qt_n
    assert qt_n >= 1
    devices = [r.device for r in rows if r.device]
    assert len(devices) == len(set(devices)), devices
    if qt_n >= 3:
        assert {r.side for r in rows} >= {"left", "center", "right"}


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="live desk")
def test_silent_grab_each_connected_screen(tmp_path) -> None:
    """Observe every monitor. No widgets, no focus, no SendInput."""
    from PIL import Image
    from PySide6.QtWidgets import QApplication

    from arelis.desktop.pixels import grab_screen, list_screens

    _app = QApplication.instance() or QApplication([])
    assert _app is not None
    rows = list_screens()
    assert rows
    for row in rows:
        dest = tmp_path / f"silent-{row.index}-{row.side}.png"
        path = grab_screen(dest, target=str(row.index), screens=rows)
        assert path == dest, row
        assert dest.is_file() and dest.stat().st_size > 200, row
        expect_w = max(1, round(row.width * (row.dpr or 1.0)))
        expect_h = max(1, round(row.height * (row.dpr or 1.0)))
        with Image.open(dest) as im:
            assert abs(im.size[0] - expect_w) <= 2, (row, im.size)
            assert abs(im.size[1] - expect_h) <= 2, (row, im.size)


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="live desk")
def test_grab_window_on_middle_and_right_only(tmp_path) -> None:
    """HWND grab on the monitors they opened. Left stays clear for Reality."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel

    from arelis.desktop.pixels import (
        grab_window,
        list_screens,
        monitor_device_for_hwnd,
        resolve_screen,
        screen_for_window,
    )

    app = QApplication.instance() or QApplication([])
    rows = list_screens()
    middle = resolve_screen("middle", rows)
    right = resolve_screen("right", rows)
    if middle is None:
        middle = next((s for s in rows if s.primary), rows[0])
    allowed = [s for s in (middle, right) if s is not None]
    seen: set[int] = set()
    unique: list = []
    for row in allowed:
        if row.side == "left" or row.index in seen:
            continue
        seen.add(row.index)
        unique.append(row)
    assert unique, rows
    for row in unique:
        token = f"ARELIS-LOOK-{row.side.upper()}-{row.index}"
        label = QLabel(token)
        label.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        label.setWindowFlag(Qt.WindowType.Tool, True)
        label.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
        label.resize(360, 96)
        label.show()
        label.move(row.x + 48, row.y + 48)
        app.processEvents()
        hwnd = int(label.winId())
        owned = screen_for_window(hwnd, rows)
        device = monitor_device_for_hwnd(hwnd)
        dest = tmp_path / f"hwnd-{row.side}-{row.index}.png"
        path = grab_window(hwnd, dest, screens=rows)
        label.close()
        app.processEvents()
        assert path == dest, row
        assert dest.is_file() and dest.stat().st_size > 80, row
        assert owned is not None, row
        assert owned.index == row.index, (row, owned)
        if row.device and device:
            assert device.lower() == row.device.lower(), (row, device)
