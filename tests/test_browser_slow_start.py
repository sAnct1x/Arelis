"""Chrome debug port can flap at launch; wait instead of killing the turn."""

from __future__ import annotations

import asyncio
import socket
import sys
import threading
import time
import types
from typing import Any

from arelis.browser.actions import ActionResult, PlaywrightDriver
from arelis.browser.session import BrowserSession
from arelis.tools.browser_tool import BrowserTool

_REFUSED = (
    "BrowserType.connect_over_cdp: connect ECONNREFUSED 127.0.0.1:9222 "
    "retrieving websocket url from http://127.0.0.1:9222"
)
_TIMEOUT_MSG = "The browser took too long to open. Try again in a moment."


class _FakePage:
    url = "https://example.com"


class _FakeContext:
    def __init__(self) -> None:
        self.pages = [_FakePage()]

    async def new_page(self) -> _FakePage:
        return _FakePage()


class _FakeBrowser:
    def __init__(self) -> None:
        self.contexts = [_FakeContext()]

    async def new_context(self) -> _FakeContext:
        return _FakeContext()

    async def close(self) -> None:
        return None


class _FakeChromium:
    def __init__(self, connect: Any) -> None:
        self._connect = connect

    async def connect_over_cdp(self, url: str) -> Any:
        return await self._connect(url)


class _FakePW:
    def __init__(self, connect: Any, stops: list[int]) -> None:
        self.chromium = _FakeChromium(connect)
        self._stops = stops

    async def stop(self) -> None:
        self._stops.append(1)


class _FakeAsyncPlaywright:
    def __init__(self, pw: _FakePW) -> None:
        self._pw = pw

    async def start(self) -> _FakePW:
        return self._pw


def _patch_launch(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from arelis.browser import launch as launch_mod

    monkeypatch.setattr(launch_mod, "playwright_available", lambda: True)
    monkeypatch.setattr(launch_mod, "prefer_cdp_url", lambda url: url)
    monkeypatch.setattr(launch_mod, "cdp_is_up", lambda _u, **_k: False)
    monkeypatch.setattr(launch_mod, "profile_appears_locked", lambda _b: False)
    monkeypatch.setattr(launch_mod, "wait_for_cdp", lambda *_a, **_k: True)
    monkeypatch.setattr(launch_mod, "launch_chromium_cdp", lambda *_a, **_k: object())
    monkeypatch.setattr(launch_mod, "pin_browsers_path", lambda: None)
    monkeypatch.setattr(launch_mod, "terminate_browser_processes", lambda _b: None)


def _patch_playwright(monkeypatch, connect: Any, stops: list[int]) -> _FakePW:
    pw = _FakePW(connect, stops)
    fake_pkg = types.ModuleType("playwright")
    fake_api = types.ModuleType("playwright.async_api")
    fake_api.async_playwright = lambda: _FakeAsyncPlaywright(pw)
    fake_pkg.async_api = fake_api
    monkeypatch.setitem(sys.modules, "playwright", fake_pkg)
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_api)
    return pw


def _stub_driver(driver: PlaywrightDriver) -> None:
    async def _pick(*, prefer_url: str = "") -> Any:
        del prefer_url
        return _FakePage()

    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    driver._pick_page = _pick  # type: ignore[method-assign]
    driver._install_hands = _noop  # type: ignore[method-assign]
    driver._present_window = _noop  # type: ignore[method-assign]


def _fake_clock(monkeypatch) -> list[float]:  # type: ignore[no-untyped-def]
    """Real budget and backoff, but sleeps only move a fake clock."""
    import arelis.browser.actions as actions_mod

    now = [0.0]
    sleeps: list[float] = []

    async def _sleep(secs: float) -> None:
        sleeps.append(secs)
        now[0] += secs

    monkeypatch.setattr(
        actions_mod, "time", types.SimpleNamespace(monotonic=lambda: now[0])
    )
    monkeypatch.setattr(actions_mod.asyncio, "sleep", _sleep)
    return sleeps


def test_tool_read_survives_cdp_refused(monkeypatch) -> None:
    _patch_launch(monkeypatch)
    sleeps = _fake_clock(monkeypatch)
    stops: list[int] = []

    async def _connect(_url: str) -> Any:
        raise Exception(_REFUSED)

    _patch_playwright(monkeypatch, _connect, stops)
    driver = PlaywrightDriver()
    _stub_driver(driver)
    tool = BrowserTool(BrowserSession(driver=driver))

    async def _run() -> None:
        got = await tool.run(action="read")
        assert got.ok is False
        assert got.data.get("code") == "CDP_TIMEOUT"
        assert got.output == _TIMEOUT_MSG
        # It waited the full budget before giving up.
        assert abs(sum(sleeps) - 18.0) < 1e-9

    asyncio.run(_run())


def test_late_listener_connects_on_fourth_try(monkeypatch) -> None:
    _patch_launch(monkeypatch)
    sleeps = _fake_clock(monkeypatch)
    stops: list[int] = []
    calls = {"n": 0}
    fake = _FakeBrowser()

    async def _connect(_url: str) -> Any:
        calls["n"] += 1
        if calls["n"] <= 3:
            raise Exception(_REFUSED)
        return fake

    _patch_playwright(monkeypatch, _connect, stops)
    driver = PlaywrightDriver()
    _stub_driver(driver)

    async def _run() -> None:
        got = await driver.ensure("chrome")
        assert got.ok is True
        assert calls["n"] == 4
        assert sleeps == [0.25, 0.5, 1.0]
        assert driver._browser is fake

    asyncio.run(_run())


def test_give_up_is_plain_and_closes_playwright(monkeypatch) -> None:
    _patch_launch(monkeypatch)
    sleeps = _fake_clock(monkeypatch)
    stops: list[int] = []

    async def _connect(_url: str) -> Any:
        raise Exception(_REFUSED)

    _patch_playwright(monkeypatch, _connect, stops)
    driver = PlaywrightDriver()
    _stub_driver(driver)

    async def _run() -> None:
        got = await driver._attach_cdp(mode="launch")
        assert got.ok is False
        assert got.data.get("code") == "CDP_TIMEOUT"
        assert got.data.get("reason") == "connect_refused"
        assert got.data.get("mode") == "launch"
        assert got.output == _TIMEOUT_MSG
        lowered = got.output.lower()
        for junk in ("9222", "127.0.0.1", "cdp", "econnrefused", "http"):
            assert junk not in lowered
        assert driver._browser is None
        assert stops
        # Backoff doubles up to the cap and stops at the 18 s budget.
        assert sleeps[:5] == [0.25, 0.5, 1.0, 2.0, 2.0]
        assert abs(sum(sleeps) - 18.0) < 1e-9

    asyncio.run(_run())


def test_retry_picks_up_late_tcp_listener(monkeypatch) -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.settimeout(3.0)
    port = int(listener.getsockname()[1])
    done = threading.Event()

    def _listen() -> None:
        time.sleep(0.05)
        try:
            listener.listen(1)
            conn, _addr = listener.accept()
            conn.close()
        except OSError:
            pass
        finally:
            done.set()

    thread = threading.Thread(target=_listen, daemon=True)
    thread.start()
    try:
        import arelis.browser.actions as actions_mod

        monkeypatch.setattr(actions_mod, "_CDP_CONNECT_BUDGET_S", 1.5)
        monkeypatch.setattr(actions_mod, "_CDP_CONNECT_BACKOFF_S", 0.02)
        monkeypatch.setattr(actions_mod, "_CDP_CONNECT_BACKOFF_CAP_S", 0.05)
        _patch_launch(monkeypatch)
        stops: list[int] = []
        fake = _FakeBrowser()

        async def _connect(_url: str) -> Any:
            try:
                sock = socket.create_connection(("127.0.0.1", port), timeout=0.08)
            except OSError as exc:
                raise Exception(_REFUSED) from exc
            sock.close()
            return fake

        _patch_playwright(monkeypatch, _connect, stops)
        driver = PlaywrightDriver()
        _stub_driver(driver)

        async def _run() -> None:
            got = await driver._attach_cdp(mode="launch")
            assert got.ok is True
            assert driver._browser is fake

        asyncio.run(_run())
    finally:
        try:
            listener.close()
        except OSError:
            pass
        done.wait(timeout=1.0)
        thread.join(timeout=1.0)


def test_open_falls_back_to_os_on_cdp_timeout(monkeypatch) -> None:
    _patch_launch(monkeypatch)
    _fake_clock(monkeypatch)
    stops: list[int] = []

    async def _connect(_url: str) -> Any:
        raise Exception(_REFUSED)

    _patch_playwright(monkeypatch, _connect, stops)
    driver = PlaywrightDriver()
    _stub_driver(driver)
    session = BrowserSession(driver=driver)

    async def _os_open(_url: str, _browser: str | None = None) -> ActionResult:
        return ActionResult(ok=True, output="Opened.", data={"mode": "os_open"})

    monkeypatch.setattr(session, "open_url_os", _os_open)
    tool = BrowserTool(session)

    async def _run() -> None:
        got = await tool.run(action="open", target="https://example.com")
        assert got.ok is True
        assert got.data.get("mode") == "os_open"
        assert got.data.get("code") == "CDP_TIMEOUT"

    asyncio.run(_run())
