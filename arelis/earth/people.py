"""Contacts as entities. Owned address book only.

A person appears when their card has lat/lon. Unknown people stay off
the map. Coordinates are never geocoded from a name. pii=contact.
No global face index.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from arelis.contacts import CONTACTS_PATH
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef

_CITE = (
    "Owned address-book pin. Coordinates from the contact card, not a "
    "lookup. Unknown people stay off the map. Not a face index."
)


def load_people(path: Path | None = None) -> list[Entity]:
    path = path or CONTACTS_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    section = raw.get("contacts") if isinstance(raw, dict) else None
    if not isinstance(section, dict):
        return []
    out: list[Entity] = []
    for key, value in section.items():
        if not isinstance(value, dict):
            continue
        entity = _entity_from_card(str(key or ""), value)
        if entity is not None:
            out.append(entity)
    return out


def _entity_from_card(alias: str, card: dict[str, Any]) -> Entity | None:
    lat = _num(card.get("lat"))
    lon = _num(card.get("lon"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return None
    name = str(card.get("name") or card.get("title") or alias).strip() or alias
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"contact:{alias.strip().casefold()}",
        cls="person",
        layer="people",
        label=name,
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="contacts.yaml",
        freshness="reconstructed",
        confidence=0.9,
        cite=_CITE,
        meta={"lat": lat, "lon": lon, "alias": alias.strip().casefold()},
        pii="contact",
        coverage=Coverage(
            "owned",
            "Only people with coordinates on the card. Everyone else is a hole.",
        ),
    )


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
