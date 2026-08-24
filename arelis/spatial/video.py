"""Sizes for the pose tap. Landmarks stay normalized 0–1."""

from __future__ import annotations

POSE_MAX_WIDTH = 640
PREVIEW_MAX_WIDTH = 640


def score_live_format(
    width: int, height: int, max_fps: float, pixel_format: str
) -> tuple[float, int, int]:
    """Sort key (higher wins). C920 YUY2 1080p is 5 fps; MJPEG 1080p is 30.

    Do not pick the first 1920×1080 on the list — that is how we locked
    the sensor at 5 Hz and blamed the copy.
    """
    name = (pixel_format or "").lower()
    jpeg = any(tag in name for tag in ("jpeg", "mjpg", "mjpeg"))
    fps = float(max_fps or 0.0)
    return (fps, 1 if jpeg else 0, int(width) * int(height))


def pick_live_format(
    rows: list[tuple[int, int, float, str]],
) -> tuple[int, int, float, str] | None:
    """Choose the live tap. Prefer ≥24 fps, then score_live_format."""
    if not rows:
        return None
    viable = [r for r in rows if float(r[2] or 0) >= 24]
    pool = viable or rows
    return max(pool, key=lambda r: score_live_format(r[0], r[1], r[2], r[3]))


def fit_size(width: int, height: int, max_width: int) -> tuple[int, int]:
    """Uniform shrink so width <= max_width. No-op if already small."""
    w, h = int(width), int(height)
    if w < 1 or h < 1:
        return (0, 0)
    if w <= max_width:
        return (w, h)
    new_w = int(max_width)
    new_h = max(1, int(round(h * (max_width / w))))
    return (new_w, new_h)
