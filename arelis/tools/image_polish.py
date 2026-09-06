"""Image desk rubric. Each check is one thing a person can see or do.

A 10 on an axis is every check on that axis passing. Tests import this
so a broken sentence cannot silently drop a point.
"""

from __future__ import annotations

from dataclasses import dataclass

AXES = (
    "intuitiveness",
    "usability",
    "visual",
    "scalability",
    "maintainability",
)


@dataclass(frozen=True)
class Check:
    id: str
    axis: str
    title: str


CHECKS: tuple[Check, ...] = (
    Check("caption-names-picture", "intuitiveness", "Hero caption is filename plus prompt"),
    Check("fail-is-sentence", "intuitiveness", "A bad file says Could not load name"),
    Check("empty-mentions-pictures", "intuitiveness", "Empty desk says pictures land here"),
    Check("status-is-errand", "intuitiveness", "Shimmer says making a picture, not calling image"),
    Check("confirm-is-human", "intuitiveness", "Allow card is a lowercase sentence"),
    Check("open-stays-on-picture", "intuitiveness", "Open stays on the picture face"),
    Check("click-thumb-opens", "usability", "A rail thumb opens that file"),
    Check("arrows-walk-rail", "usability", "Left and right walk the rail"),
    Check("tooltip-has-prompt", "usability", "Hero tooltip carries the sidecar prompt"),
    Check("progress-line-exists", "usability", "A variation has a picture N of M line"),
    Check("progress-wired", "usability", "Comfy wait can report progress"),
    Check("edit-has-errand", "usability", "image_edit has its own shimmer sentence"),
    Check("well-own-name", "visual", "Hero well is WorkspaceImageWell only"),
    Check("strip-own-name", "visual", "Rail is WorkspaceImageStrip"),
    Check("thumb-own-name", "visual", "Thumbs are WorkspaceImageThumb"),
    Check("thumb-is-square", "visual", "Each thumb is a square"),
    Check("selected-thumb", "visual", "The open picture is the checked thumb"),
    Check("qss-has-roles", "visual", "Stylesheet names well, strip, thumb, caption"),
    Check("overlay-plex-first", "visual", "Overlay type prefers IBM Plex, not Arial"),
    Check("strip-capped", "scalability", "Rail lists at most 16 files"),
    Check("n-clamped", "scalability", "Variations clamp to 1–4"),
    Check("thumb-loads-scaled", "scalability", "Thumbs decode near display size"),
    Check("hero-loads-fitted", "scalability", "Hero decodes to the well, not source pixels"),
    Check("variation-progress", "scalability", "n=4 progress names the variation"),
    Check("rail-module", "maintainability", "Listing and decode live in image_rail"),
    Check("copy-module", "maintainability", "Image sentences live in image_copy"),
    Check("polish-module", "maintainability", "This rubric is importable"),
    Check("one-name-per-role", "maintainability", "Well, strip, and thumb do not share an object name"),
    Check("confirm-covers-verbs", "maintainability", "Confirm copy covers restyle, cut-out, crop, 2×"),
)


def score(passed: set[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for axis in AXES:
        ids = [c.id for c in CHECKS if c.axis == axis]
        n = len(ids)
        hit = sum(1 for i in ids if i in passed)
        out[axis] = round(10.0 * hit / n, 1) if n else 0.0
    return out
