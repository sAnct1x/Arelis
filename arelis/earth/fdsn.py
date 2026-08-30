"""FDSN station catalogs. Official text, no key.

National / backbone networks only: INGV IV, GEOFON GE, IRIS IU,
NRCAN CN, GeoNet NZ. Positions only. GeoJSON stays closed on these
hosts; the text format is what they publish. Failures return None.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse

import httpx

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef

INGV = (
    "https://webservices.ingv.it/fdsnws/station/1/query"
    "?network=IV&format=text&level=station"
)
INGV_HOST = "webservices.ingv.it"
GEOFON = (
    "https://geofon.gfz-potsdam.de/fdsnws/station/1/query"
    "?network=GE&format=text&level=station"
)
GEOFON_HOST = "geofon.gfz-potsdam.de"
IRIS = (
    "https://service.iris.edu/fdsnws/station/1/query"
    "?network=IU&format=text&level=station"
)
IRIS_HOST = "service.iris.edu"
NRCAN = (
    "https://www.earthquakescanada.nrcan.gc.ca/fdsnws/station/1/query"
    "?network=CN&format=text&level=station"
)
NRCAN_HOST = "www.earthquakescanada.nrcan.gc.ca"
GEONET = (
    "https://service.geonet.org.nz/fdsnws/station/1/query"
    "?network=NZ&format=text&level=station"
)
GEONET_HOST = "service.geonet.org.nz"
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 12.0
_CAP = 4000
_INGV_CITE = (
    "INGV FDSN station text. Italian national network. "
    "Published sensor sites, not every quake."
)
_GEOFON_CITE = (
    "GFZ GEOFON FDSN station text. Global backbone sample. "
    "Published sensor sites, not every quake."
)
_IRIS_CITE = (
    "IRIS FDSN station text. IU global seismic network. "
    "Published sensor sites, not every quake."
)
_NRCAN_CITE = (
    "NRCAN FDSN station text. Canadian national network. "
    "Published sensor sites, not every quake."
)
_GEONET_CITE = (
    "GeoNet FDSN station text. New Zealand national network. "
    "Published sensor sites, not every quake."
)
_JOBS: tuple[tuple[str, str, str, str, str], ...] = (
    (INGV, INGV_HOST, "ingv", "INGV stations", _INGV_CITE),
    (GEOFON, GEOFON_HOST, "geofon", "GEOFON stations", _GEOFON_CITE),
    (IRIS, IRIS_HOST, "iris", "IRIS IU stations", _IRIS_CITE),
    (NRCAN, NRCAN_HOST, "nrcan", "NRCAN stations", _NRCAN_CITE),
    (GEONET, GEONET_HOST, "geonet-sta", "GeoNet stations", _GEONET_CITE),
)


def fetch_fdsn() -> list[Entity] | None:
    chunks: list[list[Entity] | None] = []
    with ThreadPoolExecutor(max_workers=len(_JOBS)) as pool:
        futs = [
            pool.submit(_fetch_one, url, host, prefix, source, cite)
            for url, host, prefix, source, cite in _JOBS
        ]
        for fut in futs:
            chunks.append(fut.result())
    if all(chunk is None for chunk in chunks):
        return None
    out: list[Entity] = []
    seen: set[str] = set()
    for chunk in chunks:
        for entity in chunk or []:
            if entity.id in seen:
                continue
            seen.add(entity.id)
            out.append(entity)
            if len(out) >= _CAP:
                return out
    return out or None


def entities_from_fdsn_text(
    text: str, *, prefix: str, source: str, cite: str
) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cols = [col.strip() for col in line.split("|")]
        if len(cols) < 4:
            continue
        net, sta, lat_s, lon_s = cols[0], cols[1], cols[2], cols[3]
        if len(cols) >= 8 and cols[7]:
            continue
        lat = _num(lat_s)
        lon = _num(lon_s)
        if lat is None or lon is None:
            continue
        if abs(lat) > 90.0 or abs(lon) > 180.0:
            continue
        if not net or not sta:
            continue
        eid = f"{prefix}:{net}.{sta}"
        if eid in seen:
            continue
        seen.add(eid)
        site = cols[5] if len(cols) > 5 else ""
        label = (site or f"{net} {sta}").strip()
        pos = lla_to_ecef(lat, lon, 0.0)
        out.append(
            Entity(
                id=eid,
                cls="station",
                layer="sites",
                label=label[:80],
                x=pos[0],
                y=pos[1],
                z=pos[2],
                source=source,
                freshness="reconstructed",
                confidence=0.8,
                cite=cite,
                meta={"lat": lat, "lon": lon, "network": net, "station": sta},
                coverage=Coverage(
                    "catalog",
                    "Published seismometer site. Not a quake. Not a face.",
                ),
                pii="none",
            )
        )
        if len(out) >= _CAP:
            break
    return out


def _fetch_one(
    url: str, pin: str, prefix: str, source: str, cite: str
) -> list[Entity] | None:
    text = _get_text(url, pin)
    if text is None:
        return None
    pins = entities_from_fdsn_text(text, prefix=prefix, source=source, cite=cite)
    return pins or None


def _get_text(url: str, pin: str) -> str | None:
    host = urlparse(url).hostname
    if not _host_pinned(host, pin):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": _UA})
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname, pin):
                return None
            return resp.text
    except Exception:
        return None


def _host_pinned(host: str | None, pin: str) -> bool:
    if not host:
        return False
    name = host.lower()
    return name == pin or name.endswith("." + pin)


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
