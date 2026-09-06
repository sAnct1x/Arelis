"""Per-contact Earth trail. Not the heliocentric solar-lab ribbon.

Samples live in ECEF metres on the tracked or ridden id. Unlock / leave
clears them. Do not reuse SolarSystem.trails — those are sun-orbit arcs.
"""

from __future__ import annotations

from collections import deque

_CAP = 48
_MIN_STEP_M2 = 400.0  # ~20 m
_TRAILS: dict[str, deque[tuple[float, float, float]]] = {}


def note(entity_id: str, xyz: tuple[float, float, float]) -> None:
    key = (entity_id or "").strip()
    if not key:
        return
    x, y, z = float(xyz[0]), float(xyz[1]), float(xyz[2])
    q = _TRAILS.setdefault(key, deque(maxlen=_CAP))
    if q:
        dx = q[-1][0] - x
        dy = q[-1][1] - y
        dz = q[-1][2] - z
        if dx * dx + dy * dy + dz * dz < _MIN_STEP_M2:
            return
    q.append((x, y, z))


def points(entity_id: str) -> tuple[tuple[float, float, float], ...]:
    key = (entity_id or "").strip()
    hit = _TRAILS.get(key)
    return tuple(hit) if hit else ()


def forget(entity_id: str | None = None) -> None:
    if entity_id is None:
        _TRAILS.clear()
        return
    _TRAILS.pop((entity_id or "").strip(), None)
