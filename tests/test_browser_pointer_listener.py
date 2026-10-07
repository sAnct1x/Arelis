"""Opening or attaching her browser must not listen for the mouse.

The pointer counter used to be injected into every page on launch and on
attach. Nothing reads it. Her window stays hers.
"""

from __future__ import annotations

import asyncio
import re
import sys
import types
from typing import Any

from arelis.browser.actions import PlaywrightDriver

# An init script (or an immediate evaluate) that registers a pointer listener.
_POINTER_LISTENER = re.compile(
    r"""addEventListener\s*\(\s*['"]pointer|onpointerdown\s*=""",
    re.IGNORECASE,
)


class _Page:
    def __init__(self, context: _Context) -> None:
        self.context = context
        self.url = "https://example.com/"

    async def evaluate(self, script: str, *args: Any) -> Any:
        del args
        self.context.planted.append(("evaluate", str(script)))
        return None


class _Cdp:
    async def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        del params
        if method == "Browser.getWindowForTarget":
            return {"windowId": 1}
        return {}


class _Context:
    def __init__(self, planted: list[tuple[str, str]]) -> None:
        self.planted = planted
        self.pages = [_Page(self)]

    async def add_init_script(self, script: str) -> None:
        self.planted.append(("init", script))

    async def new_page(self) -> _Page:
        page = _Page(self)
        self.pages.append(page)
        return page

    async def new_cdp_session(self, page: _Page) -> _Cdp:
        del page
        return _Cdp()


class _Browser:
    def __init__(self, planted: list[tuple[str, str]]) -> None:
        self.contexts = [_Context(planted)]

    async def new_context(self) -> _Context:
        ctx = _Context(self.contexts[0].planted)
        self.contexts.append(ctx)
        return ctx

    async def close(self) -> None:
        return None


class _Chromium:
    def __init__(self, planted: list[tuple[str, str]]) -> None:
        self._planted = planted

    async def connect_over_cdp(self, url: str) -> _Browser:
        del url
        return _Browser(self._planted)


class _Firefox:
    def __init__(self, planted: list[tuple[str, str]]) -> None:
        self._planted = planted

    async def launch_persistent_context(self, **kwargs: Any) -> _Context:
        del kwargs
        return _Context(self._planted)


class _Playwright:
    def __init__(self, planted: list[tuple[str, str]]) -> None:
        self.chromium = _Chromium(planted)
        self.firefox = _Firefox(planted)

    async def stop(self) -> None:
        return None


class _Starter:
    def __init__(self, pw: _Playwright) -> None:
        self._pw = pw

    async def start(self) -> _Playwright:
        return self._pw


def _mock_playwright(monkeypatch: Any, planted: list[tuple[str, str]]) -> None:
    """Replace Playwright at the import the driver uses, not inside the driver."""
    pw = _Playwright(planted)
    fake_pkg = types.ModuleType("playwright")
    fake_api = types.ModuleType("playwright.async_api")
    fake_api.async_playwright = lambda: _Starter(pw)
    fake_pkg.async_api = fake_api
    monkeypatch.setitem(sys.modules, "playwright", fake_pkg)
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_api)


def _patch_launch(monkeypatch: Any, *, cdp_up: bool) -> dict[str, bool]:
    from arelis.browser import launch as launch_mod

    state = {"up": cdp_up}
    monkeypatch.setattr(launch_mod, "playwright_available", lambda: True)
    monkeypatch.setattr(launch_mod, "prefer_cdp_url", lambda url: url)
    monkeypatch.setattr(launch_mod, "cdp_is_up", lambda _u, **_k: state["up"])
    monkeypatch.setattr(launch_mod, "profile_appears_locked", lambda _b: False)
    monkeypatch.setattr(launch_mod, "wait_for_cdp", lambda *_a, **_k: True)
    monkeypatch.setattr(launch_mod, "launch_chromium_cdp", lambda *_a, **_k: object())
    monkeypatch.setattr(launch_mod, "pin_browsers_path", lambda: None)
    monkeypatch.setattr(launch_mod, "terminate_browser_processes", lambda _b: None)
    return state


def _assert_no_pointer_listener(planted: list[tuple[str, str]], where: str) -> None:
    listeners = [(kind, script) for kind, script in planted if _POINTER_LISTENER.search(script)]
    assert not listeners, (
        f"{where} injected a pointer listener into the page via {listeners[0][0]}:\n"
        f"{listeners[0][1]}"
    )


def test_launch_and_attach_inject_no_pointer_listener(monkeypatch: Any) -> None:
    planted: list[tuple[str, str]] = []
    _mock_playwright(monkeypatch, planted)
    state = _patch_launch(monkeypatch, cdp_up=False)

    async def _run() -> None:
        launched = PlaywrightDriver()
        opened = await launched.ensure("chrome")
        assert opened.ok is True, opened.output
        assert opened.data.get("mode") == "launch"
        _assert_no_pointer_listener(planted, "launch")

        planted.clear()
        state["up"] = True
        again = await launched.ensure("chrome")
        assert again.ok is True, again.output
        assert again.data.get("mode") == "attach"
        _assert_no_pointer_listener(planted, "attach")

        planted.clear()
        fresh = PlaywrightDriver()
        attached = await fresh.ensure("chrome")
        assert attached.ok is True, attached.output
        assert attached.data.get("mode") == "attach"
        _assert_no_pointer_listener(planted, "attach to a browser that is already open")

        planted.clear()
        fox = PlaywrightDriver()
        firefox = await fox.ensure("firefox")
        assert firefox.ok is True, firefox.output
        _assert_no_pointer_listener(planted, "firefox launch")

    asyncio.run(_run())
