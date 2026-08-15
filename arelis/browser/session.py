"""One BrowserSession per Arelis process — attach, launch, or relaunch."""

from __future__ import annotations

from typing import Any

from arelis.browser.actions import (
    ActionResult,
    BrowserDriver,
    FakeDriver,
    PlaywrightDriver,
)
from arelis.browser.launch import playwright_available, resolve_browser_choice
from arelis.browser.walls import Wall, attach_wall, detect_wall, wall_message

__all__ = ["BrowserSession", "playwright_available"]


class BrowserSession:
    """Facade over a BrowserDriver (Playwright or Fake)."""

    def __init__(
        self,
        *,
        cdp_url: str = "http://127.0.0.1:9222",
        driver: BrowserDriver | None = None,
        max_snapshot_chars: int = 6000,
        max_read_chars: int = 3500,
    ) -> None:
        self.cdp_url = cdp_url
        self.max_snapshot_chars = max_snapshot_chars
        self.max_read_chars = max_read_chars
        self._driver: BrowserDriver = driver or PlaywrightDriver(cdp_url=cdp_url)
        self.last_mode: str = ""
        self.last_browser: str = ""
        self._click_misses = 0

    @classmethod
    def fake(cls, **kwargs: Any) -> BrowserSession:
        return cls(driver=FakeDriver(), **kwargs)

    async def ensure(
        self,
        browser: str | None = None,
        *,
        private: bool = False,
        relaunch: bool = False,
    ) -> ActionResult:
        name = resolve_browser_choice(browser)
        # Firefox private is the only private path we honor.
        use_private = bool(private) and name == "firefox"
        result = await self._driver.ensure(
            name, private=use_private, relaunch=relaunch
        )
        if result.ok:
            self.last_browser = name
            self.last_mode = str((result.data or {}).get("mode") or "")
        return result

    async def open_url(self, url: str) -> ActionResult:
        return await self._with_wall(await self._driver.open_url(url))

    async def open_url_os(self, url: str, browser: str | None = None) -> ActionResult:
        """Open URL like a normal browser click — no CDP attach or restart."""
        name = resolve_browser_choice(browser)
        result = await self._driver.open_url_os(url, name)
        if result.ok:
            self.last_browser = name
            self.last_mode = str((result.data or {}).get("mode") or "os_open")
        return result

    async def navigate(self, url: str) -> ActionResult:
        return await self._with_wall(await self._driver.navigate(url))

    async def snapshot(self) -> ActionResult:
        return await self._with_wall(
            await self._driver.snapshot(max_chars=self.max_snapshot_chars)
        )

    async def read(self) -> ActionResult:
        return await self._with_wall(
            await self._driver.read(max_chars=self.max_read_chars)
        )

    async def click(self, ref: str) -> ActionResult:
        result = await self._driver.click(ref)
        if not result.ok and "Unknown ref" in (result.output or ""):
            self._click_misses += 1
            if self._click_misses >= 2:
                return attach_wall(
                    ActionResult(
                        ok=False,
                        output=result.output,
                        data=dict(result.data or {}),
                    ),
                    Wall("stuck", "miss", wall_message("stuck")),
                    ok=False,
                )
            return result
        self._click_misses = 0
        if str((result.data or {}).get("code") or "") == "YOUR_TURN":
            return result
        label = str((result.data or {}).get("label") or "")
        return await self._with_wall(result, click_label=label)

    async def type_text(self, ref: str, text: str) -> ActionResult:
        result = await self._driver.type_text(ref, text)
        if str((result.data or {}).get("code") or "") == "SECRET_FIELD":
            from arelis.browser.hold import set_paused

            set_paused(True)
            data = dict(result.data or {})
            data["wall"] = "login"
            return ActionResult(
                ok=False,
                output=f"{result.output.rstrip()}\n\n{wall_message('login')}",
                data=data,
            )
        return result

    async def tabs(self, *, select: int | None = None) -> ActionResult:
        return await self._driver.tabs(select=select)

    async def screenshot(
        self, path: str, *, full_page: bool = False
    ) -> ActionResult:
        return await self._driver.screenshot(path, full_page=full_page)

    async def scroll(
        self,
        *,
        direction: str = "down",
        amount: int = 600,
        ref: str = "",
    ) -> ActionResult:
        return await self._driver.scroll(
            direction=direction, amount=amount, ref=ref
        )

    async def press(self, key: str) -> ActionResult:
        return await self._driver.press(key)

    async def select_option(self, ref: str, value: str) -> ActionResult:
        return await self._driver.select_option(ref, value)

    async def wait(self, seconds: float) -> ActionResult:
        return await self._driver.wait(seconds)

    async def close(self) -> None:
        closer = getattr(self._driver, "close", None)
        if callable(closer):
            await closer()

    async def probe_wall(self, *, click_label: str = "") -> Wall | None:
        signals: dict[str, Any] = {}
        probe = getattr(self._driver, "probe_wall_signals", None)
        if callable(probe):
            try:
                raw = await probe()
                if isinstance(raw, dict):
                    signals = raw
            except Exception:
                signals = {}
        return detect_wall(
            url=str(signals.get("url") or getattr(self._driver, "url", "") or ""),
            title=str(signals.get("title") or getattr(self._driver, "title", "") or ""),
            heading=str(signals.get("heading") or ""),
            signals=signals,
            click_label=click_label,
        )

    async def _with_wall(
        self, result: ActionResult, *, click_label: str = ""
    ) -> ActionResult:
        if not result.ok:
            return result
        if str((result.data or {}).get("code") or "") == "YOUR_TURN":
            return result
        wall = await self.probe_wall(click_label=click_label)
        if wall is None:
            return result
        return attach_wall(result, wall)
