"""Wake-phrase matching for always-listen mode.

Whisper will not spell the name the same way every time. Accept a short list of
spellings and return the remainder of the utterance, or None when this was not
a wake.

The compound phrase is required: "Hey" (or Whisper's "Hay" / "Hair" /
leading "Pay") plus the name. Bare "Arelis", "Hi Arelis", and
"Okay Arelis" do not wake —
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
    r"arelyse|areliss|arelis|arilis|arillis|"
    r"arrellis|arreliss|arrelis|"
    r"arrelas|arella|rellis|relics|relus|relis|arlus)"
)

# Junk Whisper often sticks before the greeting on noisy/long clips.
_FILLER = (
    r"(?:and|uh|um|er|ah|oh|so|well|the|a|yeah|like|hmm|mm|"
    r"you\s+know)\s*,?\s*"
)

# Required. "hay" is a frequent Whisper misspelling of "hey".
# "hi" / "ok" / "okay" are too common in calls to be wake greetings.
_GREETING = r"(?:hey|hay)\s*,?\s*"
# Start-only cousins: Whisper/Sherpa write "Hair Relus", "Hier relus",
# "Hayer relus", "Haigha relus", "Heiga relus", "Here relus". Mid-clip
# those words are ordinary speech ("here we go", "hair cut").
_GREETING_START = (
    r"(?:hey|hay|pay|hair|hier|hayer|haigha|heiga|here)\s*,?\s*"
)
# Whisper also writes "Hey a relus" / "Pay a relus" / "HAY Are relus".
_ARTICLE = r"(?:(?:a|are)\s+)?"
# One mashed token, no space. Dictate + a few Whisper clips.
_FUSED = (
    r"(?:haigaretllus|hierrallelus|hierrallus|hierarlus|"
    r"hayorellus|hayorlus|hiarlus|pyrallus|harlus)"
)

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
    r"(?i)\b(?:hey|hay|pay|hair|hier|hayer|haigha|heiga|here)\s+"
    r"(?:(?:a|are)\s+)?(?:airelyse|airelease|aurelis|aurelyse|"
    r"arellis|arelyse|areliss|arelis|arilis|arillis|arrellis|arrelis|"
    r"arrelas|arella|rellis|relics|relus|relis|arlus)\b"
    r"|\bher\s+(?:relus|relics|relis|arlus)\b"
    r"|\b(?:haigaretllus|hierrallelus|hierrallus|hierarlus|"
    r"hayorellus|hayorlus|hiarlus|pyrallus|harlus)\b"
)

# "Her relus" — "her" is too common to be a greeting, but this pair is the
# doorbell as Sherpa writes it. Start of clip only.
_WAKE_HER = re.compile(
    rf"^\s*(?:{_FILLER}){{0,6}}her\s+(?:relus|relics|relis|arlus)\b[\s,.\?!;:]*",
    re.IGNORECASE,
)
_WAKE_FUSED = re.compile(
    rf"^\s*(?:{_FILLER}){{0,6}}{_FUSED}\b[\s,.\?!;:]*",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class WakeResult:
    """Outcome of transcribing one idle wake clip."""

    matched: bool
    remainder: str
    heard: str


def _leading_wake(rest: str):
    """First doorbell token at the start of *rest*, or None."""
    for pattern in (_WAKE_FUSED, _WAKE_HER, _WAKE_AT_START):
        hit = pattern.match(rest)
        if hit is not None:
            return hit
    return re.match(
        rf"^\s*{_GREETING_START}{_ARTICLE}{_NAME}\b[\s,.\?!;:]*",
        rest,
        re.IGNORECASE,
    )


def _peel_leading_wakes(rest: str) -> str:
    """Strip repeated wake phrases so they never become a user turn."""
    while True:
        again = _leading_wake(rest)
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

    match = _leading_wake(raw)
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
