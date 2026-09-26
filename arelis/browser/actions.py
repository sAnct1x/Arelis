"""Page actions + fake driver for offline tests."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
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
    region: str = ""

    def is_secret_field(self) -> bool:
        if self.type.lower() in _SECRET_INPUT_TYPES:
            return True
        if _SECRET_AUTOCOMPLETE.search(self.autocomplete or ""):
            return True
        if self.name.lower() in {"password", "passwd", "otp", "totp"}:
            return True
        return False

    def is_file_field(self) -> bool:
        return self.type.lower() == "file"

    def line(self) -> str:
        bits = [f"[{self.ref}]", self.tag]
        if self.role:
            bits.append(f"role={self.role}")
        if self.type:
            bits.append(f"type={self.type}")
        if self.region and self.region != "main":
            bits.append(self.region)
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

    async def snapshot(
        self, *, max_chars: int = 6000, focus: str = ""
    ) -> ActionResult: ...

    async def read(self, *, max_chars: int = 3500) -> ActionResult: ...

    async def click(self, ref: str) -> ActionResult: ...

    async def hover(
        self,
        ref: str = "",
        *,
        x: float | None = None,
        y: float | None = None,
    ) -> ActionResult: ...

    async def dblclick(
        self,
        ref: str = "",
        *,
        x: float | None = None,
        y: float | None = None,
    ) -> ActionResult: ...

    async def right_click(
        self,
        ref: str = "",
        *,
        x: float | None = None,
        y: float | None = None,
    ) -> ActionResult: ...

    async def drag(
        self,
        ref: str = "",
        *,
        to: str = "",
        x: float | None = None,
        y: float | None = None,
        to_x: float | None = None,
        to_y: float | None = None,
    ) -> ActionResult: ...

    async def type_text(self, ref: str, text: str) -> ActionResult: ...

    async def tabs(
        self,
        *,
        select: int | str | None = None,
        op: str = "",
        url: str = "",
    ) -> ActionResult: ...

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

    async def wait(
        self,
        seconds: float = 1.0,
        *,
        url: str = "",
        text: str = "",
        heading: str = "",
    ) -> ActionResult: ...

    async def watch(
        self,
        *,
        url: str = "",
        text: str = "",
        heading: str = "",
    ) -> ActionResult: ...

    async def download(self, path: str, *, ref: str = "") -> ActionResult: ...

    async def upload(self, ref: str, path: str) -> ActionResult: ...

    async def pdf(self, path: str) -> ActionResult: ...

    async def back(self) -> ActionResult: ...

    async def forward(self) -> ActionResult: ...

    async def reload(self) -> ActionResult: ...

    async def settle(self, *, timeout_s: float = 4.0) -> ActionResult: ...

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

# Count trusted pointerdowns so a user grab mid-drive is not our own click.
_HANDS_JS = """
(() => {
  if (window.__arelisHands) return;
  window.__arelisHands = true;
  window.__arelisPtrCount = 0;
  window.addEventListener(
    'pointerdown',
    () => { window.__arelisPtrCount = (window.__arelisPtrCount || 0) + 1; },
    true
  );
})();
"""
_PTR_COUNT_JS = "() => window.__arelisPtrCount || 0"

_CDP_DEAD_TIPS = (
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
SETTLE_S = 4.0
SETTLE_POLL_S = 0.2

SETTLE_HAS_RESULT_JS = r"""() => {
  const root = document.querySelector('main, [role="main"], #content, ytd-app')
    || document.body;
  if (!root) return false;
  const links = root.querySelectorAll('a[href]');
  for (const a of links) {
    const href = a.href || '';
    const text = (a.innerText || a.getAttribute('aria-label') || '').trim();
    if (href.startsWith('http') && text.length >= 4
        && !/^(go to channel|subscribe)\b/i.test(text)
        && !/(?:youtube\.com|youtu\.be)\/(?:channel\/|@|c\/|user\/|results)/i.test(href)
        && (!(href.toLowerCase().includes('youtube.com') || href.toLowerCase().includes('youtu.be'))
            || href.toLowerCase().includes('/watch')
            || href.toLowerCase().includes('/shorts/'))) {
      const host = a.closest(
        'header, nav, footer, [role="banner"], [role="navigation"], [role="contentinfo"]'
      );
      if (!host) return true;
    }
  }
  return false;
}"""

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


async def _glow_xy(page: Any, x: float, y: float) -> bool:
    """Dot the pixel target in-page, then wait a beat."""
    try:
        ok = await page.evaluate(
            """([x, y]) => {
              let mark = document.getElementById('arelis-xy-glow');
              if (!mark) {
                mark = document.createElement('div');
                mark.id = 'arelis-xy-glow';
                mark.style.cssText = (
                  'position:fixed;width:16px;height:16px;margin:-8px 0 0 -8px;'
                  + 'border:2px solid #5ad4ff;border-radius:50%;'
                  + 'pointer-events:none;z-index:' + (0x7fffffff) + ';'
                );
                document.documentElement.appendChild(mark);
              }
              mark.style.left = x + 'px';
              mark.style.top = y + 'px';
              return true;
            }""",
            [float(x), float(y)],
        )
    except Exception:
        ok = False
    if GLOW_S > 0:
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


def _is_cdp_dead(exc: BaseException) -> bool:
    lowered = (str(exc).strip() or type(exc).__name__).lower()
    return any(tip in lowered for tip in _CDP_DEAD_TIPS)


def _hands_result(*, url: str = "", extra: str = "") -> ActionResult:
    from arelis.browser.walls import Wall, attach_wall, wall_message

    note = extra or "You have the mouse."
    return attach_wall(
        ActionResult(
            ok=True,
            output=note,
            data={"url": url, "label": "you"},
        ),
        Wall("hands", "operator", wall_message("hands")),
    )


def _playwright_fail(exc: BaseException) -> ActionResult:
    """Map a mid-turn Playwright/CDP crash to a stable tool result (not a turn kill)."""
    msg = str(exc).strip() or type(exc).__name__
    dead = _is_cdp_dead(exc)
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
                region="header",
            ),
            "e2": ElementInfo(
                ref="e2",
                tag="input",
                role="textbox",
                type="search",
                text="Search",
                name="search_query",
            ),
            "e6": ElementInfo(
                ref="e6",
                tag="a",
                role="link",
                text="Never Gonna Give You Up",
                href="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                region="main",
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
            "e7": ElementInfo(
                ref="e7",
                tag="input",
                role="textbox",
                type="email",
                name="email",
                text="Email",
            ),
            "e8": ElementInfo(
                ref="e8",
                tag="input",
                role="textbox",
                type="tel",
                name="phone",
                text="Phone",
            ),
            "e9": ElementInfo(
                ref="e9",
                tag="input",
                role="textbox",
                type="text",
                name="name",
                text="Name",
            ),
            "e10": ElementInfo(
                ref="e10",
                tag="input",
                type="file",
                name="file",
                text="Choose file",
            ),
            "e12": ElementInfo(
                ref="e12",
                tag="a",
                role="link",
                text="Download report",
                href="https://example.com/report.csv",
            ),
        }
        # Optional extra signals for tests: {"recaptcha": True} etc.
        self.simulate_wall: dict[str, Any] = {}
        self.scrolled: list[str] = []
        self.pressed: list[str] = []
        self.selected: list[tuple[str, str]] = []
        self.waited: list[float] = []
        self.settled: list[float] = []
        self.glowed: list[str] = []
        self.hovered: list[str] = []
        self.dblclicked: list[str] = []
        self.right_clicked: list[str] = []
        self.dragged: list[tuple[str, str]] = []
        self.downloaded: list[str] = []
        self.uploaded: list[tuple[str, str]] = []
        self._tabs: list[dict[str, str]] = [
            {"index": "0", "title": "New Tab", "url": "about:blank"},
        ]
        self._history: list[tuple[str, str]] = []
        self._future: list[tuple[str, str]] = []
        self._active = 0
        # When True, ensure() reports PROFILE_LOCKED unless relaunch=True.
        self.simulate_locked = False
        # When True, page actions fail with CDP_DEAD until relaunch=True.
        self.fail_until_relaunch = False
        self.heading = ""
        self.page_text = "Home\nSearch\nArelis test page. Welcome to the fake tab."
        # Test hook: requested URL → landed URL (login bounce, etc.).
        self.redirects: dict[str, str] = {}
        # Test hook: first wait-for applies this URL (SPA bounce after paint).
        self.pending_wait_url: str = ""
        # Test hook: operator grabbed the page between steps.
        self.user_took_over = False
        self.watch_stop = False

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

    def _push_history(self) -> None:
        current = (self.url, self.title)
        if current[0] and (not self._history or self._history[-1] != current):
            self._history.append(current)
        self._future.clear()

    def _dead_until_relaunch(self) -> ActionResult | None:
        if self.fail_until_relaunch and self.relaunch_count < 1:
            return ActionResult(
                ok=False,
                output=(
                    "[fail:browser] Browser control failed (disconnected). "
                    "Call browser(action=relaunch, url=…) after Allow."
                ),
                data={"code": "CDP_DEAD"},
            )
        return None

    async def open_url(self, url: str) -> ActionResult:
        dead = self._dead_until_relaunch()
        if dead:
            return dead
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        from arelis.browser.walls import nav_landed_note

        self._push_history()
        landed = self.redirects.get(url) or self.redirects.get(url.rstrip("/")) or url
        self.url = landed
        self.title = landed
        self.heading = ""
        self.page_text = f"Opened page at {landed}."
        self._tabs[self._active] = {
            "index": str(self._active),
            "title": self.title,
            "url": landed,
        }
        output = f"Opened {landed}"
        note = nav_landed_note(url, landed)
        if note:
            output = f"{output}\n\n{note}"
        return ActionResult(
            ok=True,
            output=output,
            data={"url": landed, "title": self.title, "requested_url": url},
        )

    async def navigate(self, url: str) -> ActionResult:
        return await self.open_url(url)

    async def snapshot(self, *, max_chars: int = 6000, focus: str = "") -> ActionResult:
        dead = self._dead_until_relaunch()
        if dead:
            return dead
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        from arelis.browser.hold import set_drive_labels
        from arelis.browser.snapshot import format_result_lines

        set_drive_labels(
            {ref: info.text or info.name for ref, info in self._elements.items()}
        )
        if (focus or "").strip().lower() == "results":
            results = format_result_lines(self._elements)
            text = "\n".join(
                [f"title: {self.title}", f"url: {self.url}", results or "results:"]
            )
        else:
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
                "focus": (focus or "").strip().lower(),
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
        dead = self._dead_until_relaunch()
        if dead:
            return dead
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
        if self.user_took_over:
            self.user_took_over = False
            return _hands_result(url=self.url)
        self.glowed.append(ref)
        self.clicked.append(ref)
        if info.href:
            self._push_history()
            self.url = info.href
            self.title = info.text or info.href
        return ActionResult(
            ok=True,
            output=f"Clicked [{ref}] {info.text or info.tag}",
            data={"ref": ref, "url": self.url, "label": info.text},
        )

    def _pointer_target(
        self, ref: str, *, x: float | None = None, y: float | None = None
    ) -> tuple[str, ActionResult | None]:
        if x is not None and y is not None:
            key = f"xy:{int(x)},{int(y)}"
            return key, None
        info = self._elements.get(ref)
        if info is None:
            return "", ActionResult(
                ok=False, output=f"Unknown ref {ref!r}. Call snapshot."
            )
        return ref, None

    async def hover(
        self,
        ref: str = "",
        *,
        x: float | None = None,
        y: float | None = None,
    ) -> ActionResult:
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        key, err = self._pointer_target(ref, x=x, y=y)
        if err:
            return err
        self.glowed.append(key)
        self.hovered.append(key)
        return ActionResult(
            ok=True,
            output=f"Hovered [{key}]",
            data={"ref": ref, "x": x, "y": y, "glowed": True, "url": self.url},
        )

    async def dblclick(
        self,
        ref: str = "",
        *,
        x: float | None = None,
        y: float | None = None,
    ) -> ActionResult:
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        key, err = self._pointer_target(ref, x=x, y=y)
        if err:
            return err
        info = self._elements.get(ref)
        if info is not None:
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
        self.glowed.append(key)
        self.dblclicked.append(key)
        return ActionResult(
            ok=True,
            output=f"Double-clicked [{key}]",
            data={"ref": ref, "x": x, "y": y, "glowed": True, "url": self.url},
        )

    async def right_click(
        self,
        ref: str = "",
        *,
        x: float | None = None,
        y: float | None = None,
    ) -> ActionResult:
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        key, err = self._pointer_target(ref, x=x, y=y)
        if err:
            return err
        self.glowed.append(key)
        self.right_clicked.append(key)
        return ActionResult(
            ok=True,
            output=f"Right-clicked [{key}]",
            data={"ref": ref, "x": x, "y": y, "glowed": True, "url": self.url},
        )

    async def drag(
        self,
        ref: str = "",
        *,
        to: str = "",
        x: float | None = None,
        y: float | None = None,
        to_x: float | None = None,
        to_y: float | None = None,
    ) -> ActionResult:
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        src, err = self._pointer_target(ref, x=x, y=y)
        if err:
            return err
        dest, dest_err = self._pointer_target(to, x=to_x, y=to_y)
        if dest_err:
            return dest_err
        self.glowed.append(src)
        self.dragged.append((src, dest))
        return ActionResult(
            ok=True,
            output=f"Dragged [{src}] to [{dest}]",
            data={
                "ref": ref,
                "to": to,
                "x": x,
                "y": y,
                "to_x": to_x,
                "to_y": to_y,
                "glowed": True,
                "url": self.url,
            },
        )

    async def type_text(self, ref: str, text: str) -> ActionResult:
        info = self._elements.get(ref)
        if info is None:
            return ActionResult(ok=False, output=f"Unknown ref {ref!r}. Call snapshot.")
        if info.is_file_field():
            return ActionResult(
                ok=False,
                output="type=file is refused. Use browser(action=upload, path=…).",
                data={"code": "FILE_INPUT", "ref": ref},
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
        self.typed.append((ref, text))
        info.text = text
        return ActionResult(
            ok=True,
            output=f"Typed into [{ref}]",
            data={"ref": ref, "length": len(text)},
        )

    def _sync_active_tab(self) -> None:
        self._tabs[self._active] = {
            "index": str(self._active),
            "title": self.title,
            "url": self.url,
        }

    async def tabs(
        self,
        *,
        select: int | str | None = None,
        op: str = "",
        url: str = "",
    ) -> ActionResult:
        from arelis.browser.places import format_tab_list, parse_tab_select, pick_tab

        kind = (op or "").strip().lower()
        idx, title_needle = parse_tab_select(select)
        if kind == "close" and title_needle:
            return ActionResult(
                ok=False,
                output=(
                    "Close is the current tab only. "
                    "Select the tab first, then tabs with tab=close. "
                    "No close-by-title."
                ),
                data={"code": "CLOSE_BY_TITLE"},
            )
        if kind == "new":
            self._sync_active_tab()
            self._active = len(self._tabs)
            target = (url or "").strip() or "about:blank"
            self.url = target
            self.title = target
            self._tabs.append(
                {"index": str(self._active), "title": self.title, "url": self.url}
            )
            self._history.clear()
            self._future.clear()
            return ActionResult(
                ok=True,
                output=f"Opened tab {self._active}: {self.url}",
                data={"tabs": list(self._tabs), "active": self._active, "url": self.url},
            )
        if kind == "close":
            if len(self._tabs) <= 1:
                self.url = "about:blank"
                self.title = "New Tab"
                self._tabs = [{"index": "0", "title": self.title, "url": self.url}]
                self._active = 0
                self._history.clear()
                self._future.clear()
                return ActionResult(
                    ok=True,
                    output="Closed the last tab — blank tab stays.",
                    data={"tabs": list(self._tabs), "active": 0},
                )
            self._tabs.pop(self._active)
            self._active = min(self._active, len(self._tabs) - 1)
            for i, tab in enumerate(self._tabs):
                tab["index"] = str(i)
            tab = self._tabs[self._active]
            self.url = tab["url"]
            self.title = tab["title"]
            return ActionResult(
                ok=True,
                output=f"Closed a tab. Now {self._active}: {self.title}",
                data={"tabs": list(self._tabs), "active": self._active},
            )
        if idx is not None or title_needle:
            chosen, err = pick_tab(self._tabs, index=idx, title=title_needle)
            if err or chosen is None:
                return ActionResult(ok=False, output=err or "No tab.")
            self._sync_active_tab()
            self._active = chosen
            tab = self._tabs[chosen]
            self.url = tab["url"]
            self.title = tab["title"]
            return ActionResult(
                ok=True,
                output=f"Selected tab {chosen}: {tab['title']}",
                data={
                    "tabs": list(self._tabs),
                    "active": chosen,
                    "url": self.url,
                    "title": self.title,
                },
            )
        return ActionResult(
            ok=True,
            output=format_tab_list(self._tabs, active=self._active),
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

    async def wait(
        self,
        seconds: float = 1.0,
        *,
        url: str = "",
        text: str = "",
        heading: str = "",
    ) -> ActionResult:
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        from arelis.browser.wait_for import (
            clamp_wait_seconds,
            has_wait_needle,
            page_needles_hit,
            wait_output,
        )

        has = has_wait_needle(url=url, text=text, heading=heading)
        delay = clamp_wait_seconds(seconds, has_needle=has)
        self.waited.append(delay)
        if has and self.pending_wait_url:
            landed = self.pending_wait_url
            self.pending_wait_url = ""
            self.url = landed
            self.title = landed
            self.page_text = f"Opened page at {landed}."
            self._tabs[self._active] = {
                "index": str(self._active),
                "title": self.title,
                "url": landed,
            }
        hit = page_needles_hit(
            landed_url=self.url,
            title=self.title,
            heading=self.heading,
            page_text=self.page_text,
            want_url=url,
            want_text=text,
            want_heading=heading,
        )
        output, data = wait_output(
            hit=hit if has else True,
            seconds=delay,
            landed_url=self.url,
            want_url=url,
            want_text=text,
            want_heading=heading,
        )
        data["title"] = self.title
        return ActionResult(ok=True, output=output, data=data)

    async def watch(
        self,
        *,
        url: str = "",
        text: str = "",
        heading: str = "",
    ) -> ActionResult:
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        from arelis.browser.wait_for import has_wait_needle, page_needles_hit

        if not has_wait_needle(url=url, text=text, heading=heading):
            return ActionResult(
                ok=False,
                output="watch needs url, text, or heading to poll for.",
            )
        if self.watch_stop:
            return ActionResult(
                ok=True,
                output="Watch cancelled.",
                data={"hit": False, "cancelled": True, "url": self.url},
            )
        if self.pending_wait_url:
            landed = self.pending_wait_url
            self.pending_wait_url = ""
            self.url = landed
            self.title = landed
            self.page_text = f"Opened page at {landed}."
        hit = page_needles_hit(
            landed_url=self.url,
            title=self.title,
            heading=self.heading,
            page_text=self.page_text,
            want_url=url,
            want_text=text,
            want_heading=heading,
        )
        if hit:
            return ActionResult(
                ok=True,
                output=f"Watch hit — {self.url}",
                data={
                    "hit": True,
                    "watch_hit": True,
                    "url": self.url,
                    "title": self.title,
                },
            )
        return ActionResult(
            ok=True,
            output=f"Watch still waiting — {self.url}",
            data={"hit": False, "url": self.url, "title": self.title},
        )

    async def download(self, path: str, *, ref: str = "") -> ActionResult:
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        if ref and ref not in self._elements:
            return ActionResult(ok=False, output=f"Unknown ref {ref!r}. Call snapshot.")
        if ref:
            self.glowed.append(ref)
            self.clicked.append(ref)
        from arelis.browser.files import file_ready_payload

        body = f"fake download from {self.url}\n".encode()
        abs_path = await asyncio.to_thread(_write_bytes_sync, path, body)
        self.downloaded.append(abs_path)
        data = file_ready_payload(Path(abs_path), kind="download")
        data["ref"] = ref
        data["url"] = self.url
        return ActionResult(
            ok=True,
            output=f"Downloaded {Path(abs_path).name}",
            data=data,
        )

    async def upload(self, ref: str, path: str) -> ActionResult:
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        info = self._elements.get(ref)
        if info is None:
            return ActionResult(ok=False, output=f"Unknown ref {ref!r}. Call snapshot.")
        if not info.is_file_field():
            return ActionResult(
                ok=False,
                output=f"[{ref}] is not a file input. Snapshot and upload to type=file.",
                data={"code": "NOT_FILE", "ref": ref},
            )
        self.glowed.append(ref)
        self.uploaded.append((ref, path))
        info.text = Path(path).name
        return ActionResult(
            ok=True,
            output=f"Uploaded {Path(path).name} to [{ref}]",
            data={"ref": ref, "path": path, "name": Path(path).name},
        )

    async def pdf(self, path: str) -> ActionResult:
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        from arelis.browser.files import fake_pdf_bytes, file_ready_payload

        abs_path = await asyncio.to_thread(_write_bytes_sync, path, fake_pdf_bytes())
        data = file_ready_payload(Path(abs_path), kind="pdf", title=self.title)
        data["url"] = self.url
        return ActionResult(
            ok=True,
            output=f"Saved tab PDF {Path(abs_path).name}",
            data=data,
        )

    async def back(self) -> ActionResult:
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        if not self._history:
            return ActionResult(ok=False, output="Nothing to go back to.")
        self._future.append((self.url, self.title))
        self.url, self.title = self._history.pop()
        self._tabs[self._active] = {
            "index": str(self._active),
            "title": self.title,
            "url": self.url,
        }
        return ActionResult(
            ok=True,
            output=f"Went back to {self.url}",
            data={"url": self.url, "title": self.title},
        )

    async def forward(self) -> ActionResult:
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        if not self._future:
            return ActionResult(ok=False, output="Nothing to go forward to.")
        self._history.append((self.url, self.title))
        self.url, self.title = self._future.pop()
        self._tabs[self._active] = {
            "index": str(self._active),
            "title": self.title,
            "url": self.url,
        }
        return ActionResult(
            ok=True,
            output=f"Went forward to {self.url}",
            data={"url": self.url, "title": self.title},
        )

    async def reload(self) -> ActionResult:
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        return ActionResult(
            ok=True,
            output=f"Reloaded {self.url}",
            data={"url": self.url, "title": self.title},
        )

    async def settle(self, *, timeout_s: float = 4.0) -> ActionResult:
        if not self.connected:
            return ActionResult(ok=False, output="Browser not connected.")
        self.settled.append(float(timeout_s))
        return ActionResult(ok=True, output="Settled.", data={"settled": True})

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
        self._ptr_seen = 0
        self._placed = False
        self._fresh_launch = False

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

        live = (
            not relaunch
            and self._browser is not None
            and self._page is not None
            and launch_mod.cdp_is_up(self.cdp_url)
        )
        if live:
            return await self._attach_cdp(mode="attach")

        chosen = launch_mod.prefer_cdp_url(self.cdp_url)
        if chosen != self.cdp_url:
            log.info(
                "CDP %s is not Arelis Chrome; using %s",
                self.cdp_url,
                chosen,
            )
            self.cdp_url = chosen

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
            self._fresh_launch = True
            self._placed = False
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
        self._fresh_launch = True
        self._placed = False
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
        await self._install_hands()
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
            await self._install_hands()
            self._mode = mode
            await self._present_window()
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
        await self._install_hands()
        self._mode = mode
        await self._present_window()
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

    async def _present_window(self) -> None:
        """Show her Chrome. Park only a window we just started.

        After that the operator owns size and place. Clicks are CDP — the
        window does not need focus. It does need to be in front of Arelis
        the first time it opens, not behind the glass.
        """
        from arelis.browser.launch import (
            raise_arelis_chrome,
            should_park_window,
            window_placement,
        )

        park = should_park_window(
            fresh_launch=self._fresh_launch, already_placed=self._placed
        )
        if park and self._page is not None:
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
            self._placed = True
            self._fresh_launch = False
        raise_arelis_chrome(restore=True)

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

    async def _install_hands(self) -> None:
        """Listen for operator pointerdowns across navigations."""
        ctx = self._context
        page = self._page
        if ctx is not None:
            try:
                await ctx.add_init_script(_HANDS_JS)
            except Exception:
                log.debug("hands init script skipped", exc_info=True)
        if page is not None:
            try:
                await page.evaluate(_HANDS_JS)
            except Exception:
                log.debug("hands inject skipped", exc_info=True)
        self._ptr_seen = 0

    async def _ptr_count(self) -> int:
        if self._page is None:
            return self._ptr_seen
        try:
            raw = await self._page.evaluate(_PTR_COUNT_JS)
        except Exception:
            return self._ptr_seen
        try:
            return int(raw or 0)
        except (TypeError, ValueError):
            return self._ptr_seen

    async def _consume_hands(self) -> ActionResult | None:
        count = await self._ptr_count()
        if count <= self._ptr_seen:
            return None
        self._ptr_seen = count
        url = ""
        try:
            url = str(self._page.url) if self._page is not None else ""
        except Exception:
            url = ""
        return _hands_result(url=url)

    def _fail_keep_or_drop(self, exc: BaseException) -> ActionResult:
        if _is_cdp_dead(exc):
            self._page = None
        return _playwright_fail(exc)

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
                await self.settle()
            await self._poll_leave_login(url)
            await self._present_window()
            title = await page.title()
            heading = await _page_heading(page)
            landed = str(page.url or url)
            from arelis.browser.walls import nav_landed_note

            bits = [f"Opened {landed}"]
            if title:
                bits.append(f"title: {title}")
            if heading:
                bits.append(f"heading: {heading}")
            output = "\n".join(bits)
            note = nav_landed_note(url, landed)
            if note:
                output = f"{output}\n\n{note}"
            return ActionResult(
                ok=True,
                output=output,
                data={
                    "url": landed,
                    "title": title,
                    "heading": heading,
                    "requested_url": url,
                },
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
            await self.settle()
            await self._poll_leave_login(url)
            title = await self._page.title()
            landed = str(self._page.url or url)
            from arelis.browser.walls import nav_landed_note

            output = f"Navigated to {landed}"
            note = nav_landed_note(url, landed)
            if note:
                output = f"{output}\n\n{note}"
            return ActionResult(
                ok=True,
                output=output,
                data={"url": landed, "title": title, "requested_url": url},
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

    async def snapshot(self, *, max_chars: int = 6000, focus: str = "") -> ActionResult:
        err = await self._require_page()
        if err:
            return err
        assert self._page is not None
        try:
            from arelis.browser.snapshot import (
                SNAPSHOT_COLLECT_JS,
                SNAPSHOT_STAMP_JS,
                rank_snapshot_nodes,
            )

            focus_key = (focus or "").strip().lower()
            raw = await self._page.evaluate(SNAPSHOT_COLLECT_JS, focus_key)
            if isinstance(raw, list):
                heading = ""
                collected = raw
            else:
                heading = str((raw or {}).get("heading") or "").strip()
                collected = list((raw or {}).get("nodes") or [])
            nodes = rank_snapshot_nodes(collected)
            if nodes:
                await self._page.evaluate(
                    SNAPSHOT_STAMP_JS,
                    {
                        "focus": focus_key,
                        "pairs": [
                            {"index": n["index"], "ref": n["ref"]} for n in nodes
                        ],
                    },
                )
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
                    region=str(item.get("region") or ""),
                )
                for item in nodes
            }
            title = await self._page.title()
            url = self._page.url
            from arelis.browser.snapshot import format_result_lines

            lines = [f"title: {title}", f"url: {url}"]
            if heading:
                lines.append(f"heading: {heading}")
            if (focus or "").strip().lower() == "results":
                results = format_result_lines(self._refs)
                lines.append(results or "results:")
            else:
                lines.append("elements:")
                for info in self._refs.values():
                    lines.append(info.line())
            text = "\n".join(lines)
            if len(text) > max_chars:
                text = text[: max_chars - 20] + "\n…(snapshot truncated)"
            from arelis.browser.hold import set_drive_labels

            set_drive_labels(
                {ref: info.text or info.name for ref, info in self._refs.items()}
            )
            return ActionResult(
                ok=True,
                output=text,
                data={
                    "url": url,
                    "title": title,
                    "refs": list(self._refs),
                    "focus": (focus or "").strip().lower(),
                },
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
        hands = await self._consume_hands()
        if hands is not None:
            return hands
        try:
            await _glow_ref(self._page, ref)
            hands = await self._consume_hands()
            if hands is not None:
                return hands
            before = await self._ptr_count()
            loc = self._page.locator(f'[data-arelis-ref="{ref}"]')
            await loc.first.click(timeout=10_000)
            after = await self._ptr_count()
            if after > before + 1:
                self._ptr_seen = after
                return _hands_result(
                    url=str(self._page.url or ""),
                    extra="You have the mouse. I stopped clicking.",
                )
            self._ptr_seen = after
            try:
                await self._page.wait_for_load_state(
                    "domcontentloaded", timeout=4_000
                )
            except Exception:
                pass
            await self.settle()
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
        except Exception as extra_exc:
            try:
                now = await self._ptr_count()
            except Exception:
                now = self._ptr_seen
            if now > self._ptr_seen:
                self._ptr_seen = now
                url = ""
                try:
                    url = str(self._page.url or "") if self._page is not None else ""
                except Exception:
                    url = ""
                return _hands_result(
                    url=url,
                    extra="You have the mouse. I stopped clicking.",
                )
            return self._fail_keep_or_drop(extra_exc)

    async def hover(
        self,
        ref: str = "",
        *,
        x: float | None = None,
        y: float | None = None,
    ) -> ActionResult:
        return await self._pointer("hover", ref=ref, x=x, y=y)

    async def dblclick(
        self,
        ref: str = "",
        *,
        x: float | None = None,
        y: float | None = None,
    ) -> ActionResult:
        return await self._pointer("dblclick", ref=ref, x=x, y=y)

    async def right_click(
        self,
        ref: str = "",
        *,
        x: float | None = None,
        y: float | None = None,
    ) -> ActionResult:
        return await self._pointer("right_click", ref=ref, x=x, y=y)

    async def drag(
        self,
        ref: str = "",
        *,
        to: str = "",
        x: float | None = None,
        y: float | None = None,
        to_x: float | None = None,
        to_y: float | None = None,
    ) -> ActionResult:
        return await self._pointer(
            "drag", ref=ref, x=x, y=y, to=to, to_x=to_x, to_y=to_y
        )

    async def _pointer(
        self,
        verb: str,
        *,
        ref: str = "",
        x: float | None = None,
        y: float | None = None,
        to: str = "",
        to_x: float | None = None,
        to_y: float | None = None,
    ) -> ActionResult:
        err = await self._require_page()
        if err:
            return err
        assert self._page is not None
        use_xy = x is not None and y is not None
        info = None
        if not use_xy:
            if not ref or ref not in self._refs:
                return ActionResult(
                    ok=False,
                    output=f"Unknown ref {ref!r}. Call snapshot first.",
                )
            info = self._refs[ref]
            from arelis.browser.walls import attach_wall, detect_wall

            wall = detect_wall(click_label=info.text or info.name)
            if wall is not None and wall.kind == "pay" and verb != "hover":
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
            if use_xy:
                await _glow_xy(self._page, float(x), float(y))
                if verb == "hover":
                    await self._page.mouse.move(float(x), float(y))
                elif verb == "dblclick":
                    await self._page.mouse.dblclick(float(x), float(y))
                elif verb == "right_click":
                    await self._page.mouse.click(
                        float(x), float(y), button="right"
                    )
                elif verb == "drag":
                    if to_x is None or to_y is None:
                        return ActionResult(
                            ok=False,
                            output="drag with x,y needs to_x and to_y.",
                        )
                    await self._page.mouse.move(float(x), float(y))
                    await self._page.mouse.down()
                    await self._page.mouse.move(float(to_x), float(to_y))
                    await self._page.mouse.up()
            else:
                await _glow_ref(self._page, ref)
                loc = self._page.locator(f'[data-arelis-ref="{ref}"]')
                if verb == "hover":
                    await loc.first.hover(timeout=10_000)
                elif verb == "dblclick":
                    await loc.first.dblclick(timeout=10_000)
                elif verb == "right_click":
                    await loc.first.click(timeout=10_000, button="right")
                elif verb == "drag":
                    dest = self._page.locator(f'[data-arelis-ref="{to}"]')
                    await loc.first.drag_to(dest.first, timeout=10_000)
            label = (info.text if info is not None else "") or ref or "pixels"
            return ActionResult(
                ok=True,
                output=f"{verb} [{ref or 'xy'}] {label}".strip(),
                data={
                    "ref": ref,
                    "to": to,
                    "x": x,
                    "y": y,
                    "glowed": True,
                    "url": self._page.url,
                    "label": label,
                },
            )
        except Exception as exc:
            return self._fail_keep_or_drop(exc)

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
        if info.is_file_field():
            return ActionResult(
                ok=False,
                output="type=file is refused. Use browser(action=upload, path=…).",
                data={"code": "FILE_INPUT", "ref": ref},
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
        hands = await self._consume_hands()
        if hands is not None:
            return hands
        try:
            loc = self._page.locator(f'[data-arelis-ref="{ref}"]')
            await loc.first.fill(text, timeout=10_000)
            self._ptr_seen = await self._ptr_count()
            return ActionResult(
                ok=True,
                output=f"Typed into [{ref}]",
                data={"ref": ref, "length": len(text)},
            )
        except Exception as extra_exc:
            try:
                now = await self._ptr_count()
            except Exception:
                now = self._ptr_seen
            if now > self._ptr_seen:
                self._ptr_seen = now
                return _hands_result(
                    url=str(getattr(self._page, "url", "") or ""),
                    extra="You have the mouse. I stopped typing.",
                )
            return self._fail_keep_or_drop(extra_exc)

    async def tabs(
        self,
        *,
        select: int | str | None = None,
        op: str = "",
        url: str = "",
    ) -> ActionResult:
        from arelis.browser.places import format_tab_list, parse_tab_select, pick_tab

        err = await self._require_page()
        if err:
            return err
        assert self._context is not None
        try:
            kind = (op or "").strip().lower()
            idx, title_needle = parse_tab_select(select)
            if kind == "close" and title_needle:
                return ActionResult(
                    ok=False,
                    output=(
                        "Close is the current tab only. "
                        "Select the tab first, then tabs with tab=close. "
                        "No close-by-title."
                    ),
                    data={"code": "CLOSE_BY_TITLE"},
                )
            if kind == "new":
                page = await self._context.new_page()
                self._page = page
                target = (url or "").strip()
                if target:
                    await page.goto(target, wait_until="domcontentloaded")
                await page.bring_to_front()
                title = await page.title()
                return ActionResult(
                    ok=True,
                    output=f"Opened tab: {page.url}",
                    data={"url": page.url, "title": title, "active": "new"},
                )
            if kind == "close":
                pages = list(self._context.pages)
                current = self._page
                if current is None:
                    return ActionResult(ok=False, output="No tab to close.")
                if len(pages) <= 1:
                    await current.goto("about:blank", wait_until="domcontentloaded")
                    return ActionResult(
                        ok=True,
                        output="Closed the last tab — blank tab stays.",
                        data={"url": current.url, "title": await current.title()},
                    )
                close_i = pages.index(current) if current in pages else 0
                await current.close()
                remain = list(self._context.pages)
                self._page = remain[min(close_i, len(remain) - 1)]
                await self._page.bring_to_front()
                title = await self._page.title()
                return ActionResult(
                    ok=True,
                    output=f"Closed a tab. Now: {title}",
                    data={"url": self._page.url, "title": title},
                )
            rows: list[dict[str, Any]] = []
            for i, page in enumerate(self._context.pages):
                try:
                    title = await page.title()
                    href = page.url
                except Exception:
                    title, href = "?", "?"
                rows.append(
                    {
                        "index": i,
                        "title": title,
                        "url": href,
                        "active": page == self._page,
                    }
                )
            if idx is not None or title_needle:
                chosen, pick_err = pick_tab(rows, index=idx, title=title_needle)
                if pick_err or chosen is None:
                    return ActionResult(ok=False, output=pick_err or "No tab.")
                pages = list(self._context.pages)
                self._page = pages[chosen]
                await self._page.bring_to_front()
                title = await self._page.title()
                return ActionResult(
                    ok=True,
                    output=f"Selected tab {chosen}: {title}",
                    data={
                        "active": chosen,
                        "url": self._page.url,
                        "title": title,
                    },
                )
            return ActionResult(
                ok=True,
                output=format_tab_list(rows),
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

    async def wait(
        self,
        seconds: float = 1.0,
        *,
        url: str = "",
        text: str = "",
        heading: str = "",
    ) -> ActionResult:
        err = await self._require_page()
        if err:
            return err
        from arelis.browser.wait_for import (
            WAIT_POLL_S,
            clamp_wait_seconds,
            has_wait_needle,
            page_needles_hit,
            wait_output,
        )

        has = has_wait_needle(url=url, text=text, heading=heading)
        delay = clamp_wait_seconds(seconds, has_needle=has)
        if not has:
            await cooperative_wait(delay)
            landed = str(self._page.url or "") if self._page is not None else ""
            output, data = wait_output(
                hit=True, seconds=delay, landed_url=landed
            )
            return ActionResult(ok=True, output=output, data=data)
        deadline = time.monotonic() + delay
        signals: dict[str, str] = {}
        hit = False
        while True:
            signals = await self._page_needles()
            hit = page_needles_hit(
                landed_url=signals.get("url") or "",
                title=signals.get("title") or "",
                heading=signals.get("heading") or "",
                page_text=signals.get("text") or "",
                want_url=url,
                want_text=text,
                want_heading=heading,
            )
            if hit:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await cooperative_wait(min(WAIT_POLL_S, remaining))
        output, data = wait_output(
            hit=hit,
            seconds=delay,
            landed_url=signals.get("url") or "",
            want_url=url,
            want_text=text,
            want_heading=heading,
        )
        data["title"] = signals.get("title") or ""
        return ActionResult(ok=True, output=output, data=data)

    async def watch(
        self,
        *,
        url: str = "",
        text: str = "",
        heading: str = "",
    ) -> ActionResult:
        err = await self._require_page()
        if err:
            return err
        from arelis.browser.wait_for import has_wait_needle, page_needles_hit

        if not has_wait_needle(url=url, text=text, heading=heading):
            return ActionResult(
                ok=False,
                output="watch needs url, text, or heading to poll for.",
            )
        if getattr(self, "watch_stop", False):
            return ActionResult(
                ok=True,
                output="Watch cancelled.",
                data={
                    "hit": False,
                    "cancelled": True,
                    "url": str(self._page.url or "") if self._page is not None else "",
                },
            )
        signals = await self._page_needles()
        hit = page_needles_hit(
            landed_url=signals.get("url") or "",
            title=signals.get("title") or "",
            heading=signals.get("heading") or "",
            page_text=signals.get("text") or "",
            want_url=url,
            want_text=text,
            want_heading=heading,
        )
        landed = signals.get("url") or ""
        if hit:
            return ActionResult(
                ok=True,
                output=f"Watch hit — {landed}",
                data={
                    "hit": True,
                    "watch_hit": True,
                    "url": landed,
                    "title": signals.get("title") or "",
                },
            )
        return ActionResult(
            ok=True,
            output=f"Watch still waiting — {landed}",
            data={
                "hit": False,
                "url": landed,
                "title": signals.get("title") or "",
            },
        )

    async def download(self, path: str, *, ref: str = "") -> ActionResult:
        err = await self._require_page()
        if err:
            return err
        assert self._page is not None
        from arelis.browser.files import file_ready_payload

        await asyncio.to_thread(_ensure_parent_dir, path)
        try:
            if ref:
                info = self._refs.get(ref)
                if info is None:
                    return ActionResult(
                        ok=False,
                        output=f"Unknown ref {ref!r}. Call snapshot first.",
                    )
                await _glow_ref(self._page, ref)
                async with self._page.expect_download(timeout=15_000) as pending:
                    loc = self._page.locator(f'[data-arelis-ref="{ref}"]')
                    await loc.first.click(timeout=10_000)
                item = await pending.value
            else:
                return ActionResult(
                    ok=False,
                    output="download needs ref (the link or button that saves a file).",
                )
            suggested = str(item.suggested_filename or Path(path).name)
            await item.save_as(path)
            abs_path = await asyncio.to_thread(os.path.abspath, path)
            data = file_ready_payload(Path(abs_path), kind="download", title=suggested)
            data["ref"] = ref
            data["url"] = str(self._page.url or "")
            return ActionResult(
                ok=True,
                output=f"Downloaded {Path(abs_path).name}",
                data=data,
            )
        except Exception as exc:
            return self._fail_keep_or_drop(exc)

    async def upload(self, ref: str, path: str) -> ActionResult:
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
        if info.is_file_field() is False and str(info.type or "").lower() != "file":
            return ActionResult(
                ok=False,
                output=f"[{ref}] is not a file input. Snapshot and upload to type=file.",
                data={"code": "NOT_FILE", "ref": ref},
            )
        try:
            await _glow_ref(self._page, ref)
            loc = self._page.locator(f'[data-arelis-ref="{ref}"]')
            await loc.first.set_input_files(path, timeout=10_000)
            return ActionResult(
                ok=True,
                output=f"Uploaded {Path(path).name} to [{ref}]",
                data={"ref": ref, "path": path, "name": Path(path).name},
            )
        except Exception as exc:
            return self._fail_keep_or_drop(exc)

    async def pdf(self, path: str) -> ActionResult:
        err = await self._require_page()
        if err:
            return err
        assert self._page is not None
        from arelis.browser.files import file_ready_payload

        await asyncio.to_thread(_ensure_parent_dir, path)
        try:
            await self._page.pdf(path=path)
            abs_path = await asyncio.to_thread(os.path.abspath, path)
            title = ""
            try:
                title = await self._page.title()
            except Exception:
                title = ""
            data = file_ready_payload(Path(abs_path), kind="pdf", title=title)
            data["url"] = str(self._page.url or "")
            return ActionResult(
                ok=True,
                output=f"Saved tab PDF {Path(abs_path).name}",
                data=data,
            )
        except Exception as exc:
            return self._fail_keep_or_drop(exc)

    async def _page_needles(self) -> dict[str, str]:
        if self._page is None:
            return {}
        try:
            raw = await self._page.evaluate(
                """() => {
  const heading = ((document.querySelector('h1') || {}).innerText || '')
    .trim().slice(0, 120);
  const text = ((document.body && document.body.innerText) || '')
    .slice(0, 2500);
  return {
    url: location.href,
    title: document.title || '',
    heading,
    text,
  };
}"""
            )
        except Exception:
            return {"url": str(self._page.url or "")}
        if not isinstance(raw, dict):
            return {"url": str(self._page.url or "")}
        return {
            "url": str(raw.get("url") or self._page.url or ""),
            "title": str(raw.get("title") or ""),
            "heading": str(raw.get("heading") or ""),
            "text": str(raw.get("text") or ""),
        }

    async def _poll_leave_login(self, requested: str) -> None:
        """SPA bounce after a login URL still paints as /login for a beat."""
        from arelis.browser.wait_for import NAV_LOGIN_POLL_S, WAIT_POLL_S
        from arelis.browser.walls import is_login_url

        if self._page is None or not is_login_url(requested):
            return
        if not is_login_url(str(self._page.url or "")):
            return
        deadline = time.monotonic() + NAV_LOGIN_POLL_S
        while is_login_url(str(self._page.url or "")):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            await cooperative_wait(min(WAIT_POLL_S, remaining))

    async def settle(self, *, timeout_s: float = SETTLE_S) -> ActionResult:
        """Wait until a result-like link exists, or the cap. Not networkidle."""
        err = await self._require_page()
        if err:
            return err
        assert self._page is not None
        cap = max(0.4, min(float(timeout_s), 8.0))
        deadline = time.monotonic() + cap
        try:
            while True:
                try:
                    hit = await self._page.evaluate(SETTLE_HAS_RESULT_JS)
                except Exception:
                    hit = False
                if hit:
                    return ActionResult(
                        ok=True, output="Settled.", data={"settled": True}
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return ActionResult(
                        ok=True,
                        output="Settled (timeout).",
                        data={"settled": False},
                    )
                await cooperative_wait(min(SETTLE_POLL_S, remaining))
        except Exception as exc:
            self._page = None
            return _playwright_fail(exc)

    async def back(self) -> ActionResult:
        err = await self._require_page()
        if err:
            return err
        assert self._page is not None
        try:
            await self._page.go_back(wait_until="domcontentloaded")
            title = await self._page.title()
            return ActionResult(
                ok=True,
                output=f"Went back to {self._page.url}",
                data={"url": self._page.url, "title": title},
            )
        except Exception as exc:
            self._page = None
            return _playwright_fail(exc)

    async def forward(self) -> ActionResult:
        err = await self._require_page()
        if err:
            return err
        assert self._page is not None
        try:
            await self._page.go_forward(wait_until="domcontentloaded")
            title = await self._page.title()
            return ActionResult(
                ok=True,
                output=f"Went forward to {self._page.url}",
                data={"url": self._page.url, "title": title},
            )
        except Exception as exc:
            self._page = None
            return _playwright_fail(exc)

    async def reload(self) -> ActionResult:
        err = await self._require_page()
        if err:
            return err
        assert self._page is not None
        try:
            await self._page.reload(wait_until="domcontentloaded")
            title = await self._page.title()
            return ActionResult(
                ok=True,
                output=f"Reloaded {self._page.url}",
                data={"url": self._page.url, "title": title},
            )
        except Exception as exc:
            self._page = None
            return _playwright_fail(exc)
