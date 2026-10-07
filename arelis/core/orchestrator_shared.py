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

# Absolute paths typed in chat that may need a session read grant.
_ABS_PATH_TOKEN = re.compile(
    r"(?P<path>"
    r"(?:[A-Za-z]:[\\/][^\s\"'<>|]+)"
    r"|(?:/(?:Users|home|tmp|var|etc|opt)[^\s\"'<>|]*))"
)

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
    """True when research is a different Ollama tag from fast."""
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
        from arelis.llm.ollama import same_ollama_model

        return not same_ollama_model(
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
