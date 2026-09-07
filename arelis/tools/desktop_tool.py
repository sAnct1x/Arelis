"""Drive the user's Windows session (no shell, no OS trees)."""

from __future__ import annotations

import logging
from typing import Any

from arelis.browser.pixels import parse_xy
from arelis.desktop.session import DesktopSession
from arelis.tools.base import ToolResult

log = logging.getLogger(__name__)

_ACTIONS = (
    "open",
    "windows",
    "monitors",
    "focus",
    "snapshot",
    "read",
    "click",
    "type",
    "press",
    "hotkey",
    "scroll",
    "screenshot",
    "wait",
)


class DesktopTool:
    name = "desktop"
    description = (
        "Drive the user's Windows session — open apps, switch windows, "
        "type, click. Not a shell and not her Chrome (use browser for the web). "
        "Prefer this when they ask to open a Windows app, or to look at "
        "something on a monitor (a book, a problem, a window). "
        "Actions: open (app name / Start Menu title — never a raw .exe path), "
        "windows (list titles), monitors (list displays), "
        "focus (bring one forward), "
        "snapshot (named controls in the focused window), "
        "read (compact visible names), "
        "click(ref or text or nth; x,y only after screenshot then vision "
        "this turn), type(text, optional into= field), press(key), "
        "hotkey(ctrl+s), scroll, screenshot (monitor or window title — "
        "grabs then reads text; vision only for a diagram), wait. "
        "You plan the drive: open notepad, type hello. "
        "Never start cmd, PowerShell, regedit, or anything that wants "
        "Administrator. Never type passwords. Stop on Pay / delete / "
        "Empty Recycle Bin / Uninstall / Format — that is their turn."
    )
    risk = "side_effect"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(_ACTIONS),
                "description": (
                    "open / windows / monitors / focus / snapshot / read / "
                    "click / type / press / hotkey / scroll / screenshot / wait"
                ),
            },
            "target": {
                "type": "string",
                "description": (
                    "open/focus: app or window name. "
                    "screenshot: monitor (1, left, right, primary) or a "
                    "window title (the book, Adobe, Kindle)."
                ),
            },
            "find": {
                "type": "string",
                "description": (
                    "screenshot: problem number or paragraph to resolve "
                    "on the still (e.g. 2.22, second paragraph)."
                ),
            },
            "ref": {
                "type": "string",
                "description": "Control ref from snapshot (e.g. d3).",
            },
            "text": {
                "type": "string",
                "description": "click: visible label. type: string to type.",
            },
            "into": {
                "type": "string",
                "description": "type: field label to focus first.",
            },
            "key": {
                "type": "string",
                "description": "press: Enter, Escape, Tab, arrows, Space.",
            },
            "keys": {
                "type": "string",
                "description": "hotkey: ctrl+s, alt+f4 (refused if destructive).",
            },
            "nth": {
                "type": "integer",
                "description": "click: 1-based match.",
            },
            "direction": {
                "type": "string",
                "description": "scroll: up / down.",
            },
            "amount": {
                "type": "integer",
                "description": "scroll notches (default 3).",
            },
            "seconds": {
                "type": "number",
                "description": "wait: 0.2-8s (default 1).",
            },
            "x": {
                "type": "number",
                "description": "Pixel X. Only after screenshot then vision this turn.",
            },
            "y": {
                "type": "number",
                "description": "Pixel Y. Only after screenshot then vision this turn.",
            },
        },
        "required": ["action"],
    }

    def __init__(
        self,
        session: DesktopSession | None = None,
        *,
        aliases: dict[str, str] | None = None,
    ) -> None:
        self.session = session or DesktopSession(aliases=aliases)
        if aliases:
            self.session.aliases.update(aliases)
        self.pixel_ok = False

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip().lower()
        if action not in _ACTIONS:
            return ToolResult(
                ok=False,
                output="Unknown action {!r}. Use: {}.".format(
                    action, ", ".join(_ACTIONS)
                ),
            )
        target = str(kwargs.get("target") or kwargs.get("url") or "").strip()
        try:
            if action == "open":
                result = await self.session.open(target)
            elif action == "windows":
                result = await self.session.windows()
            elif action == "monitors":
                result = await self.session.monitors()
            elif action == "focus":
                result = await self.session.focus(target)
            elif action == "snapshot":
                result = await self.session.snapshot()
            elif action == "read":
                result = await self.session.read()
            elif action == "type":
                text = str(kwargs.get("text") or "")
                if not text:
                    return ToolResult(ok=False, output="type needs text.")
                result = await self.session.type_into(
                    text,
                    into=str(kwargs.get("into") or ""),
                    ref=str(kwargs.get("ref") or ""),
                )
            elif action == "press":
                key = str(kwargs.get("key") or kwargs.get("text") or "").strip()
                if not key:
                    return ToolResult(ok=False, output="press needs key.")
                result = await self.session.press(key)
            elif action == "hotkey":
                combo = str(kwargs.get("keys") or kwargs.get("key") or "").strip()
                if not combo:
                    return ToolResult(ok=False, output="hotkey needs keys (e.g. ctrl+s).")
                result = await self.session.hotkey(combo)
            elif action == "click":
                x, y = parse_xy(kwargs)
                try:
                    nth = int(kwargs.get("nth") or 0)
                except (TypeError, ValueError):
                    nth = 0
                result = await self.session.click(
                    ref=str(kwargs.get("ref") or ""),
                    text=str(kwargs.get("text") or ""),
                    nth=nth,
                    x=x,
                    y=y,
                    pixel_ok=self.pixel_ok,
                )
            elif action == "scroll":
                result = await self.session.scroll(
                    str(kwargs.get("direction") or "down"),
                    amount=int(kwargs.get("amount") or 3),
                )
            elif action == "screenshot":
                result = await self.session.screenshot(
                    target,
                    find=str(kwargs.get("find") or ""),
                )
            else:
                result = await self.session.wait(float(kwargs.get("seconds") or 1.0))
        except Exception as exc:
            log.debug("desktop %s failed", action, exc_info=True)
            return ToolResult(ok=False, output=str(exc))
        return ToolResult(ok=result.ok, output=result.output, data=result.data)
