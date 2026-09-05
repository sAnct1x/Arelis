"""Browser control: aliases, launch, profile, screenshot, confirm (no live Chrome)."""

from __future__ import annotations

import asyncio
from typing import Any

from arelis.browser.aliases import resolve_target
from arelis.browser.launch import resolve_browser_choice
from arelis.browser.session import BrowserSession
from arelis.core.preflight import detect_intents
from arelis.tools.base import ToolRegistry, capability_class
from arelis.tools.browser_tool import BrowserTool


def test_resolve_alias_youtube() -> None:
    url, err = resolve_target("youtube")
    assert err is None
    assert url == "https://www.youtube.com"
    maps, maps_err = resolve_target("maps")
    assert maps_err is None
    assert maps == "https://www.google.com/maps"
    ot, ot_err = resolve_target("opentable")
    assert ot_err is None
    assert "opentable.com" in (ot or "")
    url2, err2 = resolve_target("https://www.youtube.com/watch?v=1")
    assert err2 is None
    assert url2 and url2.startswith("https://")


def test_resolve_rejects_non_http() -> None:
    url, err = resolve_target("file:///C:/secret.txt")
    assert url is None
    assert err and "http" in err.lower()


def test_resolve_browser_choice_named() -> None:
    assert resolve_browser_choice("chrome") == "chrome"
    assert resolve_browser_choice("edge") == "edge"
    assert resolve_browser_choice("firefox") == "firefox"
    assert resolve_browser_choice("default") in {"chrome", "edge", "firefox"}


def test_launch_uses_arelis_profile_not_daily_chrome(monkeypatch, tmp_path) -> None:
    from arelis.browser import launch as launch_mod

    calls: list[list[str]] = []

    class _Proc:
        pid = 4242

        def poll(self):
            return None

    def _fake_popen(args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(args))
        return _Proc()

    monkeypatch.setattr(launch_mod, "arelis_user_data_dir", lambda: tmp_path / "browser-profile")
    monkeypatch.setattr(launch_mod, "chrome_executable", lambda: r"C:\Chrome\chrome.exe")
    monkeypatch.setattr(launch_mod.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(launch_mod, "profile_has_sign_in", lambda _p=None: False)
    launch_mod.set_arelis_anchor(100, 80, 1200, 800, screen=(0, 0, 3840, 1080))
    proc = launch_mod.launch_chromium_cdp("chrome", cdp_url="http://127.0.0.1:9222")
    assert proc is not None
    assert calls
    argv = calls[0]
    joined = " ".join(argv)
    assert "--user-data-dir=" in joined
    assert "browser-profile" in joined
    assert "Google\\Chrome\\User Data" not in joined
    assert "--new-window" in argv
    want_w, want_h = launch_mod._desk_window_size(3840, 1080)
    assert any(a == f"--window-size={want_w},{want_h}" for a in argv)
    # Beside Arelis (100+1200+16), not stacked on it.
    assert "--window-position=1316,80" in argv


def test_terminate_never_kills_all_chrome(monkeypatch) -> None:
    from arelis.browser import launch as launch_mod

    runs: list[list[str]] = []

    def _fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
        runs.append(list(args))

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(launch_mod, "_pids_using_arelis_profile", lambda: [99])
    monkeypatch.setattr(launch_mod, "_last_arelis_proc", None)
    monkeypatch.setattr(launch_mod.subprocess, "run", _fake_run)
    monkeypatch.setattr(launch_mod.time, "sleep", lambda _s: None)
    launch_mod.terminate_browser_processes("chrome")
    assert runs
    assert all("/IM" not in a for run in runs for a in run)
    assert any("/PID" in run for run in runs)


def test_first_run_note_uses_marker_not_preferences(tmp_path) -> None:
    from arelis.browser.launch import first_run_note, mark_intro_shown

    prefs = tmp_path / "Default" / "Preferences"
    prefs.parent.mkdir(parents=True)
    prefs.write_text("{}", encoding="utf-8")
    note = first_run_note(tmp_path)
    assert "Arelis' Chrome" in note
    assert "daily" in note.lower()
    mark_intro_shown(tmp_path)
    assert first_run_note(tmp_path) == ""


def test_same_open_url_treats_slash_as_same() -> None:
    from arelis.browser.actions import _same_open_url

    assert _same_open_url("https://x.com/", "https://x.com")
    assert not _same_open_url("about:blank", "https://x.com")
    assert not _same_open_url("https://x.com/", "https://youtube.com")
    assert not _same_open_url(
        "https://www.youtube.com/",
        "https://www.youtube.com/results?search_query=interferometry",
    )
    assert not _same_open_url(
        "https://www.youtube.com/results?search_query=interferometry",
        "https://www.youtube.com/",
    )
    assert _same_open_url(
        "https://www.youtube.com/results?search_query=interferometry",
        "https://www.youtube.com/results?search_query=interferometry",
    )


def test_window_placement_sits_beside_not_on_top() -> None:
    from arelis.browser import launch as launch_mod

    launch_mod.set_arelis_anchor(100, 80, 1200, 800, screen=(0, 0, 3840, 1080))
    x, y, w, h = launch_mod.window_placement()
    assert (w, h) == launch_mod._desk_window_size(3840, 1080)
    assert x == 1316
    assert y == 80
    launch_mod.set_arelis_anchor(2000, 80, 1200, 800, screen=(0, 0, 2560, 1080))
    x2, _y2, w2, h2 = launch_mod.window_placement()
    assert (w2, h2) == launch_mod._desk_window_size(2560, 1080)
    assert x2 == 2000 - 16 - w2


def test_window_placement_stays_on_one_desk() -> None:
    """A 3-span HWND is not a browser size. Chrome is ~60% of one monitor."""
    from arelis.browser import launch as launch_mod

    launch_mod.set_arelis_anchor(0, 0, 7680, 1440, screen=(2560, 0, 2560, 1440))
    x, y, w, h = launch_mod.window_placement()
    assert (w, h) == launch_mod._desk_window_size(2560, 1440)
    assert w < 2000
    assert h < 1000
    assert 2560 <= x < 5120
    assert x + w <= 5120
    assert 0 <= y < 1440
    assert y + h <= 1440


def test_open_url_in_browser_launches_exe(monkeypatch) -> None:
    from arelis.browser import launch as launch_mod

    calls: list[list[str]] = []

    class _Proc:
        pass

    def _fake_popen(args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(args))
        return _Proc()

    monkeypatch.setattr(launch_mod.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(launch_mod, "chrome_executable", lambda: r"C:\Chrome\chrome.exe")
    ok, msg, data = launch_mod.open_url_in_browser(
        "https://www.youtube.com", "chrome"
    )
    assert ok
    assert data["mode"] == "os_open"
    assert "youtube.com" in msg
    assert calls and calls[0][0].endswith("chrome.exe")
    # Chrome/Edge open with --new-window so the tab is not buried.
    assert calls[0][1:] == ["--new-window", "https://www.youtube.com"]


def test_playwright_fail_maps_cdp_dead() -> None:
    from arelis.browser.actions import _playwright_fail

    dead = _playwright_fail(RuntimeError("Target closed"))
    assert not dead.ok
    assert dead.data.get("code") == "CDP_DEAD"
    assert "relaunch" in dead.output.lower()
    other = _playwright_fail(RuntimeError("something else odd"))
    assert other.data.get("code") == "BROWSER_ERROR"


def test_password_field_rejected() -> None:
    from arelis.browser.hold import set_paused

    session = BrowserSession.fake()
    set_paused(False)
    try:

        async def _run() -> None:
            await session.ensure("chrome")
            bad = await session.type_text("e3", "hunter2")
            assert not bad.ok
            assert bad.data.get("code") == "SECRET_FIELD"
            assert bad.data.get("wall") == "login"
            good = await session.type_text("e2", "peanut live")
            assert good.ok

        asyncio.run(_run())
    finally:
        set_paused(False)


def test_open_falls_back_to_os_when_playwright_missing() -> None:
    session = BrowserSession.fake()
    tool = BrowserTool(session)

    async def _no_pw(*_args: Any, **_kwargs: Any) -> Any:
        from arelis.browser.actions import ActionResult

        return ActionResult(
            ok=False,
            output="Playwright is not installed.",
            data={"code": "NO_PLAYWRIGHT"},
        )

    session.ensure = _no_pw  # type: ignore[method-assign]

    async def _run() -> None:
        opened = await tool.run(action="open", url="https://example.com")
        assert opened.ok
        assert opened.data.get("mode") == "os_open"
        assert "example.com" in (opened.output or "").lower()
        snap = await tool.run(action="snapshot")
        assert not snap.ok
        assert snap.data.get("code") == "NO_PLAYWRIGHT"

    asyncio.run(_run())


def test_fake_open_snapshot_click() -> None:
    session = BrowserSession.fake()
    tool = BrowserTool(session)

    async def _run() -> None:
        opened = await tool.run(action="open", url="youtube")
        assert opened.ok
        assert "youtube.com" in opened.output.lower()
        assert opened.data.get("mode") != "os_open"
        # Driving the page still uses CDP-style ensure + snapshot.
        snap = await tool.run(action="snapshot")
        assert snap.ok
        assert "elements:" in snap.output.lower() or "[e1]" in snap.output
        clicked = await tool.run(action="click", ref="e1")
        assert clicked.ok
        tabs = await tool.run(action="tabs")
        assert tabs.ok

    asyncio.run(_run())


def test_profile_locked_open_relaunches_her_chrome_only() -> None:
    """Open lands in Arelis Chrome. A wedged her-window may relaunch — not daily Chrome."""
    session = BrowserSession.fake()
    driver = session._driver
    assert hasattr(driver, "simulate_locked")
    driver.simulate_locked = True  # type: ignore[attr-defined]
    tool = BrowserTool(session)

    async def _run() -> None:
        opened = await tool.run(action="open", url="youtube")
        assert opened.ok
        assert driver.relaunch_count == 1  # type: ignore[attr-defined]
        assert "youtube.com" in (driver.url or "")  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_relaunch_with_url_opens_after_restart() -> None:
    session = BrowserSession.fake()
    driver = session._driver
    assert hasattr(driver, "simulate_locked")
    driver.simulate_locked = True  # type: ignore[attr-defined]
    tool = BrowserTool(session)

    async def _run() -> None:
        result = await tool.run(action="relaunch", url="youtube")
        assert result.ok
        assert driver.relaunch_count == 1  # type: ignore[attr-defined]
        assert "youtube.com" in (driver.url or "")  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_profile_locked_screenshot_writes_no_file(tmp_path, monkeypatch) -> None:
    from arelis.config import PROJECT_ROOT

    images = PROJECT_ROOT / "outputs" / "images"
    before = set(images.glob("browser_*.png")) if images.is_dir() else set()
    session = BrowserSession.fake()
    driver = session._driver
    driver.simulate_locked = True  # type: ignore[attr-defined]
    tool = BrowserTool(session)

    async def _run() -> None:
        shot = await tool.run(action="screenshot")
        assert not shot.ok
        assert shot.data.get("code") == "PROFILE_LOCKED"
        assert "no image file" in shot.output.lower()

    asyncio.run(_run())
    after = set(images.glob("browser_*.png")) if images.is_dir() else set()
    assert after == before


def test_browser_needs_confirm_separate_from_image() -> None:
    reg = ToolRegistry()
    reg.register(BrowserTool(BrowserSession.fake()))

    class Img:
        name = "image"
        description = "img"
        risk = "side_effect"
        parameters_schema: dict[str, Any] = {"type": "object", "properties": {}}

        async def run(self, **kwargs: Any) -> Any:
            from arelis.tools.base import ToolResult

            return ToolResult(ok=True, output="ok")

    reg.register(Img())
    assert reg.needs_confirm("browser", {"action": "open", "url": "youtube"})
    assert not reg.needs_confirm(
        "browser",
        {"action": "open", "url": "youtube"},
        confirm_browser=False,
    )
    # Turning off image confirm must not disable browser.
    assert reg.needs_confirm(
        "browser",
        {"action": "open", "url": "youtube"},
        confirm_image=False,
    )
    assert capability_class("browser", {"action": "open"}) == "SIDE_EFFECT_LOCAL"


def test_browser_preflight_take_me_to() -> None:
    hints = detect_intents("take me to x.com")
    assert any(h.kind == "browser" for h in hints)


def test_browser_preflight_pull_up() -> None:
    hints = detect_intents("Hey Arelis, pull up YouTube")
    assert any(h.kind == "browser" for h in hints)
    browser = next(h for h in hints if h.kind == "browser")
    assert browser.expected_tools == ("browser",)
    assert "browser" in browser.nudge.lower()


def test_fake_screenshot_then_path() -> None:
    session = BrowserSession.fake()
    tool = BrowserTool(session)

    async def _run() -> None:
        await tool.run(action="open", url="youtube")
        shot = await tool.run(action="screenshot")
        assert shot.ok
        path = str(shot.data.get("path") or "")
        assert path.startswith("outputs/images/browser_")
        assert path.endswith(".png")
        assert "vision" in shot.output.lower()
        # The reported path is relative, and relative to the data root rather than to the
        # program. Those are the same directory in a checkout, which is why resolving it
        # against the repository used to work; an installed Arelis writes screenshots under
        # the user's data and could not write them beside the executable if it wanted to.
        from arelis.paths import user_data_dir

        full = (user_data_dir() / path).resolve()
        assert full.is_file()
        assert full.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    asyncio.run(_run())


def test_browser_screenshot_preflight() -> None:
    hints = detect_intents("Screenshot this page and tell me what you see")
    assert any(h.kind == "browser_vision" for h in hints)
    hint = next(h for h in hints if h.kind == "browser_vision")
    assert hint.expected_tools == ("browser", "vision")
    assert "screenshot" in hint.nudge.lower()
    # Plain describe-this-screenshot stays vision-only (local file ask).
    vision_only = detect_intents("Describe this screenshot please")
    assert any(h.kind == "vision" for h in vision_only)
    assert not any(h.kind == "browser_vision" for h in vision_only)


def test_describe_browser_relaunch() -> None:
    reg = ToolRegistry()
    reg.register(BrowserTool(BrowserSession.fake()))
    text = reg.describe_call("browser", {"action": "relaunch", "browser": "chrome"})
    assert "relaunch" in text.lower()
    assert "restart" in text.lower()
    shot = reg.describe_call("browser", {"action": "screenshot", "full_page": True})
    assert "screenshot" in shot.lower()
    assert "vision" in shot.lower()
    assert "full page" in shot.lower()
    click = reg.describe_call("browser", {"action": "click", "ref": "e1"})
    assert "glow" in click.lower()
    read = reg.describe_call("browser", {"action": "read"})
    assert "compact" in read.lower()
    assert "scrape" in read.lower()
    maps = reg.describe_call(
        "browser", {"action": "maps", "destination": "Midway airport"}
    )
    assert "maps" in maps.lower()
    assert "Midway" in maps
    assert "phone" in maps.lower()
    search = reg.describe_call(
        "browser",
        {"action": "search", "query": "never gonna", "site": "youtube"},
    )
    assert "never gonna" in search
    assert "youtube" in search.lower()
    reserve = reg.describe_call(
        "browser",
        {
            "action": "reserve",
            "place": "The Inn",
            "party": 2,
            "time": "7pm",
        },
    )
    assert "Inn" in reserve
    assert "Book" in reserve


def test_prefer_cdp_skips_foreign_port(monkeypatch) -> None:
    from arelis.browser import launch as launch_mod

    def _up(url: str, *, timeout_s: float = 0.8) -> bool:
        del timeout_s
        return "9222" in url

    monkeypatch.setattr(launch_mod, "cdp_is_up", _up)
    monkeypatch.setattr(launch_mod, "cdp_port_is_arelis", lambda _url: False)
    assert launch_mod.prefer_cdp_url("http://127.0.0.1:9222") == (
        "http://127.0.0.1:9333"
    )
    monkeypatch.setattr(launch_mod, "cdp_port_is_arelis", lambda _url: True)
    assert launch_mod.prefer_cdp_url("http://127.0.0.1:9222") == (
        "http://127.0.0.1:9222"
    )


def test_empty_process_scan_keeps_preferred_port(monkeypatch) -> None:
    from arelis.browser import launch as launch_mod

    monkeypatch.setattr(launch_mod.sys, "platform", "win32")
    monkeypatch.setattr(launch_mod, "_chrome_cmdlines", lambda: [])
    monkeypatch.setattr(launch_mod, "cdp_is_up", lambda _url, **_k: True)
    assert launch_mod.cdp_port_is_arelis("http://127.0.0.1:9222") is None
    assert launch_mod.prefer_cdp_url("http://127.0.0.1:9222") == (
        "http://127.0.0.1:9222"
    )


def test_ensure_keeps_attached_cdp_url(monkeypatch) -> None:
    from arelis.browser import launch as launch_mod
    from arelis.browser.actions import ActionResult, PlaywrightDriver

    hops: list[str] = []

    def _prefer(url: str) -> str:
        hops.append(url)
        return "http://127.0.0.1:9333"

    monkeypatch.setattr(launch_mod, "prefer_cdp_url", _prefer)
    monkeypatch.setattr(launch_mod, "cdp_is_up", lambda _url, **_k: True)
    monkeypatch.setattr(launch_mod, "playwright_available", lambda: True)

    driver = PlaywrightDriver(cdp_url="http://127.0.0.1:9222")
    driver._browser = object()
    driver._page = object()

    async def _attach(*, mode: str) -> ActionResult:
        return ActionResult(
            ok=True,
            output=f"Connected ({mode}).",
            data={"mode": mode, "cdp": driver.cdp_url},
        )

    driver._attach_cdp = _attach  # type: ignore[method-assign]

    async def _run() -> None:
        got = await driver.ensure("chrome")
        assert got.ok
        assert driver.cdp_url == "http://127.0.0.1:9222"
        assert hops == []

    asyncio.run(_run())

