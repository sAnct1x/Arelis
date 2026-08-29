"""Published camera viewsheds. Pose priors, not a survey, not video.

Only the bundled municipal pins get a frustum. Heading/FOV/range are
documented priors so the plate can draw a hole. Occluders are not meshed.
Unpublished cameras stay absent. Unsecured IP streams are out.
"""

from __future__ import annotations

import math

from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import enu_to_ecef, lla_to_ecef

# heading_deg: clockwise from north. range_m: street scale. Not a measured pose.
POSE: dict[str, dict[str, float]] = {
    "tfl:trafalgar": {"heading_deg": 180.0, "fov_deg": 70.0, "range_m": 280.0},
    "tfl:london-bridge": {"heading_deg": 90.0, "fov_deg": 65.0, "range_m": 220.0},
    "caltrans:101-sf": {"heading_deg": 165.0, "fov_deg": 55.0, "range_m": 320.0},
    "caltrans:405-la": {"heading_deg": 180.0, "fov_deg": 55.0, "range_m": 350.0},
    "austin:6th": {"heading_deg": 90.0, "fov_deg": 70.0, "range_m": 180.0},
    "austin:congress": {"heading_deg": 0.0, "fov_deg": 70.0, "range_m": 200.0},
}

_ALT_M = 12.0
_RAYS = 5
_CITE = (
    "Published municipal pin. Viewshed is a pose prior, not a survey. "
    "No video ingest. Occluders not meshed. Unpublished cameras are holes."
)


def frustum_ecef(
    lat: float,
    lon: float,
    heading_deg: float,
    fov_deg: float,
    range_m: float,
    *,
    alt_m: float = _ALT_M,
    rays: int = _RAYS,
) -> tuple[tuple[float, float, float], ...]:
    """Origin plus an arc at range. Local ENU, then ECEF. No terrain."""
    origin = lla_to_ecef(lat, lon, alt_m)
    n = max(3, int(rays))
    half = float(fov_deg) * 0.5
    pts: list[tuple[float, float, float]] = [origin]
    for i in range(n):
        az = -half + (float(fov_deg) * i / (n - 1))
        h = math.radians(heading_deg + az)
        east = math.sin(h) * range_m
        north = math.cos(h) * range_m
        pts.append(enu_to_ecef(lat, lon, east, north, 0.0, alt_m=alt_m))
    return tuple(pts)


def attach_viewshed(entity: Entity) -> Entity:
    """Fill a frustum when heading is known. Unknown pose stays a pin."""
    pose = POSE.get(entity.id)
    source = "prior"
    if pose is None:
        heading = entity.meta.get("heading_deg")
        if heading is None:
            return entity
        try:
            pose = {
                "heading_deg": float(heading),
                "fov_deg": float(entity.meta.get("fov_deg") or 55.0),
                "range_m": float(entity.meta.get("range_m") or 280.0),
            }
        except (TypeError, ValueError):
            return entity
        source = str(entity.meta.get("pose") or "catalog")
    lat = float(entity.meta.get("lat") or 0.0)
    lon = float(entity.meta.get("lon") or 0.0)
    fan = frustum_ecef(
        lat,
        lon,
        pose["heading_deg"],
        pose["fov_deg"],
        pose["range_m"],
    )
    if entity.id in POSE:
        entity.cite = _CITE
    entity.meta = {
        **entity.meta,
        "heading_deg": pose["heading_deg"],
        "fov_deg": pose["fov_deg"],
        "range_m": pose["range_m"],
        "pose": source,
        "viewshed_ecef": [list(p) for p in fan],
    }
    note = (
        "Pose-prior frustum. Occluders not meshed. Unpublished cams are holes."
        if source == "prior"
        else "Operator-published direction. Occluders not meshed. No video."
    )
    entity.coverage = Coverage(
        kind="viewshed",
        note=note,
        volume_hint=f"{pose['range_m']:.0f} m / {pose['fov_deg']:.0f}°",
    )
    return entity


def viewshed_points(entity: Entity) -> tuple[tuple[float, float, float], ...]:
    raw = entity.meta.get("viewshed_ecef")
    if not isinstance(raw, list) or len(raw) < 3:
        return ()
    out: list[tuple[float, float, float]] = []
    for row in raw:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        try:
            out.append((float(row[0]), float(row[1]), float(row[2])))
        except (TypeError, ValueError):
            continue
    return tuple(out) if len(out) >= 3 else ()
