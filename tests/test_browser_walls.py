"""Browser walls, your-turn pauses, operator mouse, and click timeout."""

from __future__ import annotations

import asyncio

from arelis.browser.session import BrowserSession


def test_login_redirect_is_already_signed_in() -> None:
    from arelis.browser.walls import (
        is_login_url,
        login_redirected_signed_in,
        nav_landed_note,
        site_login_url,
    )

    assert site_login_url("https://x.com/home") == "https://x.com/login"
    assert site_login_url("https://example.com") is None
    assert is_login_url("https://x.com/login")
    assert is_login_url("https://x.com/i/flow/login")
    assert not is_login_url("https://x.com/home")
    assert login_redirected_signed_in("https://x.com/login", "https://x.com/home")
    assert not login_redirected_signed_in("https://x.com/home", "https://x.com/home")
    assert not login_redirected_signed_in("https://x.com/login", "https://x.com/login")
    note = nav_landed_note("https://x.com/login", "https://x.com/home")
    assert "Already signed in" in note
    assert nav_landed_note("https://x.com/home", "https://x.com/home") == ""


def test_detect_wall_kinds() -> None:
    from arelis.browser.walls import detect_wall, pay_cta_label

    assert detect_wall(signals={"recaptcha": True}).kind == "captcha"
    assert detect_wall(url="https://accounts.google.com/signin").kind == "login"
    assert detect_wall(url="https://x.com/i/jf/onboarding/web?mode=login").kind == "login"
    assert detect_wall(url="https://x.com/i/flow/login").kind == "login"
    assert detect_wall(
        url="https://x.com/i/jf/onboarding/web#/s/signup_phone/r-auy0ku"
    ).kind == "login"
    assert detect_wall(url="https://x.com/home") is None
    assert detect_wall(url="https://shop.example/checkout").kind == "pay"
    assert detect_wall(url="https://www.youtube.com", signals={"password": True}) is None
    assert pay_cta_label("Pay") == "Pay"
    assert pay_cta_label("Book now") == "Book now"
    assert pay_cta_label("Checkout") == "Checkout"
    assert pay_cta_label("Proceed to checkout") == "Proceed to checkout"
    assert pay_cta_label("Add to cart") is None
    assert pay_cta_label("Add to bag") is None
    assert pay_cta_label("Home") is None
    assert pay_cta_label("Confirm reservation") == "Confirm reservation"
    assert pay_cta_label("Complete reservation") == "Complete reservation"


def test_your_turn_on_x_onboarding_login() -> None:
    from arelis.browser.hold import is_paused, set_paused

    session = BrowserSession.fake()
    set_paused(False)
    try:

        async def _run() -> None:
            await session.ensure("chrome")
            opened = await session.open_url(
                "https://x.com/i/jf/onboarding/web?mode=login"
            )
            assert opened.ok
            assert opened.data.get("code") == "YOUR_TURN"
            assert opened.data.get("wall") == "login"
            assert is_paused()

        asyncio.run(_run())
    finally:
        set_paused(False)


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


def test_operator_mouse_pauses_drive() -> None:
    from arelis.browser.hold import is_paused, set_paused
    from arelis.browser.walls import your_turn_status

    session = BrowserSession.fake()
    set_paused(False)
    try:

        async def _run() -> None:
            await session.ensure("chrome")
            session._driver.user_took_over = True  # type: ignore[attr-defined]
            result = await session.click("e1")
            assert result.data.get("code") == "YOUR_TURN"
            assert result.data.get("wall") == "hands"
            assert is_paused()
            assert "e1" not in getattr(session._driver, "clicked", [])
            assert "mouse" in your_turn_status("hands")

        asyncio.run(_run())
    finally:
        set_paused(False)


def test_click_timeout_is_not_cdp_death() -> None:
    from arelis.browser.actions import _is_cdp_dead

    assert not _is_cdp_dead(TimeoutError("Timeout 10000ms exceeded."))
    assert not _is_cdp_dead(RuntimeError("element is not stable"))
    assert _is_cdp_dead(RuntimeError("Target closed"))
    assert _is_cdp_dead(RuntimeError("Browser has been closed"))


def test_your_turn_on_login_url() -> None:
    from arelis.browser.hold import set_paused

    session = BrowserSession.fake()
    set_paused(False)
    try:

        async def _run() -> None:
            await session.ensure("chrome")
            opened = await session.open_url("https://accounts.google.com/signin")
            assert opened.ok
            assert opened.data.get("code") == "YOUR_TURN"
            assert opened.data.get("wall") == "login"
            assert "your turn" in opened.output.lower()

        asyncio.run(_run())
    finally:
        set_paused(False)


def test_checkout_receipt_is_short() -> None:
    from arelis.browser.walls import checkout_receipt

    line = checkout_receipt(
        url="https://shop.example/checkout",
        title="Checkout",
        heading="Checkout",
        body="title: Checkout\nurl: https://shop.example/checkout\n\nTotal $12.00",
    )
    assert line.startswith("Checkout is up — your turn to click Pay.")
    assert "https://shop.example/checkout" in line
    assert "Total $12.00" in line
    assert line.count("\n") <= 4


def test_pay_checkout_receipt_reads_once() -> None:
    from types import SimpleNamespace

    from arelis.core.turn_context import TurnContext
    from arelis.core.turn_execute import _pay_checkout_receipt

    session = BrowserSession.fake()

    async def _run() -> None:
        await session.ensure("chrome")
        await session.open_url("https://shop.example/checkout")
        session._driver.title = "Checkout"  # type: ignore[attr-defined]
        session._driver.heading = "Pay now"  # type: ignore[attr-defined]
        session._driver.page_text = "Total $12.00"  # type: ignore[attr-defined]
        loop = SimpleNamespace(tools=SimpleNamespace(get=lambda _n: SimpleNamespace(session=session)))
        ctx = TurnContext(text="checkout", role="hot")
        line = await _pay_checkout_receipt(
            loop, ctx, {"url": "https://shop.example/checkout"}
        )
        assert "your turn to click Pay" in line
        assert "Pay now" in line or "Checkout" in line

    asyncio.run(_run())


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


def test_your_turn_captcha_then_clears() -> None:
    from arelis.browser.hold import is_paused, set_paused

    session = BrowserSession.fake()
    driver = session._driver
    driver.simulate_wall = {"recaptcha": True}  # type: ignore[attr-defined]
    set_paused(False)
    try:

        async def _run() -> None:
            await session.ensure("chrome")
            snap = await session.snapshot()
            assert snap.data.get("wall") == "captcha"
            assert is_paused()
            driver.simulate_wall = {}  # type: ignore[attr-defined]
            assert await session.probe_wall() is None

        asyncio.run(_run())
    finally:
        set_paused(False)


def test_your_turn_after_two_missed_clicks() -> None:
    from arelis.browser.hold import set_paused

    session = BrowserSession.fake()
    set_paused(False)
    try:

        async def _run() -> None:
            await session.ensure("chrome")
            first = await session.click("e99")
            assert not first.ok
            assert first.data.get("code") != "YOUR_TURN"
            second = await session.click("e99")
            assert not second.ok
            assert second.data.get("code") == "YOUR_TURN"
            assert second.data.get("wall") == "stuck"

        asyncio.run(_run())
    finally:
        set_paused(False)

