"""Open and close Arelis tiles from speech — the View menu, in words."""

from __future__ import annotations

import re
from typing import Any

# Canonical names match View-menu actions and TileTool.enum.
TILE_NAMES: tuple[str, ...] = (
    "thinking",
    "workspace",
    "history",
    "notifications",
    "camera",
    "contacts",
    "calendar",
    "world",
)

# Longer aliases first so "past conversations" wins over a stray "history" later.
_ALIASES: tuple[tuple[str, str], ...] = (
    ("notifications", r"notifications?|alerts?|notify(?:\s+center)?"),
    ("thinking", r"thinking|thoughts"),
    (
        "workspace",
        r"workspace|work\s*space|(?:the\s+)?desk|(?:file|files)\s+(?:tile|panel|dock)|the\s+editor",
    ),
    ("history", r"history|(?:past|old)\s+(?:chats?|conversations?)"),
    ("camera", r"camera|webcam|web\s*cam"),
    ("contacts", r"contacts?|address\s+book"),
    ("calendar", r"calendar|agenda"),
    (
        "world",
        r"world|reality|solar\s+lab|solar\s+system|toy\s+area|"
        r"hands(?:\s+sandbox)?|sandbox",
    ),
)


def _alias_union() -> str:
    return "|".join(f"(?:{pat})" for _name, pat in _ALIASES)


_OPEN_VERB = (
    r"(?:open|show|display|launch|pop\s+up|bring\s+up|pull\s+up|"
    r"show\s+me|bring\s+me)"
)
_CLOSE_VERB = r"(?:close|hide|dismiss|shut|put\s+away)"
_DET = r"(?:(?:up|me|the|my|our|this|that)\s+)*"

_OPEN = re.compile(
    r"(?i)\b"
    + _OPEN_VERB
    + r"\s+"
    + _DET
    + r"(?P<tile>"
    + _alias_union()
    + r")"
    + r"(?:\s+(?:tile|window|panel|dock|app))?\b"
)
_CLOSE = re.compile(
    r"(?i)\b"
    + _CLOSE_VERB
    + r"\s+"
    + _DET
    + r"(?P<tile>"
    + _alias_union()
    + r")"
    + r"(?:\s+(?:tile|window|panel|dock|app))?\b"
)
_BARE_CLOSE = re.compile(
    r"(?i)^\s*(?:close|hide|dismiss|shut|put\s+away)\s+"
    r"(?:it|them|that|this)(?:\s+(?:tile|window|panel|dock))?"
    r"[.!]?\s*$"
)
_NOT_TILE = re.compile(
    r"(?i)("
    r"\bin\s+(?:the\s+)?(?:browser|chrome|edge|firefox)\b|"
    r"\bwebsite\b|"
    r"calendar\.google|"
    r"\b(?:this|that|the|a)\s+file\b|"
    r"\bthe\s+room\b|"
    r"\bgit\s+history\b|"
    r"\bcommit\s+history\b|"
    r"\bsettings\b|"
    r"\byoutube\b|"
    r"https?://"
    r")"
)


_SOLAR_PAGE = re.compile(r"(?i)\bsolar\s+(?:lab|system)\b")
_HANDS_PAGE = re.compile(r"(?i)\b(?:toy\s+area|hands(?:\s+sandbox)?|sandbox)\b")


def world_page_for(text: str) -> str:
    """solar / hands when the words name a page; empty means Reality's chooser."""
    raw = text or ""
    if _SOLAR_PAGE.search(raw):
        return "solar"
    if _HANDS_PAGE.search(raw):
        return "hands"
    return ""


def _canonical(raw: str) -> str:
    blob = (raw or "").casefold().strip()
    for name, pat in _ALIASES:
        if re.fullmatch(pat, blob, flags=re.I):
            return name
    return ""


def match_tile_intent(text: str) -> tuple[str, str] | None:
    """('open'|'close', canonical name) or ('close', '') for 'close them'.

    Empty name means reuse the last tile the tool opened. Calendar phrases
    that already match agenda open/close still return calendar here; the
    agent loop prefers agenda when that tool is registered.
    """
    raw = (text or "").strip()
    if not raw or _NOT_TILE.search(raw):
        return None
    if _BARE_CLOSE.match(raw):
        return ("close", "")
    closed = _CLOSE.search(raw)
    if closed:
        name = _canonical(closed.group("tile") or "")
        if not name:
            return None
        if name == "calendar":
            from arelis.core.agenda_complete import looks_like_calendar_delete

            if looks_like_calendar_delete(raw) or re.search(
                r"(?i)\b(?:calendar|agenda)\s+(?:event|meeting)\b", raw
            ):
                return None
        return ("close", name)
    opened = _OPEN.search(raw)
    if opened:
        name = _canonical(opened.group("tile") or "")
        if not name:
            return None
        if name == "calendar":
            from arelis.core.agenda_complete import (
                looks_like_calendar_create,
                looks_like_calendar_delete,
                looks_like_calendar_read,
            )

            if (
                looks_like_calendar_read(raw)
                or looks_like_calendar_create(raw)
                or looks_like_calendar_delete(raw)
            ):
                return None
        return ("open", name)
    return None


def tile_tool_args(text: str, *, last_name: str = "") -> dict[str, Any] | None:
    hit = match_tile_intent(text)
    if hit is None:
        return None
    action, name = hit
    if not name:
        name = (last_name or "").strip()
    if not name:
        return None
    args: dict[str, Any] = {"action": action, "name": name}
    if name == "world":
        page = world_page_for(text)
        if page:
            args["page"] = page
    return args
