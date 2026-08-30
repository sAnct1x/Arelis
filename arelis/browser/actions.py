"""Page actions + fake driver for offline tests."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from arelis.browser.hold import cooperative_wait

log = logging.getLogger(__name__)

# Input types we refuse to fill — never handle credentials.
_SECRET_INPUT_TYPES = frozenset(
    {
        "password",
        "otp",
        "tel-otp",
        "one-time-code",
    }
)
_SECRET_AUTOCOMPLETE = re.compile(
    r"(?i)(current-password|new-password|one-time-code|otp|cc-number|cc-csc)"
)


@dataclass
class ElementInfo:
    ref: str
    tag: str
    role: str = ""
    type: str = ""
    name: str = ""
    text: str = ""
    href: str = ""
    autocomplete: str = ""

    def is_secret_field(self) -> bool:
        if self.type.lower() in _SECRET_INPUT_TYPES:
            return True
        if _SECRET_AUTOCOMPLETE.search(self.autocomplete or ""):
            return True
        if self.name.lower() in {"password", "passwd", "otp", "totp"}:
            return True
        return False

    def line(self) -> str:
        bits = [f"[{self.ref}]", self.tag]
        if self.role:
            bits.append(f"role={self.role}")
        if self.type:
            bits.append(f"type={self.type}")
        if self.text:
            bits.append(repr(self.text[:60]))
        if self.href:
            bits.append(self.href[:80])
        return " ".join(bits)


@dataclass
class ActionResult:
    ok: bool
    output: str
    data: dict[str, Any] = field(default_factory=dict)


class BrowserDriver(Protocol):
    async def ensure(
        self,
        browser: str,
        *,
        private: bool = False,
        relaunch: bool = False,
    ) -> ActionResult: ...

    async def open_url(self, url: str) -> ActionResult: ...

    async def open_url_os(self, url: str, browser: str = "chrome") -> ActionResult: ...

    async def navigate(self, url: str) -> ActionResult: ...

    async def snapshot(self, *, max_chars: int = 6000) -> ActionResult: ...

    async def read(self, *, max_chars: int = 3500) -> ActionResult: ...

    async def click(self, ref: str) -> ActionResult: ...

    async def type_text(self, ref: str, text: str) -> ActionResult: ...

    async def tabs(self, *, select: int | None = None) -> ActionResult: ...

    async def screenshot(
        self, path: str, *, full_page: bool = False
    ) -> ActionResult: ...

    async def scroll(
        self,
        *,
        direction: str = "down",
        amount: int = 600,
        ref: str = "",
    ) -> ActionResult: ...

    async def press(self, key: str) -> ActionResult: ...

    async def select_option(self, ref: str, value: str) -> ActionResult: ...

    async def wait(self, seconds: float) -> ActionResult: ...

    async def close(self) -> None: ...


# Minimal valid 1x1 PNG for FakeDriver (no Pillow dependency).
_FAKE_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _same_open_url(current: str, wanted: str) -> bool:
    """True when the tab is already on this open target (ignore trailing slash).

    A results URL is not the site home: youtube.com must not count as already
    being /results?search_query=…, and opening youtube.com while already on
    /results must navigate.
    """
    a = (current or "").strip().lower()
    b = (wanted or "").strip().lower()
    if not a or not b:
        return False
    if a.startswith("chrome://") or a.startswith("about:"):
        return False
    a_base, _, a_q = a.partition("?")
    b_base, _, b_q = b.partition("?")
    a_base = a_base.rstrip("/")
    b_base = b_base.rstrip("/")
    if b_q:
        return a_base == b_base and a_q == b_q
    return a_base == b_base


# Glow beat before click. Tests set this to 0.
GLOW_S = 0.4

_PRESS_KEYS = {
    "enter": "Enter",
    "return": "Enter",
    "escape": "Escape",
    "esc": "Escape",
    "tab": "Tab",
    "space": "Space",
    "backspace": "Backspace",
    "arrowup": "ArrowUp",
    "up": "ArrowUp",
    "arrowdown": "ArrowDown",
    "down": "ArrowDown",
    "arrowleft": "ArrowLeft",
    "left": "ArrowLeft",
    "arrowright": "ArrowRight",
    "right": "ArrowRight",
    "home": "Home",
    "end": "End",
    "pageup": "PageUp",
    "pagedown": "PageDown",
}


def compact_visible_text(raw: str) -> str:
    """Collapse noisy innerText into short readable lines."""
    lines: list[str] = []
    for line in (raw or "").splitlines():
        line = " ".join(line.split())
        if line:
            lines.append(line)
    return "\n".join(lines)


def format_tab_read(
    *,
    title: str,
    url: str,
    heading: str = "",
    body: str = "",
    max_chars: int = 3500,
) -> str:
    """Compact title / url / heading / body for the model (not a scrape dump)."""
    bits = [f"title: {(title or '').strip()}", f"url: {(url or '').strip()}"]
    head = (heading or "").strip()
    if head:
        bits.append(f"heading: {head[:160]}")
    bits.append("")
    bits.append(compact_visible_text(body))
    text = "\n".join(bits).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 22] + "\n…(tab text truncated)"
    return text


def normalize_press_key(key: str) -> str | None:
    raw = (key or "").strip()
    if not raw:
        return None
    mapped = _PRESS_KEYS.get(raw.lower())
    if mapped:
        return mapped
    if raw in set(_PRESS_KEYS.values()):
        return raw
    return None


async def _glow_ref(page: Any, ref: str) -> bool:
    """Outline the target in-page (not the OS mouse), then wait a beat."""
    try:
        ok = await page.evaluate(
            """(ref) => {
              const el = document.querySelector('[data-arelis-ref="' + ref + '"]');
              if (!el) return false;
              el.scrollIntoView({block: 'center', inline: 'nearest'});
              el.style.setProperty('outline', '3px solid #5ad4ff', 'important');
              el.style.setProperty('outline-offset', '2px', 'important');
              return true;
            }""",
            ref,
        )
    except Exception:
        return False
    if ok and GLOW_S > 0:
        await cooperative_wait(GLOW_S)
    return bool(ok)


async def _page_heading(page: Any) -> str:
    try:
        text = await page.evaluate(
            """() => ((document.querySelector('h1') || {}).innerText || '')
              .trim().slice(0, 120)"""
        )
    except Exception:
        return ""
    return str(text or "").strip()


def _playwright_fail(exc: BaseException) -> ActionResult:
    """Map a mid-turn Playwright/CDP crash to a stable tool result (not a turn kill)."""
    msg = str(exc).strip() or type(exc).__name__
    lowered = msg.lower()
    dead = any(
        tip in lowered
        for tip in (
            "target closed",
            "target crashed",
            "connection closed",
            "browser has been closed",
            "browser closed",
            "disconnected",
            "protocol error",
            "websocket",
            "cdp",
        )
    )
    code = "CDP_DEAD" if dead else "BROWSER_ERROR"
    tip = (
        "Call browser(action=relaunch, url=…) after Allow, or close extra Chrome "
        "windows and retry. Prefer browser(action=open) when you only need to "
        "show a page (no restart). Do not invent page contents."
        if dead
        else "Retry once, or use browser(action=open) for a plain OS open."
    )
    return ActionResult(
        ok=False,
        output=f"[fail:browser] Browser control failed ({msg}). {tip}",
        data={"code": code},
    )


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _write_bytes_sync(path: str, data: bytes) -> str:
    _ensure_parent_dir(path)
    with open(path, "wb") as fh:
        fh.write(data)
    return os.path.abspath(path)


def _file_size_sync(path: str) -> int:
    return os.path.getsize(path) if os.path.isfile(path) else 0


class FakeDriver:
    """In-memory driver for unit tests and foundation scenarios."""

    def __init__(self) -> None:
        self.browser = "chrome"
        self.private = False
        self.url = "about:blank"
        self.title = "New Tab"
        self.connected = False
        self.mode = "fake"
        self.relaunch_count = 0
        self.typed: list[tuple[str, str]] = []
        self.clicked: list[str] = []
        self._elements: dict[str, ElementInfo] = {
            "e1": ElementInfo(
                ref="e1",
                tag="a",
                role="link",
                text="Home",
                href="https://www.youtube.com/",
            ),
            "e2": ElementInfo(
                ref="e2",
                tag="input",
                role="textbox",
                type="search",
                text="",
                name="search_query",
            ),
            "e3": ElementInfo(
                ref="e3",
                tag="input",
                type="password",
                name="password",
                autocomplete="current-password",
            ),
            "e4": ElementInfo(
                ref="e4",
                tag="select",
                role="combobox",
                name="party_size",
                text="2",
            ),
            "e5": ElementInfo(
                ref="e5",
                tag="button",
                role="button",
                text="Pay",
            ),
            "e11": ElementInfo(
                ref="e11",
                tag="button",
                role="button",
                text="Sign in",
            ),
            "e24": ElementInfo(
                ref="e24",
                tag="button",
                role="button",
                text="Sign in to like videos, comment, and subscribe",
            ),
        }
        # Optional extra signals for tests: {"recaptcha": True} etc.
        self.simulate_wall: dict[str, Any] = {}
        self.scrolled: list[str] = []
        self.pressed: list[str] = []
        self.selected: list[tuple[str, str]] = []
        self.waited: list[float] = []
        self.glowed: list[str] = []
        self._tabs: list[dict[str, str]] = [
            {"index": "0", "title": "New Tab", "url": "about:blank"},
        ]
        self._active = 0
        # When True, ensure() reports PROFILE_LOCKED unless relaunch=True.
        self.simulate_locked = False
        self.heading = ""
        self.page_text = "Home\nSearch\nArelis test page. Welcome to the fake tab."

    async def ensure(
        self,
        browser: str,
        *,
        private: bool = False,
        relaunch: bool = False,
    ) -> ActionResult:
        if self.simulate_locked and not relaunch and not self.connected:
            label = str(browser).capitalize()
            return ActionResult(
                ok=False,
                output=(
                    f"{label} profile in use — already open without debugging. "
                    "open/navigate will restart with control after Allow, then "
                    f"open the URL. Or close {label} / Allow relaunch. "
                    "Do not screenshot until connected."
                ),
                data={"code": "PROFILE_LOCKED", "browser": browser},
            )
        if relaunch:
            self.relaunch_count += 1
            self.simulate_locked = False
        self.browser = browser
        self.private = private
        self.connected = True
        self.mode = "relaunch" if relaunch else "attach"
        return ActionResult(
            ok=True,
            output=f"Connected to {browser} ({self.mode}"
            + (", private" if private else "")
            + ").",
            data={"browser": browser, "mode": self.mode, "private": private},
        )

    async def open_url_os(self, url: str, browser: str = "chrome") -> ActionResult:
        """Plain open for tests — no lock / relaunch path."""
        self.browser = browser
        self.connected = True
        self.mode = "os_open"
        self.url = url
        self.title = url
        self._tabs[self._active] = {
            "index": str(self._active),
            "title": self.title,
            "url": url,
        }
        return ActionResult(
            ok=True,
            output=f"Opened {url} in {browser}.",
            data={"mode": "os_open", "browser": browser, "url": url},
        )

    async def open_url(self, url: str) -> ActionResult:
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        self.url = url
        self.title = url
        self.heading = ""
        self.page_text = f"Opened page at {url}."
        self._tabs[self._active] = {
            "index": str(self._active),
            "title": self.title,
            "url": url,
        }
        return ActionResult(
            ok=True,
            output=f"Opened {url}",
            data={"url": url, "title": self.title},
        )

    async def navigate(self, url: str) -> ActionResult:
        return await self.open_url(url)

    async def snapshot(self, *, max_chars: int = 6000) -> ActionResult:
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        lines = [f"title: {self.title}", f"url: {self.url}", "elements:"]
        for info in self._elements.values():
            lines.append(info.line())
        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[: max_chars - 20] + "\n…(snapshot truncated)"
        return ActionResult(
            ok=True,
            output=text,
            data={
                "url": self.url,
                "title": self.title,
                "refs": list(self._elements),
            },
        )

    async def read(self, *, max_chars: int = 3500) -> ActionResult:
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        text = format_tab_read(
            title=self.title,
            url=self.url,
            heading=self.heading,
            body=self.page_text,
            max_chars=max_chars,
        )
        return ActionResult(
            ok=True,
            output=text,
            data={
                "url": self.url,
                "title": self.title,
                "heading": self.heading,
                "chars": len(text),
                "untrusted": True,
            },
        )

    async def probe_wall_signals(self) -> dict[str, Any]:
        extra = dict(self.simulate_wall or {})
        extra.setdefault("url", self.url)
        extra.setdefault("title", self.title)
        extra.setdefault(
            "password",
            any(info.is_secret_field() for info in self._elements.values()),
        )
        extra.setdefault(
            "card",
            any(
                "cc-" in (info.autocomplete or "").lower()
                or "card" in (info.name or "").lower()
                for info in self._elements.values()
            ),
        )
        return extra

    async def click(self, ref: str) -> ActionResult:
        info = self._elements.get(ref)
        if info is None:
            return ActionResult(ok=False, output=f"Unknown ref {ref!r}. Call snapshot.")
        from arelis.browser.walls import attach_wall, detect_wall

        wall = detect_wall(click_label=info.text or info.name)
        if wall is not None and wall.kind == "pay":
            return attach_wall(
                ActionResult(
                    ok=False,
                    output=f"Stopped before [{ref}] {info.text or info.tag}.",
                    data={"ref": ref, "label": info.text, "url": self.url},
                ),
                wall,
                ok=False,
            )
        self.glowed.append(ref)
        self.clicked.append(ref)
        if info.href:
            self.url = info.href
            self.title = info.text or info.href
        return ActionResult(
            ok=True,
            output=f"Clicked [{ref}] {info.text or info.tag}",
            data={"ref": ref, "url": self.url, "label": info.text},
        )

    async def type_text(self, ref: str, text: str) -> ActionResult:
        info = self._elements.get(ref)
        if info is None:
            return ActionResult(ok=False, output=f"Unknown ref {ref!r}. Call snapshot.")
        if info.is_secret_field():
            return ActionResult(
                ok=False,
                output=(
                    "Refused to type into a password/OTP field. "
                    "Arelis does not enter credentials — sign in yourself."
                ),
                data={"code": "SECRET_FIELD", "ref": ref},
            )
        self.typed.append((ref, text))
        info.text = text
        return ActionResult(
            ok=True,
            output=f"Typed into [{ref}]",
            data={"ref": ref, "length": len(text)},
        )

    async def tabs(self, *, select: int | None = None) -> ActionResult:
        if select is not None:
            if select < 0 or select >= len(self._tabs):
                return ActionResult(ok=False, output=f"No tab index {select}.")
            self._active = select
            tab = self._tabs[select]
            self.url = tab["url"]
            self.title = tab["title"]
            return ActionResult(
                ok=True,
                output=f"Selected tab {select}: {tab['title']}",
                data={"tabs": self._tabs, "active": select},
            )
        lines = [
            f"{t['index']}: {t['title']} — {t['url']}"
            + (" (active)" if i == self._active else "")
            for i, t in enumerate(self._tabs)
        ]
        return ActionResult(
            ok=True,
            output="Tabs:\n" + "\n".join(lines),
            data={"tabs": list(self._tabs), "active": self._active},
        )

    async def screenshot(
        self, path: str, *, full_page: bool = False
    ) -> ActionResult:
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        abs_path = await asyncio.to_thread(_write_bytes_sync, path, _FAKE_PNG)
        return ActionResult(
            ok=True,
            output=f"Screenshot saved ({'full page' if full_page else 'viewport'}).",
            data={
                "path": abs_path,
                "url": self.url,
                "title": self.title,
                "full_page": bool(full_page),
                "bytes": len(_FAKE_PNG),
            },
        )

    async def scroll(
        self,
        *,
        direction: str = "down",
        amount: int = 600,
        ref: str = "",
    ) -> ActionResult:
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        if ref:
            if ref not in self._elements:
                return ActionResult(ok=False, output=f"Unknown ref {ref!r}.")
            self.scrolled.append(f"ref:{ref}")
            return ActionResult(ok=True, output=f"Scrolled [{ref}] into view.")
        way = (direction or "down").strip().lower() or "down"
        self.scrolled.append(f"{way}:{amount}")
        return ActionResult(ok=True, output=f"Scrolled {way} {amount}px.")

    async def press(self, key: str) -> ActionResult:
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        mapped = normalize_press_key(key)
        if not mapped:
            return ActionResult(ok=False, output=f"Unsupported key {key!r}.")
        self.pressed.append(mapped)
        return ActionResult(ok=True, output=f"Pressed {mapped}.")

    async def select_option(self, ref: str, value: str) -> ActionResult:
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        info = self._elements.get(ref)
        if info is None:
            return ActionResult(ok=False, output=f"Unknown ref {ref!r}.")
        if info.tag != "select":
            return ActionResult(ok=False, output=f"[{ref}] is not a dropdown.")
        info.text = value
        self.selected.append((ref, value))
        return ActionResult(ok=True, output=f"Selected {value!r} on [{ref}].")

    async def wait(self, seconds: float) -> ActionResult:
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        self.waited.append(float(seconds))
        return ActionResult(ok=True, output=f"Waited {seconds:.1f}s.")

    async def close(self) -> None:
        self.connected = False


class PlaywrightDriver:
    """Drive a real browser via Playwright CDP or Firefox launch."""

    def __init__(self, *, cdp_url: str = "http://127.0.0.1:9222") -> None:
        self.cdp_url = cdp_url.rstrip("/")
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._refs: dict[str, ElementInfo] = {}
        self._browser_name = "chrome"
        self._private = False
        self._mode = ""

    async def ensure(
        self,
        browser: str,
        *,
        private: bool = False,
        relaunch: bool = False,
    ) -> ActionResult:
        from arelis.browser import launch as launch_mod

        if not launch_mod.playwright_available():
            return ActionResult(
                ok=False,
                output=(
                    "Playwright is not installed. Run: "
                    'pip install -e ".[browser]" && playwright install chromium firefox'
                ),
                data={"code": "NO_PLAYWRIGHT"},
            )

        self._browser_name = browser
        self._private = private

        if browser == "firefox":
            return await self._ensure_firefox(private=private)

        if relaunch:
            launch_mod.terminate_browser_processes(browser)  # type: ignore[arg-type]
            await self._close_pw()
            proc = launch_mod.launch_chromium_cdp(
                browser,  # type: ignore[arg-type]
                cdp_url=self.cdp_url,
                restore_session=True,
            )
            if proc is None:
                return ActionResult(
                    ok=False,
                    output=f"Could not find {browser} executable.",
                    data={"code": "NO_EXECUTABLE"},
                )
            if not launch_mod.wait_for_cdp(self.cdp_url, timeout_s=20.0):
                return ActionResult(
                    ok=False,
                    output=f"Launched {browser} but CDP did not come up on {self.cdp_url}.",
                    data={"code": "CDP_TIMEOUT"},
                )
            return await self._attach_cdp(mode="relaunch")

        if launch_mod.cdp_is_up(self.cdp_url):
            return await self._attach_cdp(mode="attach")

        # Try launch with user profile.
        if launch_mod.profile_appears_locked(browser):  # type: ignore[arg-type]
            return ActionResult(
                ok=False,
                output=(
                    "Arelis Chrome is open but not controllable "
                    f"(CDP down on {self.cdp_url}). Allow relaunch to restart "
                    "HER window only — daily Chrome is left alone. "
                    "Do not screenshot until connected."
                ),
                data={"code": "PROFILE_LOCKED", "browser": browser},
            )

        proc = launch_mod.launch_chromium_cdp(
            browser,  # type: ignore[arg-type]
            cdp_url=self.cdp_url,
            restore_session=True,
        )
        if proc is None:
            return ActionResult(
                ok=False,
                output=f"Could not find {browser} executable.",
                data={"code": "NO_EXECUTABLE"},
            )
        if not launch_mod.wait_for_cdp(self.cdp_url, timeout_s=15.0):
            # Launch may have bounced off a locked profile without our heuristic.
            if launch_mod.profile_appears_locked(browser):  # type: ignore[arg-type]
                return ActionResult(
                    ok=False,
                    output=(
                        "Arelis Chrome is open but not controllable. "
                        "Allow relaunch to restart her window only. "
                        "Daily Chrome is left alone. Do not screenshot until connected."
                    ),
                    data={"code": "PROFILE_LOCKED", "browser": browser},
                )
            return ActionResult(
                ok=False,
                output=f"Launched {browser} but CDP did not come up on {self.cdp_url}.",
                data={"code": "CDP_TIMEOUT"},
            )
        return await self._attach_cdp(mode="launch")

    async def _ensure_firefox(self, *, private: bool) -> ActionResult:
        import tempfile

        from arelis.browser.launch import pin_browsers_path

        # Before the import below: this is the one path that needs a browser
        # Playwright downloaded itself, so it is the one that decides where those
        # land. Chrome and Edge are attached over CDP and need nothing downloaded.
        pin_browsers_path()

        from playwright.async_api import async_playwright

        await self._close_pw()
        self._pw = await async_playwright().start()
        # Ephemeral profile (and private flag) — never the user's Firefox logins.
        tmp = tempfile.mkdtemp(prefix="arelis-firefox-")
        self._context = await self._pw.firefox.launch_persistent_context(
            user_data_dir=tmp,
            headless=False,
        )
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        self._mode = "firefox_private" if private else "firefox"
        return ActionResult(
            ok=True,
            output=f"Launched Firefox ({self._mode}).",
            data={"browser": "firefox", "mode": self._mode, "private": private},
        )

    async def _attach_cdp(self, *, mode: str) -> ActionResult:
        from arelis.browser.launch import pin_browsers_path

        pin_browsers_path()

        from playwright.async_api import async_playwright

        already = self._browser is not None and self._context is not None
        if already:
            # Keep the tab open/navigate just selected. Re-picking after a
            # launch-mode connect used to snap back to the front tab (Gmail).
            if self._page is None:
                self._page = await self._pick_page()
            self._mode = mode
            await self._apply_placement()
            return ActionResult(
                ok=True,
                output=f"Connected to {self._browser_name} ({mode}).",
                data={
                    "browser": self._browser_name,
                    "mode": mode,
                    "private": self._private,
                },
            )

        await self._close_pw()
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.connect_over_cdp(self.cdp_url)
        contexts = self._browser.contexts
        self._context = contexts[0] if contexts else await self._browser.new_context()
        self._page = await self._pick_page()
        self._mode = mode
        await self._apply_placement()
        return ActionResult(
            ok=True,
            output=f"Connected to {self._browser_name} ({mode}).",
            data={
                "browser": self._browser_name,
                "mode": mode,
                "private": self._private,
                "cdp": self.cdp_url,
            },
        )

    async def _apply_placement(self) -> None:
        """Park her Chrome beside Arelis. Launch flags are often ignored once Chrome exists."""
        if self._page is None:
            return
        from arelis.browser.launch import window_placement

        x, y, w, h = window_placement()
        try:
            cdp = await self._page.context.new_cdp_session(self._page)
            info = await cdp.send("Browser.getWindowForTarget")
            await cdp.send(
                "Browser.setWindowBounds",
                {
                    "windowId": info["windowId"],
                    "bounds": {
                        "left": x,
                        "top": y,
                        "width": w,
                        "height": h,
                        "windowState": "normal",
                    },
                },
            )
        except Exception:
            log.debug("could not place Arelis Chrome window", exc_info=True)

    async def _pick_page(self, *, prefer_url: str = "") -> Any:
        """Pick a page under the attached context.

        Multi-window Chrome often leaves several tabs; preferring the last page
        alone attaches to a buried tab. Prefer a URL match when known, else the
        last non-blank / non-chrome:// page, else pages[-1].
        """
        assert self._context is not None
        pages = list(self._context.pages)
        if not pages:
            return await self._context.new_page()

        prefer = (prefer_url or "").strip().lower()
        prefer_host = ""
        if prefer.startswith("http"):
            try:
                from urllib.parse import urlparse

                prefer_host = (urlparse(prefer).netloc or "").lower()
            except Exception:
                prefer_host = ""

        best: Any = pages[-1]
        best_score = -1
        for page in pages:
            try:
                url = str(page.url or "")
            except Exception:
                url = ""
            lowered = url.lower()
            score = 0
            if url and not lowered.startswith(("chrome://", "edge://", "about:blank")):
                score += 2
            if prefer and prefer in lowered:
                score += 10
            if prefer_host and prefer_host in lowered:
                score += 5
            # Stable tie-break: later tabs win when scores equal.
            if score >= best_score:
                best_score = score
                best = page
        return best

    async def _close_pw(self) -> None:
        self._page = None
        self._context = None
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None
        self._refs.clear()

    async def close(self) -> None:
        """Stop the Playwright driver without Browser.close (CDP would quit Chrome)."""
        self._page = None
        self._context = None
        self._browser = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None
        self._refs.clear()

    async def _require_page(self) -> ActionResult | None:
        if self._page is None:
            return ActionResult(
                ok=False,
                output="Browser not connected. Call open or relaunch first.",
                data={"code": "NOT_CONNECTED"},
            )
        return None

    async def open_url_os(self, url: str, browser: str = "chrome") -> ActionResult:
        from arelis.browser import launch as launch_mod

        ok, output, data = launch_mod.open_url_in_browser(url, browser)
        return ActionResult(ok=ok, output=output, data=dict(data))

    async def open_url(self, url: str) -> ActionResult:
        """Show ``url`` in the current tab. Do not spawn a second copy."""
        err = await self._require_page()
        if err:
            return err
        assert self._context is not None
        try:
            page = await self._pick_page(prefer_url=url)
            self._page = page
            current = ""
            try:
                current = str(page.url or "")
            except Exception:
                current = ""
            if not _same_open_url(current, url):
                await page.goto(url, wait_until="domcontentloaded")
            await self._apply_placement()
            title = await page.title()
            heading = await _page_heading(page)
            bits = [f"Opened {page.url}"]
            if title:
                bits.append(f"title: {title}")
            if heading:
                bits.append(f"heading: {heading}")
            return ActionResult(
                ok=True,
                output="\n".join(bits),
                data={"url": page.url, "title": title, "heading": heading},
            )
        except Exception as exc:
            self._page = None
            return _playwright_fail(exc)

    async def navigate(self, url: str) -> ActionResult:
        err = await self._require_page()
        if err:
            return err
        assert self._page is not None
        try:
            await self._page.goto(url, wait_until="domcontentloaded")
            await self._apply_placement()
            title = await self._page.title()
            return ActionResult(
                ok=True,
                output=f"Navigated to {url}",
                data={"url": self._page.url, "title": title},
            )
        except Exception as exc:
            self._page = None
            return _playwright_fail(exc)

    async def probe_wall_signals(self) -> dict[str, Any]:
        err = await self._require_page()
        if err:
            return {}
        assert self._page is not None
        try:
            raw = await self._page.evaluate(
                """() => {
  const text = ((document.body && document.body.innerText) || '').slice(0, 2500);
  return {
    url: location.href,
    title: document.title || '',
    heading: ((document.querySelector('h1') || {}).innerText || '')
      .trim().slice(0, 120),
    recaptcha: !!(document.querySelector(
      'iframe[src*="recaptcha"], .g-recaptcha, [data-sitekey]'
    )),
    hcaptcha: !!(document.querySelector(
      'iframe[src*="hcaptcha"], .h-captcha'
    )),
    turnstile: !!(document.querySelector(
      'iframe[src*="challenges.cloudflare"], .cf-turnstile'
    )),
    password: !!(document.querySelector('input[type="password"]')),
    otp: !!(document.querySelector(
      'input[autocomplete*="one-time"], input[name*="otp"]'
    )),
    card: !!(document.querySelector(
      'input[autocomplete*="cc-"], input[name*="cardnumber"]'
    )),
    text: text,
  };
}"""
            )
        except Exception:
            return {}
        return dict(raw or {}) if isinstance(raw, dict) else {}

    async def snapshot(self, *, max_chars: int = 6000) -> ActionResult:
        err = await self._require_page()
        if err:
            return err
        assert self._page is not None
        try:
            raw = await self._page.evaluate(
                """() => {
  const sel = 'a[href], button, input, textarea, select, '
    + '[role="button"], [role="link"], [role="textbox"], [contenteditable="true"]';
  const nodes = Array.from(document.querySelectorAll(sel)).slice(0, 80);
  const heading = ((document.querySelector('h1') || {}).innerText || '')
    .trim().slice(0, 120);
  return {
    heading: heading,
    nodes: nodes.map((el, i) => {
      const ref = 'e' + (i + 1);
      el.setAttribute('data-arelis-ref', ref);
      const text = (el.innerText || el.value || el.getAttribute('aria-label')
        || el.getAttribute('placeholder') || '').trim().slice(0, 80);
      return {
        ref: ref,
        tag: el.tagName.toLowerCase(),
        role: el.getAttribute('role') || '',
        type: (el.getAttribute('type') || '').toLowerCase(),
        name: el.getAttribute('name') || '',
        text: text,
        href: el.href || '',
        autocomplete: el.getAttribute('autocomplete') || '',
      };
    }),
  };
}"""
            )
            if isinstance(raw, list):
                heading = ""
                nodes = raw
            else:
                heading = str((raw or {}).get("heading") or "").strip()
                nodes = list((raw or {}).get("nodes") or [])
            self._refs = {
                item["ref"]: ElementInfo(
                    ref=item["ref"],
                    tag=item.get("tag") or "",
                    role=item.get("role") or "",
                    type=item.get("type") or "",
                    name=item.get("name") or "",
                    text=item.get("text") or "",
                    href=item.get("href") or "",
                    autocomplete=item.get("autocomplete") or "",
                )
                for item in nodes
            }
            title = await self._page.title()
            url = self._page.url
            lines = [f"title: {title}", f"url: {url}"]
            if heading:
                lines.append(f"heading: {heading}")
            lines.append("elements:")
            for info in self._refs.values():
                lines.append(info.line())
            text = "\n".join(lines)
            if len(text) > max_chars:
                text = text[: max_chars - 20] + "\n…(snapshot truncated)"
            return ActionResult(
                ok=True,
                output=text,
                data={"url": url, "title": title, "refs": list(self._refs)},
            )
        except Exception as exc:
            self._page = None
            return _playwright_fail(exc)

    async def read(self, *, max_chars: int = 3500) -> ActionResult:
        err = await self._require_page()
        if err:
            return err
        assert self._page is not None
        try:
            raw = await self._page.evaluate(
                """() => {
  const root = document.querySelector('main, article, [role="main"]')
    || document.body;
  const clone = root ? root.cloneNode(true) : null;
  if (clone) {
    clone.querySelectorAll(
      'script, style, noscript, svg, nav, footer, [hidden], [aria-hidden="true"]'
    ).forEach((el) => el.remove());
  }
  const text = ((clone && clone.innerText) || '').replace(/\\u00a0/g, ' ');
  return {
    title: document.title || '',
    url: location.href,
    heading: ((document.querySelector('h1') || {}).innerText || '')
      .trim().slice(0, 160),
    text: text,
  };
}"""
            )
            info = raw if isinstance(raw, dict) else {}
            title = str(info.get("title") or "").strip() or await self._page.title()
            url = str(info.get("url") or "").strip() or self._page.url
            heading = str(info.get("heading") or "").strip()
            text = format_tab_read(
                title=title,
                url=url,
                heading=heading,
                body=str(info.get("text") or ""),
                max_chars=max_chars,
            )
            return ActionResult(
                ok=True,
                output=text,
                data={
                    "url": url,
                    "title": title,
                    "heading": heading,
                    "chars": len(text),
                    "untrusted": True,
                },
            )
        except Exception as exc:
            self._page = None
            return _playwright_fail(exc)

    async def click(self, ref: str) -> ActionResult:
        err = await self._require_page()
        if err:
            return err
        assert self._page is not None
        if ref not in self._refs:
            return ActionResult(
                ok=False,
                output=f"Unknown ref {ref!r}. Call snapshot first.",
            )
        info = self._refs[ref]
        from arelis.browser.walls import attach_wall, detect_wall

        wall = detect_wall(click_label=info.text or info.name)
        if wall is not None and wall.kind == "pay":
            return attach_wall(
                ActionResult(
                    ok=False,
                    output=f"Stopped before [{ref}] {info.text or info.tag}.",
                    data={"ref": ref, "label": info.text, "url": self._page.url},
                ),
                wall,
                ok=False,
            )
        try:
            await _glow_ref(self._page, ref)
            loc = self._page.locator(f'[data-arelis-ref="{ref}"]')
            await loc.first.click(timeout=10_000)
            return ActionResult(
                ok=True,
                output=f"Clicked [{ref}] {info.text or info.tag}",
                data={
                    "ref": ref,
                    "url": self._page.url,
                    "glowed": True,
                    "label": info.text,
                },
            )
        except Exception as exc:
            self._page = None
            return _playwright_fail(exc)

    async def type_text(self, ref: str, text: str) -> ActionResult:
        err = await self._require_page()
        if err:
            return err
        assert self._page is not None
        info = self._refs.get(ref)
        if info is None:
            return ActionResult(
                ok=False,
                output=f"Unknown ref {ref!r}. Call snapshot first.",
            )
        if info.is_secret_field():
            return ActionResult(
                ok=False,
                output=(
                    "Refused to type into a password/OTP field. "
                    "Arelis does not enter credentials — sign in yourself."
                ),
                data={"code": "SECRET_FIELD", "ref": ref},
            )
        try:
            loc = self._page.locator(f'[data-arelis-ref="{ref}"]')
            await loc.first.fill(text, timeout=10_000)
            return ActionResult(
                ok=True,
                output=f"Typed into [{ref}]",
                data={"ref": ref, "length": len(text)},
            )
        except Exception as exc:
            self._page = None
            return _playwright_fail(exc)

    async def tabs(self, *, select: int | None = None) -> ActionResult:
        err = await self._require_page()
        if err:
            return err
        assert self._context is not None
        try:
            pages = self._context.pages
            if select is not None:
                if select < 0 or select >= len(pages):
                    return ActionResult(ok=False, output=f"No tab index {select}.")
                self._page = pages[select]
                await self._page.bring_to_front()
                title = await self._page.title()
                return ActionResult(
                    ok=True,
                    output=f"Selected tab {select}: {title}",
                    data={"active": select, "url": self._page.url, "title": title},
                )
            rows: list[dict[str, Any]] = []
            lines: list[str] = []
            for i, page in enumerate(pages):
                try:
                    title = await page.title()
                    url = page.url
                except Exception:
                    title, url = "?", "?"
                active = page == self._page
                rows.append({"index": i, "title": title, "url": url, "active": active})
                mark = " (active)" if active else ""
                lines.append(f"{i}: {title} — {url}{mark}")
            return ActionResult(
                ok=True,
                output="Tabs:\n" + "\n".join(lines),
                data={"tabs": rows},
            )
        except Exception as exc:
            self._page = None
            return _playwright_fail(exc)

    async def screenshot(
        self, path: str, *, full_page: bool = False
    ) -> ActionResult:
        err = await self._require_page()
        if err:
            return err
        assert self._page is not None
        await asyncio.to_thread(_ensure_parent_dir, path)
        try:
            await self._page.screenshot(path=path, full_page=bool(full_page))
        except Exception as exc:
            fail = _playwright_fail(exc)
            if fail.data.get("code") == "CDP_DEAD":
                self._page = None
                return fail
            return ActionResult(
                ok=False,
                output=f"Screenshot failed: {exc}",
                data={"code": "SCREENSHOT_FAILED"},
            )
        try:
            size = await asyncio.to_thread(_file_size_sync, path)
            title = await self._page.title()
            abs_path = await asyncio.to_thread(os.path.abspath, path)
            return ActionResult(
                ok=True,
                output=f"Screenshot saved ({'full page' if full_page else 'viewport'}).",
                data={
                    "path": abs_path,
                    "url": self._page.url,
                    "title": title,
                    "full_page": bool(full_page),
                    "bytes": size,
                },
            )
        except Exception as exc:
            self._page = None
            return _playwright_fail(exc)

    async def scroll(
        self,
        *,
        direction: str = "down",
        amount: int = 600,
        ref: str = "",
    ) -> ActionResult:
        err = await self._require_page()
        if err:
            return err
        assert self._page is not None
        try:
            if ref:
                if ref not in self._refs:
                    return ActionResult(
                        ok=False,
                        output=f"Unknown ref {ref!r}. Call snapshot first.",
                    )
                await self._page.evaluate(
                    """(ref) => {
                      const el = document.querySelector('[data-arelis-ref="' + ref + '"]');
                      if (el) el.scrollIntoView({block: 'center', inline: 'nearest'});
                    }""",
                    ref,
                )
                return ActionResult(ok=True, output=f"Scrolled [{ref}] into view.")
            way = (direction or "down").strip().lower() or "down"
            px = max(40, min(int(amount), 4000))
            dx, dy = 0, px
            if way == "up":
                dy = -px
            elif way == "left":
                dx, dy = -px, 0
            elif way == "right":
                dx, dy = px, 0
            elif way == "page":
                await self._page.evaluate("() => window.scrollBy(0, window.innerHeight)")
                return ActionResult(ok=True, output="Scrolled one page down.")
            await self._page.evaluate("([x, y]) => window.scrollBy(x, y)", [dx, dy])
            return ActionResult(ok=True, output=f"Scrolled {way} {px}px.")
        except Exception as exc:
            self._page = None
            return _playwright_fail(exc)

    async def press(self, key: str) -> ActionResult:
        err = await self._require_page()
        if err:
            return err
        assert self._page is not None
        mapped = normalize_press_key(key)
        if not mapped:
            return ActionResult(
                ok=False,
                output=f"Unsupported key {key!r}. Use Enter, Escape, Tab, arrows.",
            )
        try:
            await self._page.keyboard.press(mapped)
            return ActionResult(ok=True, output=f"Pressed {mapped}.")
        except Exception as exc:
            self._page = None
            return _playwright_fail(exc)

    async def select_option(self, ref: str, value: str) -> ActionResult:
        err = await self._require_page()
        if err:
            return err
        assert self._page is not None
        info = self._refs.get(ref)
        if info is None:
            return ActionResult(
                ok=False,
                output=f"Unknown ref {ref!r}. Call snapshot first.",
            )
        if info.tag != "select":
            return ActionResult(ok=False, output=f"[{ref}] is not a dropdown.")
        try:
            loc = self._page.locator(f'[data-arelis-ref="{ref}"]')
            await loc.first.select_option(label=value, timeout=8_000)
            return ActionResult(ok=True, output=f"Selected {value!r} on [{ref}].")
        except Exception:
            try:
                loc = self._page.locator(f'[data-arelis-ref="{ref}"]')
                await loc.first.select_option(value=value, timeout=8_000)
                return ActionResult(ok=True, output=f"Selected {value!r} on [{ref}].")
            except Exception as exc:
                self._page = None
                return _playwright_fail(exc)

    async def wait(self, seconds: float) -> ActionResult:
        err = await self._require_page()
        if err:
            return err
        delay = max(0.2, min(float(seconds), 8.0))
        await cooperative_wait(delay)
        return ActionResult(ok=True, output=f"Waited {delay:.1f}s.")
