"""Hand frame as data. No Qt. Safe to log and to test."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from arelis.spatial import (
    CURL_FINGERS,
    INDEX_MCP,
    INDEX_TIP,
    LANDMARK_NAMES,
    MIDDLE_MCP,
    PINKY_MCP,
    THUMB_TIP,
)


@dataclass(frozen=True)
class Landmark:
    x: float
    y: float
    z: float = 0.0
    name: str = ""


@dataclass(frozen=True)
class Hand:
    label: str
    landmarks: tuple[Landmark, ...]
    score: float = 0.0
    # Pinch midpoint after 1€, when a FilterBank has seen this hand. Tips stay
    # raw so the grab metric does not lag through itself; the world follows this.
    pointer: tuple[float, float] | None = None

    def xy(self, index: int) -> tuple[float, float]:
        point = self.landmarks[index]
        return (point.x, point.y)

    def xyz(self, index: int) -> tuple[float, float, float]:
        point = self.landmarks[index]
        return (point.x, point.y, point.z)

    def pinch_tips(self) -> tuple[tuple[float, float], tuple[float, float]]:
        return (self.xy(THUMB_TIP), self.xy(INDEX_TIP))

    def pinch_centroid(self) -> tuple[float, float]:
        thumb, index = self.pinch_tips()
        return ((thumb[0] + index[0]) / 2.0, (thumb[1] + index[1]) / 2.0)

    def pointer_xy(self) -> tuple[float, float]:
        """World cursor. Filtered midpoint when we have one, else the raw pinch."""
        if self.pointer is not None:
            return self.pointer
        return self.pinch_centroid()

    def pinch_span_xy(self) -> float:
        """Image-plane thumb-index. Tiny means the 2D tips have collapsed."""
        thumb, index = self.pinch_tips()
        return ((thumb[0] - index[0]) ** 2 + (thumb[1] - index[1]) ** 2) ** 0.5

    def pinch_metric(self) -> float:
        """Aperture: thumb-index / palm width in 3D. Smaller is closed.

        Fist and pad-pinch both crush this. Pose is aperture × knuckle
        curl, not this number alone. 2D span used to explode when turned.
        """
        palm = self.palm_width()
        span = _dist3(self.xyz(THUMB_TIP), self.xyz(INDEX_TIP))
        if palm < 1e-6:
            return span
        return span / palm

    def palm_width(self) -> float:
        return _dist3(self.xyz(INDEX_MCP), self.xyz(PINKY_MCP))

    def palm_span_xy(self, *, aspect: float = 16.0 / 9.0) -> float:
        """Index MCP–pinky MCP in frame-width units. Not MediaPipe z."""
        ix, iy = self.xy(INDEX_MCP)
        px, py = self.xy(PINKY_MCP)
        ratio = max(float(aspect), 1e-6)
        return ((ix - px) ** 2 + ((iy - py) / ratio) ** 2) ** 0.5

    def reach_span_xy(self, *, aspect: float = 16.0 / 9.0) -> float:
        """Wrist–middle MCP in frame-width units.

        A dolly scales this with the palm. A twist changes palm span
        and leaves this behind.
        """
        wx, wy = self.xy(0)
        mx, my = self.xy(MIDDLE_MCP)
        ratio = max(float(aspect), 1e-6)
        return ((wx - mx) ** 2 + ((wy - my) / ratio) ** 2) ** 0.5

    def finger_extension(self) -> float:
        """Legacy chord/palm. A 3D fist at the camera looks 'extended' here."""
        palm = self.palm_width()
        if palm < 1e-6:
            return 0.0
        spans = [
            _dist3(self.xyz(tip), self.xyz(mcp))
            for mcp, _pip, _dip, tip in CURL_FINGERS
        ]
        return (sum(spans) / 3.0) / palm

    def finger_curl(self, mcp: int, pip: int, dip: int, tip: int) -> float:
        """0 = straight bone chain, 1 = folded.

        Chord / chain in 3D. A fist aimed at the C920 still folds the
        knuckles; tip–MCP alone matches an open finger pointing at you.
        """
        chain = (
            _dist3(self.xyz(mcp), self.xyz(pip))
            + _dist3(self.xyz(pip), self.xyz(dip))
            + _dist3(self.xyz(dip), self.xyz(tip))
        )
        chord = _dist3(self.xyz(mcp), self.xyz(tip))
        if chain < 1e-6:
            return 1.0 if chord < 1e-6 else 0.0
        return max(0.0, min(1.0, 1.0 - chord / chain))

    def hand_curl(self) -> float:
        """Mean knuckle curl of middle, ring, pinky. Index is the pinch."""
        return sum(self.finger_curl(*bones) for bones in CURL_FINGERS) / 3.0

    def clips_frame(self) -> bool:
        """True when pose bones have left the sensor.

        MediaPipe still returns 21 points at the rim. Tips glue to 0/1
        or go slightly past; aperture then spikes and a fist 'opens'.
        A whole hand sitting in the corner is not this — wrist on the
        edge is a real pose. A tip glued to the wall while the wrist
        is still inside is the lie.
        """
        n = len(self.landmarks)
        if n < 9:
            return False
        wx, wy = self.xy(0)
        if wx < 0.0 or wx > 1.0 or wy < 0.0 or wy > 1.0:
            return True
        if not (0.04 < wx < 0.96 and 0.04 < wy < 0.96):
            return False
        tips = (THUMB_TIP, INDEX_TIP)
        if n >= 21:
            tips = (THUMB_TIP, INDEX_TIP, 12, 16, 20)
        for i in tips:
            x, y = self.xy(i)
            if x <= 0.0 or x >= 1.0 or y <= 0.0 or y >= 1.0:
                return True
        return False


def grab_drive(
    hand: Hand,
    *,
    closed: bool,
    offset: tuple[float, float] | None,
) -> tuple[tuple[float, float], tuple[float, float] | None]:
    """Cursor for the plane. While closed, wrist plus the offset from grab.

    MediaPipe z is wrist-relative, not world depth. The 2D tip midpoint
    orbits when you turn a hand; the wrist does not. Capture the aperture
    relative to the wrist on the first closed frame so a facing grab still
    sits on the fingers, and a later turn does not drag the disc around them.
    """
    tip = hand.pointer_xy()
    if not closed:
        return tip, None
    wrist = hand.xy(0)
    if offset is None:
        offset = (tip[0] - wrist[0], tip[1] - wrist[1])
    return (wrist[0] + offset[0], wrist[1] + offset[1]), offset


@dataclass(frozen=True)
class HandsFrame:
    t_capture: float
    t_infer: float
    width: int
    height: int
    infer_width: int
    infer_height: int
    hands: tuple[Hand, ...]
    backend: str = ""

    def to_log(self) -> dict[str, Any]:
        return {
            "t_capture": self.t_capture,
            "t_infer": self.t_infer,
            "width": self.width,
            "height": self.height,
            "infer_width": self.infer_width,
            "infer_height": self.infer_height,
            "backend": self.backend,
            "hands": [
                {
                    "label": hand.label,
                    "score": hand.score,
                    "pinch": round(hand.pinch_metric(), 5),
                    "curl": round(hand.hand_curl(), 5),
                    "extension": round(hand.finger_extension(), 5),
                    "landmarks": [
                        {
                            "name": lm.name or LANDMARK_NAMES[i],
                            "x": lm.x,
                            "y": lm.y,
                            "z": lm.z,
                        }
                        for i, lm in enumerate(hand.landmarks)
                    ],
                }
                for hand in self.hands
            ],
        }


def _dist3(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


@dataclass
class FilterBank:
    """One 1€ pair (x, y) per landmark, keyed by a wrist-stable slot.

    List order swaps when hands cross. Follow the wrist, not the index.
    """

    filters: dict[tuple[int, int, str], Any] = field(default_factory=dict)
    factory: Any = None
    _prev: list[tuple[tuple[float, float], int]] = field(default_factory=list)
    _next_id: int = 0

    def apply(self, frame: HandsFrame) -> HandsFrame:
        from arelis.spatial.one_euro import OneEuro

        make = self.factory or (lambda: OneEuro())
        t = frame.t_capture
        used: set[int] = set()
        assigned: list[tuple[Hand, int, tuple[float, float]]] = []
        for hand in frame.hands[:2]:
            wrist = hand.xy(0)
            slot = None
            best = 1e9
            for prev_wrist, prev_slot in self._prev:
                if prev_slot in used:
                    continue
                dist = (
                    (wrist[0] - prev_wrist[0]) ** 2 + (wrist[1] - prev_wrist[1]) ** 2
                ) ** 0.5
                if dist < best:
                    best = dist
                    slot = prev_slot
            if slot is None or best > 0.22:
                slot = self._next_id
                self._next_id += 1
            used.add(slot)
            assigned.append((hand, slot, wrist))
        self._prev = [(wrist, slot) for _, slot, wrist in assigned]
        out: list[Hand] = []
        for hand, slot, _wrist in assigned:
            points: list[Landmark] = []
            for i, lm in enumerate(hand.landmarks):
                # Tips unfiltered: 1€ on each pad makes a close pinch slide
                # through itself and the world cursor flips.
                if i in (THUMB_TIP, INDEX_TIP):
                    points.append(lm)
                    continue
                fx = self.filters.setdefault((slot, i, "x"), make())
                fy = self.filters.setdefault((slot, i, "y"), make())
                points.append(
                    Landmark(
                        x=fx(lm.x, t),
                        y=fy(lm.y, t),
                        z=lm.z,
                        name=lm.name,
                    )
                )
            cx, cy = hand.pinch_centroid()
            px = self.filters.setdefault((slot, -1, "x"), make())
            py = self.filters.setdefault((slot, -1, "y"), make())
            out.append(
                Hand(
                    label=hand.label,
                    landmarks=tuple(points),
                    score=hand.score,
                    pointer=(px(cx, t), py(cy, t)),
                )
            )
        return HandsFrame(
            t_capture=frame.t_capture,
            t_infer=frame.t_infer,
            width=frame.width,
            height=frame.height,
            infer_width=frame.infer_width,
            infer_height=frame.infer_height,
            hands=tuple(out),
            backend=frame.backend,
        )

    def reset(self) -> None:
        for item in self.filters.values():
            reset = getattr(item, "reset", None)
            if callable(reset):
                reset()
        self.filters.clear()
        self._prev.clear()
        self._next_id = 0
