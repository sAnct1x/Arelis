"""Paste the three keys that change the Earth picture.

Never log the value. secrets.yaml stays gitignored. A missing key is a
chip, not a scavenger hunt through a YAML file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from arelis.earth.secrets import SECRETS_PATH, earth_secret

# field, chip label, prompt. Order is the picture: cities, fires, ships.
PICTURE_KEYS: tuple[tuple[str, str, str, str], ...] = (
    (
        "google_maps_key",
        "ARELIS_GOOGLE_MAPS_KEY",
        "Photoreal",
        "Paste a Google Maps tile key",
    ),
    (
        "firms_key",
        "ARELIS_FIRMS_KEY",
        "Fires key",
        "Paste a NASA FIRMS MAP_KEY",
    ),
    (
        "aisstream_key",
        "ARELIS_AISSTREAM_KEY",
        "Ships key",
        "Paste an AISStream key",
    ),
)


def picture_key_state() -> list[tuple[str, str, str, bool]]:
    """(field, chip, prompt, present)."""
    out: list[tuple[str, str, str, bool]] = []
    for field, env, chip, prompt in PICTURE_KEYS:
        out.append((field, chip, prompt, bool(earth_secret(field, env))))
    return out


def missing_picture_keys() -> list[tuple[str, str, str]]:
    return [
        (field, chip, prompt)
        for field, chip, prompt, present in picture_key_state()
        if not present
    ]


def save_earth_key(field: str, value: str, path: Path | None = None) -> bool:
    """Write earth.<field> without clobbering the rest of the file."""
    text = (value or "").strip()
    allowed = {row[0] for row in PICTURE_KEYS}
    if field not in allowed or not text:
        return False
    dest = path or SECRETS_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        raw = yaml.safe_load(dest.read_text(encoding="utf-8")) if dest.is_file() else {}
    except (OSError, yaml.YAMLError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    block: dict[str, Any] = raw.get("earth") if isinstance(raw.get("earth"), dict) else {}
    block[field] = text
    raw["earth"] = block
    dest.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return True
