"""Browser walls, your-turn pauses, operator mouse, and click timeout."""

from __future__ import annotations

import asyncio

from arelis.browser.session import BrowserSession


def test_x_login_redirect_to_home_is_not_a_wall() -> None:
    from arelis.browser.hold import is_paused, set_paused

    session = BrowserSession.fake()
    session._driver.redirects["https://x.com/login"] = "https://x.com/home"  # type: ignore[attr-defined]
    set_paused(False)
    try:

        async def _run() -> None:
            await session.ensure("chrome")
            opened = await session.open_url("https://x.com/login")
            assert opened.ok
            assert opened.data.get("url") == "https://x.com/home"
            assert opened.data.get("wall") is None
            assert "Already signed in" in opened.output
            assert not is_paused()

        asyncio.run(_run())
    finally:
        set_paused(False)


def test_mouse_does_not_steal_her_window() -> None:
    """Her Chrome stays hers during a drive. Stop / Pause is the strip."""
    from arelis.browser.hold import set_paused

    session = BrowserSession.fake()
    set_paused(False)
    try:

        async def _run() -> None:
            await session.ensure("chrome")
            session._driver.user_took_over = True  # type: ignore[attr-defined]
            result = await session.click("e1")
            assert result.ok
            assert result.data.get("wall") != "hands"
            assert "e1" in getattr(session._driver, "clicked", [])

        asyncio.run(_run())
    finally:
        set_paused(False)


def test_click_timeout_is_not_cdp_death() -> None:
    from arelis.browser.actions import _is_cdp_dead

    assert not _is_cdp_dead(TimeoutError("Timeout 10000ms exceeded."))
    assert not _is_cdp_dead(RuntimeError("element is not stable"))
    assert _is_cdp_dead(RuntimeError("Target closed"))
    assert _is_cdp_dead(RuntimeError("Browser has been closed"))


def test_your_turn_refuses_pay_click() -> None:
    from arelis.browser.hold import set_paused

    session = BrowserSession.fake()
    set_paused(False)
    try:

        async def _run() -> None:
            await session.ensure("chrome")
            result = await session.click("e5")
            assert not result.ok
            assert result.data.get("code") == "YOUR_TURN"
            assert result.data.get("wall") == "pay"
            assert "e5" not in getattr(session._driver, "clicked", [])

        asyncio.run(_run())
    finally:
        set_paused(False)


def test_normalize_press_key_supports_chords_and_function_keys() -> None:
    """Browser press action supports modifier chords (Ctrl+A, Shift+Tab) and F-keys."""
    from arelis.browser.actions import normalize_press_key

    assert normalize_press_key("enter") == "Enter"
    assert normalize_press_key("delete") == "Delete"
    assert normalize_press_key("f5") == "F5"
    assert normalize_press_key("ctrl+a") == "Control+a"
    assert normalize_press_key("Control+Enter") == "Control+Enter"
    assert normalize_press_key("shift+tab") == "Shift+Tab"
    assert normalize_press_key("ctrl+shift+k") == "Control+Shift+k"
    assert normalize_press_key("unknown+key") is None


def test_playwright_driver_resolves_iframe_locators_and_adopts_new_popup_tabs() -> None:
    """Cross-frame stamped refs resolve to the iframe locator; popups become the active page."""
    from arelis.browser.actions import ElementInfo, PlaywrightDriver

    class _FakeLocator:
        def __init__(self, count_val: int, label: str) -> None:
            self._count = count_val
            self.label = label
            self.clicked = 0
            self.filled: list[str] = []

        @property
        def first(self) -> _FakeLocator:
            return self

        async def count(self) -> int:
            return self._count

        async def click(self, **_kwargs: object) -> None:
            self.clicked += 1

        async def fill(self, text: str, **_kwargs: object) -> None:
            self.filled.append(text)

    class _FakeFrame:
        def __init__(self, loc: _FakeLocator) -> None:
            self._loc = loc

        def locator(self, _sel: str) -> _FakeLocator:
            return self._loc

    class _FakePage:
        def __init__(
            self,
            url: str,
            main_loc: _FakeLocator,
            frames: list[_FakeFrame],
            on_click_spawn: _FakePage | None = None,
            context: _FakeContext | None = None,
        ) -> None:
            self.url = url
            self._main_loc = main_loc
            self.main_frame = frames[0] if frames else None
            self.frames = frames
            self._spawn = on_click_spawn
            self._context = context
            self.fronted = False

        def set_default_timeout(self, _ms: int) -> None:
            return None

        def set_default_navigation_timeout(self, _ms: int) -> None:
            return None

        def locator(self, _sel: str) -> _FakeLocator:
            if self._spawn is not None and self._context is not None:
                orig_click = self._main_loc.click

                async def _click_and_spawn(**kw: object) -> None:
                    await orig_click(**kw)
                    if self._spawn not in self._context.pages:
                        self._context.pages.append(self._spawn)

                self._main_loc.click = _click_and_spawn  # type: ignore[method-assign]
            return self._main_loc

        async def bring_to_front(self) -> None:
            self.fronted = True

    class _FakeContext:
        def __init__(self, pages: list[_FakePage]) -> None:
            self.pages = pages

    main_loc = _FakeLocator(0, "main")
    iframe_loc = _FakeLocator(1, "iframe")
    f_main = _FakeFrame(main_loc)
    f_sub = _FakeFrame(iframe_loc)

    popup_loc = _FakeLocator(1, "popup")
    popup_page = _FakePage("https://example.com/popup", popup_loc, [])
    ctx = _FakeContext([])
    page = _FakePage(
        "https://example.com/start",
        _FakeLocator(1, "main_btn"),
        [f_main, f_sub],
        on_click_spawn=popup_page,
        context=ctx,
    )
    ctx.pages.append(page)

    driver = PlaywrightDriver()
    driver._context = ctx
    driver._page = page
    driver._refs = {
        "e1": ElementInfo(ref="e1", tag="button", text="In Frame"),
        "e2": ElementInfo(ref="e2", tag="a", text="Open Popup"),
    }

    async def _run() -> None:
        # 1. Cross-frame resolution: when main_loc has count 0, resolves to f_sub's locator
        page_no_main = _FakePage("https://example.com/frame", main_loc, [f_main, f_sub])
        driver._page = page_no_main
        resolved = await driver._resolve_locator("e1")
        assert resolved is iframe_loc

        # 2. Clicking a link that opens a new tab adopts the popup page automatically
        driver._page = page
        res = await driver.click("e2")
        assert res.ok
        assert driver._page is popup_page
        assert popup_page.fronted
        assert res.data.get("url") == "https://example.com/popup"

    asyncio.run(_run())


def test_custom_combobox_is_recognized_as_select_target() -> None:
    """ARIA role=combobox and role=listbox are selectable via browser(action=select)."""
    from arelis.browser.actions import ElementInfo
    from arelis.browser.session import BrowserSession

    session = BrowserSession.fake()
    session._driver._elements["e99"] = ElementInfo(  # type: ignore[attr-defined]
        ref="e99",
        tag="div",
        role="combobox",
        name="sort_by",
        text="Sort by",
    )

    async def _run() -> None:
        await session.ensure("chrome")
        res = await session.select_option("", "Newest", into="Sort by")
        assert res.ok
        assert ("e99", "Newest") in session._driver.selected  # type: ignore[attr-defined]

    asyncio.run(_run())


def test_browser_element_state_badges_and_trailing_newline_submit_and_dialog_guard() -> None:
    """ElementInfo formats state=; trailing newline submits; dialog guard dismisses alerts."""
    from arelis.browser.actions import ElementInfo, PlaywrightDriver
    from arelis.browser.session import BrowserSession

    el = ElementInfo(
        ref="e42",
        tag="input",
        role="switch",
        type="checkbox",
        text="Dark mode",
        state="checked",
    )
    assert "state=checked" in el.line()

    session = BrowserSession.fake()

    async def _run() -> None:
        await session.ensure("chrome")
        # Trailing newline in type_text triggers Enter + post-submit snapshot
        typed = await session.type_text("e2", "astrophysics\n")
        assert typed.ok
        assert typed.data.get("submitted") is True
        assert typed.data.get("snapshot") is True
        assert ("e2", "astrophysics") in session._driver.typed  # type: ignore[attr-defined]
        assert "Enter" in session._driver.pressed  # type: ignore[attr-defined]
        assert "elements:" in typed.output

        # Direct press("Enter") also returns a post-press snapshot
        pressed = await session.press("Enter")
        assert pressed.ok
        assert pressed.data.get("snapshot") is True
        assert "elements:" in pressed.output

        # Native JS dialog handler auto-dismisses alert and records _last_dialog
        driver = PlaywrightDriver()
        handlers: dict[str, object] = {}

        class _DialogPage:
            def on(self, event: str, fn: object) -> None:
                handlers[event] = fn

        class _FakeDialog:
            def __init__(self, dtype: str, message: str) -> None:
                self.type = dtype
                self.message = message
                self.dismissed = False
                self.accepted = False

            async def dismiss(self) -> None:
                self.dismissed = True

            async def accept(self) -> None:
                self.accepted = True

        dpage = _DialogPage()
        driver._bind_dialog_guard(dpage)
        assert "dialog" in handlers
        alert = _FakeDialog("alert", "Session expiring soon")
        await handlers["dialog"](alert)  # type: ignore[operator]
        assert alert.dismissed
        assert driver._last_dialog == "alert: Session expiring soon"

        unload = _FakeDialog("beforeunload", "Leave site?")
        await handlers["dialog"](unload)  # type: ignore[operator]
        assert unload.accepted

    asyncio.run(_run())




