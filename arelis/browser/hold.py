"""Pause latch for the Drive strip.

Stop still cancels the turn. Pause only freezes glow / wait / the next tool
step; the page stays. The UI and the orchestrator share this module flag so a
click already in its glow beat can hold without extra plumbing through Playwright.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

_paused = False
_drive_labels: dict[str, str] = {}


def set_drive_labels(labels: dict[str, str] | None) -> None:
    """Last snapshot labels, so the Drive strip can say 'Sign in' not 'e11'."""
    global _drive_labels
    _drive_labels = dict(labels or {})


def set_paused(on: bool) -> None:
    global _paused
    _paused = bool(on)


def is_paused() -> bool:
    return _paused


async def cooperative_wait(seconds: float) -> None:
    """Sleep that freezes while paused. Task cancel still interrupts the wait."""
    end = time.monotonic() + max(0.0, float(seconds))
    while True:
        while is_paused():  # noqa: ASYNC110 — UI thread toggles a bool
            await asyncio.sleep(0.08)
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        await asyncio.sleep(min(0.08, remaining))


def format_drive_status(action: str, args: dict[str, Any] | None = None) -> str:
    """One line for the Drive strip from a browser tool call."""
    args = args or {}
    act = (action or "").strip().lower()
    ref = str(args.get("ref") or "").strip()
    url = str(args.get("url") or args.get("target") or "").strip()
    if url.startswith("http"):
        host = url.split("://", 1)[-1].split("/", 1)[0]
    else:
        host = url[:48]
    if act == "click":
        label = str(args.get("text") or args.get("label") or "").strip()
        if not label and ref:
            label = (_drive_labels.get(ref) or "").strip()
        if label:
            return f"about to click {label[:40]}…"
        return f"about to click {ref}…" if ref else "about to click…"
    if act == "back":
        return "going back…"
    if act == "open":
        return f"opening {host}…" if host else "opening…"
    if act == "navigate":
        return f"going to {host}…" if host else "navigating…"
    if act == "type":
        into = str(args.get("into") or "").strip()
        where = into or ref
        return f"typing in {where}…" if where else "typing…"
    if act == "forward":
        return "going forward…"
    if act == "reload":
        return "reloading…"
    if act == "find":
        q = str(args.get("text") or args.get("query") or "").strip()
        return f"finding {q[:40]}…" if q else "finding…"
    if act == "scroll":
        return "scrolling…"
    if act == "press":
        key = str(args.get("key") or "").strip() or "key"
        return f"pressing {key}…"
    if act == "select":
        return f"selecting on {ref}…" if ref else "selecting…"
    if act == "wait":
        return "waiting…"
    if act == "snapshot":
        return "reading the page…"
    if act == "read":
        return "reading this tab…"
    if act == "maps":
        dest = str(args.get("destination") or args.get("url") or "").strip()
        label = dest[:40] if dest else "maps"
        return f"opening maps to {label}…"
    if act == "search":
        q = str(args.get("query") or args.get("text") or "").strip()
        label = q[:40] if q else "search"
        return f"searching {label}…"
    if act == "reserve":
        place = str(args.get("place") or args.get("query") or "").strip()
        label = place[:40] if place else "a table"
        return f"booking {label}…"
    if act == "screenshot":
        return "capturing…"
    if act == "tabs":
        tab = str(args.get("tab") or "").strip().lower()
        if tab == "new":
            return "opening a tab…"
        if tab == "close":
            return "closing a tab…"
        return "checking tabs…"
    if act == "relaunch":
        return "restarting her Chrome…"
    return "driving…"


def format_drive_done(
    action: str,
    args: dict[str, Any] | None = None,
    *,
    data: dict[str, Any] | None = None,
) -> str:
    """Past-tense Drive line after a step. Empty means keep the about-to copy."""
    args = args or {}
    data = data or {}
    act = (action or "").strip().lower()
    label = str(
        data.get("label") or args.get("text") or args.get("label") or ""
    ).strip()
    if act == "click":
        return f"clicked {label[:40]}" if label else "clicked"
    if act == "search":
        q = str(args.get("query") or args.get("text") or data.get("query") or "").strip()
        return f"searched {q[:40]}" if q else "searched"
    if act == "open":
        return "opened"
    if act == "navigate":
        return "opened the page"
    if act == "type":
        return "typed"
    if act == "maps":
        dest = str(data.get("destination") or args.get("destination") or "").strip()
        return f"opened maps to {dest[:40]}" if dest else "opened maps"
    if act == "read":
        return "read this tab"
    if act == "snapshot":
        return "read the page"
    return ""
