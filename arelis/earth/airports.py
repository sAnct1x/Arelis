"""OurAirports public dump. Large/medium fields with scheduled service.

Daily CSV from the OurAirports data repo. Positions only — not a live
radar. Failures return None so bundled sites stay. Host is the already
pinned raw.githubusercontent.com mirror.
"""

from __future__ import annotations

import csv
import io
from typing import Any
from urllib.parse import urlparse

import httpx

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef

# Same files as davidmegginson.github.io/ourairports-data/. GitHub raw is
# already an egress pin (release assets). Do not add a second host.
AIRPORTS_CSV = (
    "https://raw.githubusercontent.com/davidmegginson/ourairports-data/"
    "main/airports.csv"
)
AIRPORTS_HOST = "raw.githubusercontent.com"
_UA = f"Arelis/{__version__} (+{__source_url__})"

_TIMEOUT = 20.0
_CAP = 2500
_TYPES = frozenset({"large_airport", "medium_airport"})
_CITE = (
    "OurAirports public dump (ODbL-adjacent community catalog). "
    "Large/medium fields with scheduled service. Not a live radar. "
    "Closed and private strips stay off."
)


def fetch_airports() -> list[Entity] | None:
    text = _get_csv()
    if text is None:
        return None
    pins = entities_from_csv(text)
    return pins or None


def entities_from_csv(text: str) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    try:
        reader = csv.DictReader(io.StringIO(text))
    except Exception:
        return []
    for row in reader:
        if not isinstance(row, dict):
            continue
        entity = _entity_from_row(row)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _entity_from_row(row: dict[str, Any]) -> Entity | None:
    kind = str(row.get("type") or "").strip()
    if kind not in _TYPES:
        return None
    if str(row.get("scheduled_service") or "").strip().casefold() != "yes":
        return None
    lat = _num(row.get("latitude_deg"))
    lon = _num(row.get("longitude_deg"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return None
    ident = str(row.get("ident") or row.get("gps_code") or "").strip()
    iata = str(row.get("iata_code") or "").strip()
    name = str(row.get("name") or ident or iata).strip()
    if not ident and not iata:
        return None
    eid = f"apt:{ident or iata}"
    alt_ft = _num(row.get("elevation_ft")) or 0.0
    pos = lla_to_ecef(lat, lon, alt_ft * 0.3048)
    label = f"{iata} {name}" if iata and iata.casefold() not in name.casefold() else name
    return Entity(
        id=eid,
        cls="site",
        layer="sites",
        label=label[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="OurAirports",
        freshness="reconstructed",
        confidence=0.8,
        cite=_CITE,
        meta={"lat": lat, "lon": lon, "ident": ident, "iata": iata, "type": kind},
        coverage=Coverage(
            "catalog",
            "Published field pin. Not a live radar. Not every strip.",
        ),
    )


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _host_pinned(host: str | None) -> bool:
    if not host:
        return False
    name = host.lower()
    return name == AIRPORTS_HOST or name.endswith("." + AIRPORTS_HOST)


def _get_csv() -> str | None:
    if not _host_pinned(urlparse(AIRPORTS_CSV).hostname):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(AIRPORTS_CSV, headers={"User-Agent": _UA})
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                return None
            text = resp.text
    except Exception:
        return None
    return text if isinstance(text, str) and "latitude_deg" in text else None
