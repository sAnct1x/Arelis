"""Synthetic C920 hands for gesture tests. No camera."""

from __future__ import annotations

from arelis.spatial import LANDMARK_NAMES
from arelis.spatial.types import Hand, HandsFrame, Landmark

# MediaPipe indices we place explicitly. The rest stay on the wrist.
_WRIST = 0
_THUMB = (1, 2, 3, 4)
_INDEX = (5, 6, 7, 8)
_MIDDLE = (9, 10, 11, 12)
_RING = (13, 14, 15, 16)
_PINKY = (17, 18, 19, 20)


def make_hand(
    label: str,
    wrist: tuple[float, float],
    *,
    pose: str = "open",
    pointer: tuple[float, float] | None = None,
) -> Hand:
    """One 21-point hand. pose is open / pinch / fist."""
    wx, wy = float(wrist[0]), float(wrist[1])
    pts = [(wx, wy, 0.0)] * 21
    # Palm ~8 cm in image units. Index MCP right of pinky.
    ix, iy = wx + 0.040, wy - 0.028
    px, py = wx - 0.040, wy - 0.022
    pts[5] = (ix, iy, 0.0)
    pts[17] = (px, py, 0.0)
    pts[9] = (wx + 0.012, wy - 0.032, 0.0)
    pts[13] = (wx - 0.014, wy - 0.030, 0.0)
    thumb_base = (wx + 0.018, wy + 0.006, 0.0)
    pts[1] = thumb_base
    pts[2] = (wx + 0.028, wy - 0.004, 0.0)
    pts[3] = (wx + 0.034, wy - 0.014, 0.0)
    kind = str(pose or "open").lower()
    if kind == "open":
        pts[4] = (wx + 0.010, wy - 0.012, 0.0)
        _extend(pts, _INDEX, (ix, iy - 0.090))
        _extend(pts, _MIDDLE, (pts[9][0], pts[9][1] - 0.095))
        _extend(pts, _RING, (pts[13][0], pts[13][1] - 0.088))
        _extend(pts, _PINKY, (px, py - 0.072))
    elif kind == "pinch":
        tip = (ix + 0.006, iy - 0.062)
        pts[4] = (tip[0] - 0.006, tip[1] + 0.004, 0.0)
        _extend(pts, _INDEX, tip)
        _extend(pts, _MIDDLE, (pts[9][0], pts[9][1] - 0.095))
        _extend(pts, _RING, (pts[13][0], pts[13][1] - 0.088))
        _extend(pts, _PINKY, (px, py - 0.072))
    else:
        # Fist: pads collapsed, unused fingers folded.
        tip = (ix - 0.004, iy - 0.018)
        pts[4] = (tip[0] - 0.004, tip[1] + 0.006, 0.0)
        _extend(pts, _INDEX, tip)
        _fold(pts, _MIDDLE)
        _fold(pts, _RING)
        _fold(pts, _PINKY)
    marks = tuple(
        Landmark(x=x, y=y, z=z, name=LANDMARK_NAMES[i] if i < 21 else "")
        for i, (x, y, z) in enumerate(pts)
    )
    return Hand(label=label, landmarks=marks, score=0.99, pointer=pointer)


def frame_of(*hands: Hand, t: float = 0.0) -> HandsFrame:
    return HandsFrame(
        t_capture=float(t),
        t_infer=float(t),
        width=640,
        height=360,
        infer_width=640,
        infer_height=360,
        hands=tuple(hands),
        backend="test",
    )


def _extend(pts: list, bones: tuple[int, ...], tip: tuple[float, float]) -> None:
    mcp = pts[bones[0]]
    tx, ty = tip
    for i, u in zip(bones[1:], (0.34, 0.67, 1.0), strict=True):
        pts[i] = (mcp[0] + (tx - mcp[0]) * u, mcp[1] + (ty - mcp[1]) * u, 0.0)


def _fold(pts: list, bones: tuple[int, ...]) -> None:
    mcp = pts[bones[0]]
    pts[bones[1]] = (mcp[0] + 0.018, mcp[1] - 0.016, 0.0)
    pts[bones[2]] = (mcp[0] + 0.012, mcp[1] + 0.004, 0.0)
    pts[bones[3]] = (mcp[0] + 0.004, mcp[1] + 0.010, 0.0)
