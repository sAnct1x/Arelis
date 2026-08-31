"""Find a city, country, state, continent, contact, or home."""

from __future__ import annotations

from typing import Any

from arelis.earth.gazetteer import (
    FALLBACK_COUNTRIES,
    FALLBACK_PLACES,
    GotoHit,
    catalog,
    home_hit,
    resolve_place,
)

__all__ = [
    "GotoHit",
    "fallback_countries",
    "fallback_places",
    "home_hit",
    "resolve_place",
    "suggest",
]


def fallback_places() -> tuple[tuple[str, float, float], ...]:
    return FALLBACK_PLACES


def fallback_countries() -> tuple[tuple[str, float, float], ...]:
    return FALLBACK_COUNTRIES


def suggest(query: str, zone: Any = None, *, limit: int = 8) -> list[GotoHit]:
    q = (query or "").strip().casefold()
    hits: list[GotoHit] = []
    seen: set[tuple[str, str]] = set()

    def take(hit: GotoHit) -> None:
        key = (hit.kind, hit.name.casefold())
        if key in seen:
            return
        if q and q not in hit.name.casefold() and q not in hit.kind:
            if not (hit.entity_id and q in hit.entity_id.casefold()):
                return
        seen.add(key)
        hits.append(hit)

    for hit in catalog():
        take(hit)
    if zone is not None and getattr(zone, "active", False) and q:
        try:
            from arelis.earth.lod import entity_lla

            for ent in zone.search(query):
                pair = entity_lla(ent)
                if pair is None:
                    continue
                take(
                    GotoHit(
                        "contact" if ent.layer == "people" else ent.layer,
                        ent.label,
                        pair[0],
                        pair[1],
                        ent.id,
                    )
                )
        except Exception:
            pass

    def rank(hit: GotoHit) -> tuple[int, int, str]:
        name = hit.name.casefold()
        if q and name == q:
            prefix = 0
        elif q and name.startswith(q):
            prefix = 1
        elif q and q in name:
            prefix = 2
        else:
            prefix = 3
        kind_order = {
            "home": 0,
            "continent": 1,
            "country": 2,
            "state": 3,
            "city": 4,
        }.get(hit.kind, 5)
        return (prefix, kind_order, hit.name)

    return sorted(hits, key=rank)[:limit]
