"""Short yes/no lists for an open confirm card (voice or typed)."""

from __future__ import annotations

import re

# Whole utterance only. Room chat and "I don't know" must not decide.
_ALLOW = re.compile(
    r"(?i)^\s*(?:"
    r"yes|yeah|yep|yup|ok|okay|sure|"
    r"allow|approve|"
    r"go ahead|do it|please do"
    r")\s*[.!]?\s*$"
)
_DENY = re.compile(
    r"(?i)^\s*(?:"
    r"no|nope|nah|"
    r"deny|"
    r"don't|dont|do not|"
    r"stop|never|not now"
    r")\s*[.!]?\s*$"
)


def classify_confirm_utterance(text: str) -> str | None:
    """Return ``allow`` or ``skip`` (deny) when the whole line is a decision.

    Internal wire is still skip. Empty string is not a decision (Enter on an
    empty composer stays the keyboard shortcut for allow).
    """
    raw = (text or "").strip()
    if not raw:
        return None
    if _ALLOW.match(raw):
        return "allow"
    if _DENY.match(raw):
        return "skip"
    return None
