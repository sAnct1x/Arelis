"""Wake-phrase matching for always-listen mode.

Whisper will not spell the name the same way every time. Accept a short list of
spellings and return the remainder of the utterance, or None when this was not
a wake.

The compound phrase is required: "Hey" (or Whisper's "Hay" / leading "Pay")
plus the name. Bare "Arelis", "Hi Arelis", and "Okay Arelis" do not wake —
those fire too easily on Discord and room talk. Leading Whisper fillers
("and", "uh", …) are ignored. A long clip may still wake if it contains
"Hey Arelis" later; a bare name later in the transcript does not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Name spellings Whisper commonly produces for ah-REL-is / uh-rell-iss.
# Includes the double-r "Arrelis" it actually writes. Excludes cousins that
# match ordinary speech ("or Ellis", "air Elise").
_NAME = (
    r"(?:airelyse|airelease|aurelyse|aurelis|arellis|"
    r"arelyse|areliss|arelis|arrellis|arreliss|arrelis|"
    r"arrelas|arella|relus|relis)"
)

# Junk Whisper often sticks before the greeting on noisy/long clips.
_FILLER = (
    r"(?:and|uh|um|er|ah|oh|so|well|the|a|yeah|like|hmm|mm|"
    r"you\s+know)\s*,?\s*"
)

# Required. "hay" is a frequent Whisper misspelling of "hey".
# "hi" / "ok" / "okay" are too common in calls to be wake greetings.
_GREETING = r"(?:hey|hay)\s*,?\s*"
# "pay" is hey-as-heard, but only at the start — mid-clip "pay Aurelis"
# is ordinary speech.
_GREETING_START = r"(?:hey|hay|pay)\s*,?\s*"
# Whisper also writes "Hey a relus" / "Pay a relus".
_ARTICLE = r"(?:a\s+)?"

# Strict: start of string after optional fillers + required greeting.
_WAKE_AT_START = re.compile(
    rf"^\s*(?:{_FILLER}){{0,6}}{_GREETING_START}{_ARTICLE}{_NAME}\b[\s,.\?!;:]*",
    re.IGNORECASE,
)

# Anywhere: greeting+name only (used when start match fails).
_WAKE_ANYWHERE = re.compile(
    rf"{_GREETING}{_ARTICLE}{_NAME}\b[\s,.\?!;:]*",
    re.IGNORECASE,
)

# Soft hint that Whisper heard the compound phrase but match_wake still failed.
_NAME_HINT = re.compile(
    r"(?i)\b(?:hey|hay|pay)\s+(?:a\s+)?(?:airelyse|airelease|aurelis|aurelyse|"
    r"arellis|arelyse|areliss|arelis|arrelis|arrelas|arella|relus|relis)\b"
)


@dataclass(frozen=True)
class WakeResult:
    """Outcome of transcribing one idle wake clip."""

    matched: bool
    remainder: str
    heard: str


def _peel_leading_wakes(rest: str) -> str:
    """Strip repeated wake phrases so they never become a user turn."""
    while True:
        again = _WAKE_AT_START.match(rest)
        if again is None:
            again = re.match(
                rf"^\s*{_GREETING_START}{_ARTICLE}{_NAME}\b[\s,.\?!;:]*",
                rest,
                re.IGNORECASE,
            )
            if again is None:
                break
        rest = rest[again.end() :].strip()
    # Trailing "Arelis. Arelis." echoes after a command (hey optional here).
    trail = re.compile(
        rf"(?i)(?:\s*[.\?!;:]?\s*(?:{_GREETING})?{_NAME}\b)+[\s,.\?!;:]*$"
    )
    rest = trail.sub("", rest).strip()
    return rest


def match_wake(text: str) -> str | None:
    """If text contains "Hey Arelis" (or a spelling variant), return the rest.

    Returns None when the clip was ordinary speech that should be ignored while
    idle-listening. Prefers a match at the start (after fillers); otherwise
    uses the first greeting+name hit so a long clip can still wake. A bare
    name without "Hey" / "Hay" never matches.
    """
    raw = (text or "").strip()
    if not raw:
        return None

    match = _WAKE_AT_START.match(raw)
    if match is not None:
        return _peel_leading_wakes(raw[match.end() :].strip())

    match = _WAKE_ANYWHERE.search(raw)
    if match is None:
        return None
    return _peel_leading_wakes(raw[match.end() :].strip())


def looks_like_wake_attempt(text: str) -> bool:
    """True when the transcript probably meant to wake her (for operator feedback)."""
    return bool(_NAME_HINT.search(text or ""))


def classify_wake(text: str) -> WakeResult:
    """Match + package heard text for logging / UI feedback."""
    heard = (text or "").strip()
    if not heard:
        return WakeResult(matched=False, remainder="", heard="")
    remainder = match_wake(heard)
    if remainder is None:
        return WakeResult(matched=False, remainder="", heard=heard)
    return WakeResult(matched=True, remainder=remainder, heard=heard)
