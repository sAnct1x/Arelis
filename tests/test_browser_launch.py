"""Browser control: aliases, launch, profile, screenshot, confirm (no live Chrome)."""

from __future__ import annotations

import asyncio
from typing import Any

from arelis.browser.session import BrowserSession
from arelis.tools.base import ToolRegistry, capability_class
from arelis.tools.browser_tool import BrowserTool


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


def _fake_chrome(monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    from arelis.browser import launch as launch_mod

    calls: list[list[str]] = []

    class _Proc:
        pid = 1

        def poll(self):
            return None

    profile = tmp_path / "browser-profile"
    (profile / "Default").mkdir(parents=True)
    (profile / "Default" / "Preferences").write_text("{}", encoding="utf-8")
    (profile / "Default" / "Cookies").write_text("session", encoding="utf-8")
    monkeypatch.setattr(launch_mod, "arelis_user_data_dir", lambda: profile)
    monkeypatch.setattr(launch_mod, "chrome_executable", lambda: "chrome")
    monkeypatch.setattr(
        launch_mod.subprocess, "Popen", lambda args, **_k: calls.append(list(args)) or _Proc()
    )
    monkeypatch.setattr(launch_mod, "_last_arelis_proc", None)
    monkeypatch.setattr(launch_mod, "_owned_browser_launched", False)
    return launch_mod, profile, calls


def test_persistent_profile_is_opt_in(monkeypatch, tmp_path) -> None:
    launch_mod, profile, calls = _fake_chrome(monkeypatch, tmp_path)
    launch_mod.launch_chromium_cdp("chrome", cdp_url="http://127.0.0.1:9222", fresh_profile=False)
    argv = calls[0]
    assert "--restore-last-session" in argv
    assert "https://www.google.com" not in argv
    assert (profile / "Default" / "Cookies").exists()


def _driver_launch_kwargs(monkeypatch, *, fresh_profile: bool | None = None):  # type: ignore[no-untyped-def]
    from arelis.browser import launch as launch_mod
    from arelis.browser.actions import ActionResult, PlaywrightDriver

    seen: list[dict[str, Any]] = []

    def _launch(_browser, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(kwargs)
        return object()

    monkeypatch.setattr(launch_mod, "playwright_available", lambda: True)
    monkeypatch.setattr(launch_mod, "prefer_cdp_url", lambda url: url)
    monkeypatch.setattr(launch_mod, "cdp_is_up", lambda _u, **_k: False)
    monkeypatch.setattr(launch_mod, "profile_appears_locked", lambda _b: False)
    monkeypatch.setattr(launch_mod, "wait_for_cdp", lambda *_a, **_k: True)
    monkeypatch.setattr(launch_mod, "terminate_browser_processes", lambda _b: None)
    monkeypatch.setattr(launch_mod, "launch_chromium_cdp", _launch)
    driver = (
        PlaywrightDriver()
        if fresh_profile is None
        else PlaywrightDriver(fresh_profile=fresh_profile)
    )

    async def _attach(*, mode: str) -> ActionResult:
        return ActionResult(ok=True, output=mode)

    async def _close() -> None:
        return None

    driver._attach_cdp = _attach  # type: ignore[method-assign]
    driver._close_pw = _close  # type: ignore[method-assign]
    return driver, seen


def test_open_adds_sign_in_note_only_when_profile_is_kept(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    session = BrowserSession.fake()
    session._driver.fresh_profile = False  # type: ignore[attr-defined]
    tool = BrowserTool(session)

    async def _run() -> None:
        first = await tool.run(action="open", url="https://example.com")
        assert first.ok
        assert "Opened https://example.com" in (first.output or "")
        assert "Sign into Google and Maps" not in (first.output or "")
        assert "Sign into Google and Maps" in str((first.data or {}).get("intro") or "")
        second = await tool.run(action="open", url="https://example.com/next")
        assert second.ok
        assert "Sign into Google and Maps" not in (second.output or "")
        assert not str((second.data or {}).get("intro") or "")

    asyncio.run(_run())

    wiped = BrowserSession.fake()
    wiped._driver.fresh_profile = True  # type: ignore[attr-defined]
    fresh_tool = BrowserTool(wiped)

    async def _fresh() -> None:
        opened = await fresh_tool.run(action="open", url="https://example.com")
        assert opened.ok
        assert "Sign into Google and Maps" not in (opened.output or "")

    asyncio.run(_fresh())


