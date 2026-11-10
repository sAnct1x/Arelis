"""The handful of names every orchestrator mixin needs. One copy.

When `Orchestrator` was split into mixins, this block went along for the ride
into each new file. It ended up defined four times, in `orchestrator.py`,
`orchestrator_turns.py`, `orchestrator_confirm.py` and `orchestrator_slash.py`,
byte for byte, and used in exactly one of them.

That is worse than untidy. `TOOL_CMD` decides which tools a typed slash command
may run without a confirm card, and the comment on it explains at length why
`send_email` and `send_sms` are absent. Four copies of that list is four places
to add a tool and three places to forget, with the safety argument sitting next
to a copy nobody reads.
"""

from __future__ import annotations

import re
from pathlib import Path

# Absolute paths typed in chat that may need a session read grant.
# Paths with spaces (a Desktop folder named "Arelis 0.3.5 test files") must
# be included; a token that stops at the first space never issues the Allow
# card for the file the user typed.
_ABS_PATH_TOKEN = re.compile(
    r"(?P<path>"
    r"(?:[A-Za-z]:[\\/][^\s\"'<>|]+)"
    r"|(?:/(?:Users|home|tmp|var|etc|opt)[^\s\"'<>|]*))"
)
_ABS_PATH_START = re.compile(
    r"[A-Za-z]:[\\/]|/(?:Users|home|tmp|var|etc|opt)/"
)
_FILE_EXT = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,7}$")
_PATH_ILLEGAL = frozenset("\"'<>|\r\n\t")


def _scan_typed_path(text: str, start: int) -> str | None:
    """Longest typed file path starting at ``start``, spaces allowed."""
    if start < len(text) and text[start] in "\"'":
        quote = text[start]
        end = text.find(quote, start + 1)
        if end < 0:
            return None
        body = text[start + 1 : end].strip().rstrip(".,);]")
        return body or None
    i = start
    n = len(text)
    while i < n and text[i] not in _PATH_ILLEGAL:
        i += 1
        candidate = text[start:i].rstrip(".,);]")
        if not _FILE_EXT.search(candidate):
            continue
        end = start + len(candidate)
        nxt = text[end] if end < n else ""
        if nxt.isalnum() or nxt in "\\/":
            continue
        if nxt == "." and end + 1 < n and text[end + 1].isalnum():
            continue
        return candidate
    return None


def typed_absolute_paths(text: str) -> list[str]:
    """Absolute paths typed in a message, including ones that contain spaces.

    The returned strings are the typed forms, punctuation at the end already
    stripped. Existence is left to the caller so a missing file does not
    become a parent-folder grant.
    """
    raw = text or ""
    found: list[str] = []
    seen: set[str] = set()

    def _norm(token: str) -> str:
        return token.replace("\\", "/").lower()

    def _covers(long: str, short: str) -> bool:
        # Only a real path child covers a prefix. A space-separated tail
        # ("folder and convert sample.nc") must not drop the shorter typed
        # prefix, which is kept as a fallback for the existence check.
        a, b = _norm(long), _norm(short)
        if a == b:
            return True
        return a.startswith(b) and (len(a) == len(b) or a[len(b)] in "/\\")

    def _add(token: str | None) -> None:
        cleaned = (token or "").strip().rstrip(".,);]")
        if not cleaned:
            return
        key = _norm(cleaned)
        if key in seen:
            return
        for i, existing in enumerate(found):
            if _covers(existing, cleaned):
                return
            if _covers(cleaned, existing):
                seen.discard(_norm(existing))
                found[i] = cleaned
                seen.add(key)
                return
        seen.add(key)
        found.append(cleaned)

    index = 0
    while True:
        match = _ABS_PATH_START.search(raw, index)
        if match is None:
            break
        # A quote immediately before the start is a quoted path.
        origin = match.start()
        if origin > 0 and raw[origin - 1] in "\"'":
            origin -= 1
        token = _scan_typed_path(raw, origin)
        if token:
            _add(token)
            index = origin + (len(token) if origin == match.start() else len(token) + 2)
            if index <= match.start():
                index = match.end()
            continue
        index = match.end()
    for match in _ABS_PATH_TOKEN.finditer(raw):
        _add(match.group("path"))
    return found


def longest_existing_typed_paths(tokens: list[str]) -> list[str]:
    """Keep the longest existing token among overlapping typed paths.

    Shorter space-delimited prefixes stay only when no longer overlapping
    token exists. A missing file is not walked up to a parent folder that
    was not itself a typed token.
    """
    existing: list[str] = []
    seen: set[str] = set()
    for raw in tokens:
        cleaned = (raw or "").strip()
        if not cleaned:
            continue
        try:
            path = Path(cleaned).expanduser().resolve()
        except OSError:
            continue
        if not path.exists():
            continue
        key = cleaned.replace("\\", "/").lower()
        if key in seen:
            continue
        seen.add(key)
        existing.append(cleaned)

    def _overlaps_longer(long: str, short: str) -> bool:
        a, b = long.replace("\\", "/").lower(), short.replace("\\", "/").lower()
        if a == b or not a.startswith(b):
            return False
        return a[len(b)] in "/\\ "

    kept: list[str] = []
    for raw in existing:
        if any(_overlaps_longer(other, raw) for other in existing):
            continue
        kept.append(raw)
    return kept


ROLES: set[str] = {"fast", "research"}

# "switch roles to research, then I got a prompt" is the chip, not a tile
# and not a room. The word role/mode/chip has to be in the sentence, or the
# line has to be only the switch. "switch to research the muon papers" stays
# a normal turn.
_ROLE_SWITCH = re.compile(
    r"""(?ix)
    ^\s*
    (?:hey[\s,!.]*)?
    (?:please\s+)?
    (?:can\s+you\s+|could\s+you\s+)?
    (?:
        switch(?:\s+the)?\s+roles?\s+to\s+
      | switch\s+to\s+(?:the\s+)?
      | (?:change|set)(?:\s+the)?\s+(?:role|mode|chip)\s+to\s+
      | (?:use|pick)\s+(?:the\s+)?
    )
    (?P<role>fast|research)
    (?:\s+(?:role|mode|chip))?
    \b
    (?P<rest>.*)
    $
    """
)
_ROLE_HANDOFF = re.compile(
    r"""(?ix)
    ^(?:i(?:\s+'?ve|\s+have|\s+got)?|got|there(?:'s|\s+is))\s+
    (?:a\s+|some\s+)?(?:good\s+|new\s+)?
    (?:prompt|question|questions|ask|task)\b
    """
)


def _role_rest(rest: str | None) -> str:
    cleaned = re.sub(r"(?i)^[\s,.]+(?:and|then)?[\s,.]*", "", rest or "")
    cleaned = re.sub(r"(?i)^(?:and|then)[\s,.]+", "", cleaned)
    return cleaned.strip()


def match_role_switch(text: str) -> tuple[str, str] | None:
    """Return ``(role, remainder)`` when the line asks to change the chip.

    Remainder is what to run after the switch. Empty when the rest is only
    "I have a prompt coming". None when the line is a normal request that
    happens to say "switch to".
    """
    raw = (text or "").strip()
    found = _ROLE_SWITCH.match(raw)
    if found is None:
        return None
    role = found.group("role").lower()
    rest = _role_rest(found.group("rest"))
    head = raw[: found.end("role")]
    after = raw[found.end("role") :]
    named = bool(re.search(r"(?i)\b(?:roles?|mode|chip)\b", head)) or bool(
        re.match(r"(?i)\s+(?:role|mode|chip)\b", after)
    )
    if named:
        return role, rest
    if rest and not _ROLE_HANDOFF.match(rest):
        return None
    return role, ""


def research_needs_vram_swap(router: object) -> bool:
    """True when research is a different model name from fast."""
    same = getattr(router, "same_chat_weights", None)
    if callable(same):
        try:
            return not bool(same("fast", "research"))
        except Exception:
            return True
    model_for = getattr(router, "model_for", None)
    if not callable(model_for):
        return True
    try:
        from arelis.llm.wire import same_model

        return not same_model(
            str(model_for("fast") or ""),
            str(model_for("research") or ""),
        )
    except Exception:
        return True


def comms_bypasses_sticky(text: str) -> bool:
    """True when this turn is SMS/email/agenda and must not keep a sticky hold."""
    raw = (text or "").strip()
    if not raw:
        return False
    from arelis.core.agenda_complete import (
        looks_like_calendar_create,
        looks_like_calendar_delete,
        looks_like_calendar_read,
    )
    from arelis.core.email_complete import looks_like_compose_email
    from arelis.core.sms_complete import parse_sms_utterance

    if parse_sms_utterance(raw) is not None:
        return True
    if looks_like_compose_email(raw):
        return True
    from arelis.core.intent_catalog import EARTH_STATUS, SOLAR_STATUS

    if SOLAR_STATUS.matches(raw) or EARTH_STATUS.matches(raw):
        return True
    return (
        looks_like_calendar_create(raw)
        or looks_like_calendar_delete(raw)
        or looks_like_calendar_read(raw)
    )


# Slash commands run a tool directly, bypassing the model and the confirm card.
# That bypass is intentional and is scoped to text the user typed: naming a tool
# and its arguments explicitly is itself the confirmation.
#
# send_email and send_sms are deliberately absent. Every other tool here is
# undoable or local; a sent message is neither, and the card showing the
# recipient and body is the only gate it has. There is no version of typing it
# out that replaces reading what is about to leave the machine.
TOOL_CMD = re.compile(
    r"^/(?P<tool>web_search|web_fetch|scrape|workspace|analyze|image"
    r"|inbox|schedule)(?:\s+(?P<args>.+))?$",
    re.IGNORECASE,
)
