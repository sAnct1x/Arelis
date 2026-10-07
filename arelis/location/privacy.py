"""Keep the saved place out of visible reasoning and logs.

The saved city and postal code used to ride in a system line on every turn, so a
reasoning model quoted them in its thinking text and the Thinking dock showed
them. Two controls, both under ``location.privacy`` in config:

``prompt_detail``  how much of the place the model sees every turn.
    off   (default) timezone only. A tool that needs the place asks for it.
    city  city, region, country. No postal code, no coordinates.
    full  everything the resolver knows (the old behaviour).

``redact_display``  replace the saved city, postal code and coordinates with
    ``[location]`` in streamed reasoning, in the Thinking dock (plain status
    lines, tool arguments, and tool results shown there), and in the text logs.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from typing import Any

PROMPT_DETAILS = ("off", "city", "full")
DEFAULT_PROMPT_DETAIL = "off"
REPLACEMENT = "[location]"
_MIN_TERM = 3
_TTL_S = 2.0


def privacy_config(config: dict[str, Any] | None) -> dict[str, Any]:
    loc = (config or {}).get("location") or {}
    raw = loc.get("privacy") if isinstance(loc, dict) else None
    return raw if isinstance(raw, dict) else {}


def prompt_detail(config: dict[str, Any] | None) -> str:
    """off | city | full. Anything unrecognised is the safe answer, off."""
    raw = str(privacy_config(config).get("prompt_detail") or DEFAULT_PROMPT_DETAIL)
    raw = raw.strip().lower()
    return raw if raw in PROMPT_DETAILS else DEFAULT_PROMPT_DETAIL


def redact_display_enabled(config: dict[str, Any] | None) -> bool:
    return bool(privacy_config(config).get("redact_display", True))


def location_terms(location: Any) -> list[str]:
    """Strings that identify the saved place, longest first."""
    if location is None:
        return []
    terms: list[str] = []
    for name in ("city", "postal_code"):
        value = " ".join(str(getattr(location, name, "") or "").split())
        if len(value) >= _MIN_TERM:
            terms.append(value)
    lat = getattr(location, "latitude", None)
    lon = getattr(location, "longitude", None)
    if lat is not None and lon is not None:
        try:
            terms.extend([f"{float(lat):.4f}", f"{float(lon):.4f}"])
        except (TypeError, ValueError):
            pass
    return sorted(set(terms), key=lambda t: (-len(t), t))


class LocationRedactor:
    """Replaces the saved place in text. Terms are re-read so edits apply live."""

    def __init__(self, get_location: Callable[[], Any]) -> None:
        self._get = get_location
        self._terms: list[str] = []
        self._pattern: re.Pattern[str] | None = None
        self._at = float("-inf")

    def _refresh(self) -> None:
        now = time.monotonic()
        if now - self._at < _TTL_S:
            return
        self._at = now
        try:
            terms = location_terms(self._get())
        except Exception:
            # A resolver hiccup must not break logging or the thinking stream;
            # with no terms the text passes through unchanged this tick.
            terms = []
        if terms == self._terms:
            return
        self._terms = terms
        if not terms:
            self._pattern = None
            return
        alts = "|".join(re.escape(t) for t in terms)
        self._pattern = re.compile(rf"(?<!\w)(?:{alts})(?!\w)", re.IGNORECASE)

    def redact(self, text: str) -> str:
        if not text:
            return text
        self._refresh()
        if self._pattern is None:
            return text
        return self._pattern.sub(REPLACEMENT, text)

    def partial_suffix(self, text: str) -> int:
        """Length of a trailing slice that could still grow into a term."""
        self._refresh()
        if not self._terms:
            return 0
        low = text.lower()
        longest = max(len(t) for t in self._terms)
        for size in range(min(len(low), longest - 1), 0, -1):
            tail = low[-size:]
            if any(t.lower().startswith(tail) for t in self._terms):
                return size
        return 0


class StreamRedactor:
    """Redacts a token stream, holding back only a possible half-written term."""

    def __init__(self, redactor: LocationRedactor | None) -> None:
        self._r = redactor
        self._buf = ""

    def feed(self, chunk: str) -> str:
        if self._r is None:
            return chunk
        text = self._r.redact(self._buf + chunk)
        hold = self._r.partial_suffix(text)
        if hold:
            self._buf = text[-hold:]
            return text[:-hold]
        self._buf = ""
        return text

    def flush(self) -> str:
        if self._r is None or not self._buf:
            return ""
        out = self._r.redact(self._buf)
        self._buf = ""
        return out


_active: LocationRedactor | None = None


def install(config: dict[str, Any] | None) -> LocationRedactor | None:
    """Set the process-wide redactor from config. None when switched off."""
    global _active
    location = (config or {}).get("_location")
    if location is None or not redact_display_enabled(config):
        _active = None
        return None

    def _get() -> Any:
        snap = getattr(location, "snapshot", None)
        return snap() if callable(snap) else location

    _active = LocationRedactor(_get)
    return _active


def current() -> LocationRedactor | None:
    return _active


def redact(text: str) -> str:
    return _active.redact(text) if _active is not None else text


class LocationLogFilter(logging.Filter):
    """Handler filter: scrub the saved place out of a record before it is written."""

    def filter(self, record: logging.LogRecord) -> bool:
        redactor = _active
        if redactor is None:
            return True
        try:
            message = record.getMessage()
        except Exception:
            # A log record that cannot render must not be dropped or loop back
            # into logging from inside a filter; write it as it is.
            return True
        cleaned = redactor.redact(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = None
        return True
