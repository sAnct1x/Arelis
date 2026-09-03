"""NASA EONET natural events. Named public catalog. Not a face index.

Open events with a point. Failures return None so bundled sites stay.
Host pinned in tests/test_egress.py. Stretch 8: events and assets.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef

EONET_EVENTS = "https://eonet.gsfc.nasa.gov/api/v3/events"
EONET_HOST = "eonet.gsfc.nasa.gov"

_TIMEOUT = 10.0
_CAP = 120
_CITE = (
    "NASA EONET open events. Named public catalog (storms, fires, volcanoes). "
    "Not a face index. Not every incident on Earth."
)


def fetch_eonet() -> list[Entity] | None:
    payload = _get_json()
    if payload is None:
        return None
    rows = payload.get("events")
    if not isinstance(rows, list):
        return None
    return entities_from_events(rows)


def entities_from_events(rows: list[Any]) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = _entity_from_event(row)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _entity_from_event(row: dict[str, Any]) -> Entity | None:
    geom = _last_point(row.get("geometry"))
    if geom is None:
        return None
    lon, lat, when = geom
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    eid = str(row.get("id") or "").strip()
    title = str(row.get("title") or "").strip()
    if not eid and not title:
        return None
    cats = row.get("categories") if isinstance(row.get("categories"), list) else []
    kind = ""
    for cat in cats:
        if isinstance(cat, dict) and cat.get("title"):
            kind = str(cat.get("title"))
            break
    pos = lla_to_ecef(lat, lon, 0.0)
    label = title or eid
    if kind and kind.casefold() not in label.casefold():
        label = f"{kind}: {label}"
    return Entity(
        id=f"eonet:{eid or title.casefold()[:48]}",
        cls="site",
        layer="sites",
        label=label[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        when_unix=when,
        source="NASA EONET",
        freshness="delayed",
        confidence=0.7,
        cite=_CITE,
        meta={"lat": lat, "lon": lon, "category": kind, "event": eid},
        coverage=Coverage(
            "event",
            "Named public event. Most of Earth is unnamed.",
        ),
    )


def _last_point(geometry: Any) -> tuple[float, float, float] | None:
    if not isinstance(geometry, list) or not geometry:
        return None
    last = geometry[-1]
    if not isinstance(last, dict):
        return None
    coords = last.get("coordinates")
    if not isinstance(coords, list) or len(coords) < 2:
        return None
    lon = _num(coords[0])
    lat = _num(coords[1])
    if lat is None or lon is None:
        return None
    when = _unix_from_iso(last.get("date"))
    return lon, lat, when


def _unix_from_iso(stamp: Any) -> float:
    if not isinstance(stamp, str) or not stamp.strip():
        return 0.0
    text = stamp.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).astimezone(UTC).timestamp()
    except ValueError:
        return 0.0


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_json() -> dict[str, Any] | None:
    from arelis.earth.http import get_json

    data = get_json(
        EONET_EVENTS,
        EONET_HOST,
        timeout=_TIMEOUT,
        headers={"User-Agent": "ArelisEarth/0.2"},
        params={"status": "open", "limit": str(_CAP)},
    )
    return data if isinstance(data, dict) else None
