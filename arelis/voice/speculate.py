"""Provisional intent from early STT — weather/SMS only.

Conversation mode can transcribe a mid-utterance snapshot. If the provisional
text clearly matches weather or SMS, surface it (STATUS). Tools still run only
on the final committed transcript; if the final text disagrees, speculation is
cancelled (no side effects were started).
"""

from __future__ import annotations

from dataclasses import dataclass

from arelis.core.preflight import detect_intents


@dataclass(frozen=True)
class ProvisionalIntent:
    kinds: tuple[str, ...]
    summary: str


_SAFE = frozenset({"weather", "sms_send"})


def provisional_intents(text: str) -> ProvisionalIntent | None:
    """Return safe provisional intents, or None if nothing actionable."""
    kinds = tuple(
        h.kind for h in detect_intents(text or "") if h.kind in _SAFE
    )
    if not kinds:
        return None
    labels = []
    if "weather" in kinds:
        labels.append("weather")
    if "sms_send" in kinds:
        labels.append("SMS")
    return ProvisionalIntent(
        kinds=kinds,
        summary="Provisional hear: " + " / ".join(labels),
    )


def speculation_matches_final(provisional: ProvisionalIntent | None, final: str) -> bool:
    """True when final transcript still supports the same safe intents."""
    if provisional is None:
        return True
    again = provisional_intents(final)
    if again is None:
        return False
    return set(provisional.kinds).issubset(set(again.kinds))
