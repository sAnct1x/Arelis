"""Closed physics-room verbs. Tiny decoder, no turn, no 9B.

Whole utterance only. In orbit these words are English.
"""

from __future__ import annotations

import re
from typing import Literal

PhysicsVerb = Literal[
    "heavier",
    "lighter",
    "freeze",
    "unfreeze",
    "undo",
    "pause",
    "resume",
    "step",
    "faster",
    "slower",
    "realtime",
    "hour",
    "day",
    "year",
    "fly",
    "inspect",
]

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
_PAUSE = re.compile(r"(?i)^\s*pause(?:\s+it)?\s*[.!]?\s*$")
_RESUME = re.compile(
    r"(?i)^\s*(?:resume(?:\s+it)?|unpause|play)\s*[.!]?\s*$"
)
_STEP = re.compile(r"(?i)^\s*step(?:\s+once)?\s*[.!]?\s*$")
_FASTER = re.compile(
    r"(?i)^\s*(?:faster|speed up|go faster)\s*[.!]?\s*$"
)
_SLOWER = re.compile(
    r"(?i)^\s*(?:slower|slow down|go slower)\s*[.!]?\s*$"
)
_REALTIME = re.compile(
    r"(?i)^\s*(?:real\s*time|realtime|1x|real[- ]time)\s*[.!]?\s*$"
)
_HOUR = re.compile(r"(?i)^\s*(?:one\s+)?hour(?:\s+per\s+second)?\s*[.!]?\s*$")
_DAY = re.compile(r"(?i)^\s*(?:one\s+)?day(?:\s+per\s+second)?\s*[.!]?\s*$")
_YEAR = re.compile(r"(?i)^\s*(?:one\s+)?year(?:\s+per\s+second)?\s*[.!]?\s*$")
_FLY = re.compile(
    r"(?i)^\s*(?:fly|craft|pilot|board)\s*[.!]?\s*$"
)
_INSPECT = re.compile(
    r"(?i)^\s*(?:inspect|look|orbit\s+view)\s*[.!]?\s*$"
)

_TOY = frozenset({"heavier", "lighter", "freeze", "unfreeze", "undo"})
_TIME = frozenset(
    {
        "pause",
        "resume",
        "step",
        "faster",
        "slower",
        "realtime",
        "hour",
        "day",
        "year",
        "fly",
        "inspect",
    }
)


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
    if _PAUSE.match(raw):
        return "pause"
    if _RESUME.match(raw):
        return "resume"
    if _STEP.match(raw):
        return "step"
    if _FASTER.match(raw):
        return "faster"
    if _SLOWER.match(raw):
        return "slower"
    if _REALTIME.match(raw):
        return "realtime"
    if _HOUR.match(raw):
        return "hour"
    if _DAY.match(raw):
        return "day"
    if _YEAR.match(raw):
        return "year"
    if _FLY.match(raw):
        return "fly"
    if _INSPECT.match(raw):
        return "inspect"
    return None


def is_time_verb(verb: str) -> bool:
    return verb in _TIME


def is_toy_verb(verb: str) -> bool:
    return verb in _TOY
