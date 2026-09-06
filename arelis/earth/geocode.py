"""Nominatim street-address search. User-typed, 1 req/s, not a crawl.

Gazetteer cities stay local. Contacts stay on their stored lat/lon —
never geocoded from a name. Hosts pinned in tests/test_egress.py.
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Any

import httpx

from arelis import __source_url__, __version__
from arelis.earth.gazetteer import GotoHit

NOMINATIM = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HOST = "nominatim.openstreetmap.org"
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 4.0
_MIN_GAP_S = 1.05
_STREET = re.compile(
    r"(?i)\b("
    r"st|street|ave|avenue|rd|road|blvd|boulevard|dr|drive|ln|lane|"
    r"ct|court|way|hwy|highway|pkwy|parkway|pl|place|cir|circle|"
    r"apt|suite|unit|pike|terrace|ter"
    r")\b"
)
_lock = threading.Lock()
_cache: dict[str, tuple[GotoHit, ...]] = {}
_last_unix = 0.0


def looks_like_address(query: str) -> bool:
    """True when the text is a street address, not a city name."""
    q = (query or "").strip()
    if len(q) < 5:
        return False
    words = q.split()
    if any(ch.isdigit() for ch in q) and len(q) >= 6:
        return True
    if "," in q and len(words) >= 2:
        return True
    return bool(_STREET.search(q) and len(words) >= 2)


def _fold(query: str) -> str:
    return " ".join((query or "").strip().casefold().split())


def _kind_for(row: dict[str, Any]) -> str:
    addresstype = str(row.get("addresstype") or row.get("type") or "").casefold()
    if addresstype in {"city", "town", "village", "municipality", "suburb"}:
        return "city"
    if addresstype in {"state", "province", "region"}:
        return "state"
    if addresstype in {"country"}:
        return "country"
    return "address"


def search_address(query: str, *, limit: int = 5, force: bool = False) -> list[GotoHit]:
    """Resolve a typed or spoken place. Empty under pytest unless cached.

    ``force`` is Enter / take-me-to — city + state, not only a street line.
    """
    key = _fold(query)
    if not key:
        return []
    with _lock:
        cached = _cache.get(key)
    if cached is not None:
        return list(cached)[:limit]
    if not force and not looks_like_address(query):
        return []
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return []
    global _last_unix
    with _lock:
        wait = _MIN_GAP_S - (time.monotonic() - _last_unix)
    if wait > 0.0:
        time.sleep(min(wait, _MIN_GAP_S))
    try:
        response = httpx.get(
            NOMINATIM,
            params={
                "q": query.strip(),
                "format": "jsonv2",
                "limit": str(max(1, min(8, int(limit)))),
                "addressdetails": "0",
            },
            headers={"User-Agent": _UA, "Accept": "application/json"},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        rows = response.json()
    except Exception:
        return []
    with _lock:
        _last_unix = time.monotonic()
    hits: list[GotoHit] = []
    seen: set[str] = set()
    if not isinstance(rows, list):
        return []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        name = str(row.get("display_name") or "").strip()
        if not name:
            continue
        fold = name.casefold()
        if fold in seen:
            continue
        seen.add(fold)
        hit = GotoHit(_kind_for(row), name, lat, lon)
        hits.append(hit)
    frozen = tuple(hits)
    with _lock:
        _cache[key] = frozen
        for hit in frozen:
            _cache.setdefault(_fold(hit.name), frozen)
    return list(frozen)[:limit]


def remember_hits(query: str, hits: list[GotoHit]) -> None:
    """Test helper — seed the cache without opening the network."""
    key = _fold(query)
    if not key:
        return
    frozen = tuple(hits)
    with _lock:
        _cache[key] = frozen
        for hit in frozen:
            _cache.setdefault(_fold(hit.name), frozen)


def clear_cache() -> None:
    with _lock:
        _cache.clear()
