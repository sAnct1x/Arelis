"""Reality plate rubric. Each check is one thing a person can see or do.

A 10 on an axis is every check on that axis passing. Tests import this
so a broken sentence cannot silently drop a point.
"""

from __future__ import annotations

from dataclasses import dataclass

AXES = ("intuitiveness", "visual", "friendly")


@dataclass(frozen=True)
class Check:
    id: str
    axis: str
    title: str


CHECKS: tuple[Check, ...] = (
    Check("status-sentence", "intuitiveness", "Status is a sentence, not ECEF n"),
    Check("live-nudge", "intuitiveness", "Simulated status tells you to click Live"),
    Check("band-not-toggle", "intuitiveness", "Band is a distance phrase, not a chip"),
    Check("find-exists", "intuitiveness", "Find field is on the plate"),
    Check("find-tokyo", "intuitiveness", "Find matches Tokyo without a chat turn"),
    Check("people-chip", "intuitiveness", "People chip is on the city bar"),
    Check("marks-on-h", "intuitiveness", "H names Earth marks"),
    Check("slash-find", "intuitiveness", "Slash opens find on Earth"),
    Check("live-label", "visual", "Live reads Live off / Live on"),
    Check("band-type", "visual", "Band paint is type, not a filled toggle"),
    Check("coach-line", "visual", "Coach names the next click"),
    Check("deaf-copy", "visual", "Empty live look box explains the hole"),
    Check("same-marks", "visual", "Mark hints share the Earth mark factory language"),
    Check("no-ecef-hud", "visual", "HUD status never says ECEF"),
    Check("find-works", "friendly", "Find flies to a city"),
    Check("home-optional", "friendly", "Home is offered when the profile has lat/lon"),
    Check("key-paste", "friendly", "Photoreal / Fires / Ships paste without opening YAML"),
    Check("key-hidden", "friendly", "Pasted keys are never echoed"),
    Check("inspect-human", "friendly", "Inspect names kind and freshness in English"),
    Check("enter-human", "friendly", "Enter note is Watching Earth, not ECEF"),
    Check("verbs-stay", "friendly", "enter Earth / leave Earth still closed verbs"),
    Check("failures-keep-sim", "friendly", "Live failure still keeps simulation"),
)


def score(passed: set[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for axis in AXES:
        ids = [c.id for c in CHECKS if c.axis == axis]
        n = len(ids)
        hit = sum(1 for i in ids if i in passed)
        out[axis] = round(10.0 * hit / n, 1) if n else 0.0
    return out
