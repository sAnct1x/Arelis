"""Closed physics-room verbs. Tiny decoder, no turn, no 9B.

Whole utterance only. In orbit these words are English.
"""

from __future__ import annotations

import re
from typing import Literal

PhysicsVerb = Literal["heavier", "lighter", "freeze", "unfreeze", "undo"]

_HEAVIER = re.compile(
    r"(?i)^\s*(?:make (?:it|this|that) )?(?:heavier|heavy)\s*[.!]?\s*$"
)
_LIGHTER = re.compile(
    r"(?i)^\s*(?:make (?:it|this|that) )?lighter\s*[.!]?\s*$"
)
_FREEZE = re.compile(
    r"(?i)^\s*(?:freeze(?:\s+it)?|hold still)\s*[.!]?\s*$"
)
_UNFREEZE = re.compile(
    r"(?i)^\s*(?:unfreeze(?:\s+it)?|thaw)\s*[.!]?\s*$"
)
_UNDO = re.compile(r"(?i)^\s*(?:undo(?:\s+that)?)\s*[.!]?\s*$")


def classify_physics_verb(text: str) -> PhysicsVerb | None:
    """Return a closed verb, or None when this is ordinary talk."""
    raw = (text or "").strip()
    if not raw:
        return None
    if _HEAVIER.match(raw):
        return "heavier"
    if _LIGHTER.match(raw):
        return "lighter"
    if _FREEZE.match(raw):
        return "freeze"
    if _UNFREEZE.match(raw):
        return "unfreeze"
    if _UNDO.match(raw):
        return "undo"
    return None
