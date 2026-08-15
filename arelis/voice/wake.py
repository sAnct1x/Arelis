"""Wake-phrase matching for always-listen mode.

Whisper will not spell the name the same way every time. Accept a short list of
spellings and return the remainder of the utterance, or None when this was not
a wake.

"Hey" / "Hi" is optional. Leading Whisper fillers ("and", "uh", …) are ignored.
If the name appears later in a long hallucinated clip, the first clear wake in
the transcript still counts — remainder is everything after that match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Name spellings Whisper commonly produces (including Airelyse / Aurelis).
_NAME = (
    r"(?:airelyse|airelease|aurelyse|aurelis|arellis|aerolyse|"
    r"air\s*elise|air\s*elis|"
    r"arelyse|arelys|areliss|arelis|a\s*relis|"
    r"or\s*elis|orelis)"
)

# Junk Whisper often sticks before the name on noisy/long clips.
_FILLER = (
    r"(?:and|uh|um|er|ah|oh|so|well|the|a|yeah|like|hmm|mm|"
    r"you\s+know)\s*,?\s*"
)

_GREETING = r"(?:hey|hi|okay|ok)\s*,?\s*"

# Strict: start of string after optional fillers + optional greeting.
_WAKE_AT_START = re.compile(
    rf"^\s*(?:{_FILLER}){{0,6}}(?:{_GREETING})?{_NAME}\b[\s,.\?!;:]*",
    re.IGNORECASE,
)

# Anywhere: greeting+name or bare name (used when start match fails).
_WAKE_ANYWHERE = re.compile(
    rf"(?:{_GREETING})?{_NAME}\b[\s,.\?!;:]*",
    re.IGNORECASE,
)

# Soft hint that Whisper heard the name but match_wake still failed.
_NAME_HINT = re.compile(
    r"(?i)\b(?:hey\s+)?(?:air\s*)?(?:elise|elis|arelys|arelis|airelyse|"
    r"aurelis|aurelyse|orelis)\b"
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
            # Also peel bare mid-string wakes at the front after punctuation.
            again = re.match(
                rf"^\s*(?:{_GREETING})?{_NAME}\b[\s,.\?!;:]*",
                rest,
                re.IGNORECASE,
            )
            if again is None:
                break
        rest = rest[again.end() :].strip()
    # Trailing "Arelis. Arelis." echoes after a command.
    trail = re.compile(
        rf"(?i)(?:\s*[.\?!;:]?\s*(?:{_GREETING})?{_NAME}\b)+[\s,.\?!;:]*$"
    )
    rest = trail.sub("", rest).strip()
    return rest


def match_wake(text: str) -> str | None:
    """If text contains a wake phrase, return the remainder (may be empty).

    Returns None when the clip was ordinary speech that should be ignored while
    idle-listening. Prefers a match at the start (after fillers); otherwise
    uses the first name hit in the transcript so long noisy clips still wake.
    """
    raw = (text or "").strip()
    if not raw:
        return None

    match = _WAKE_AT_START.match(raw)
    if match is not None:
        return _peel_leading_wakes(raw[match.end() :].strip())

    # Long ambient/VAD dumps: find the first real wake and take what follows.
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
