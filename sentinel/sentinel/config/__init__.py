"""Configuration loader and visual theme tokens for Sentinel."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from sentinel.paths import PACKAGE_ROOT, data_dir

_DEFAULT_YAML = PACKAGE_ROOT / "config" / "default.yaml"

# Exact palette tokens derived from Arelis's theme_tokens.py & filament_field.py,
# plus a "matrix" subterranean obsidian/crimson mode.
THEME_PALETTES: dict[str, dict[str, Any]] = {
    "sodium": {
        "id": "sodium",
        "label": "Sodium (Default Lamp)",
        "bg0": "#100d0b",
        "bg1": "#2a221c",
        "bg2": "#40342b",
        "void_rgb": [16, 13, 11],
        "core_hex": "#ffe4cc",
        "core_halo_hex": "#ffb06c",
        "accent": "#ff7a22",
        "accent2": "#ffc08a",
        "text": "#f8f1ea",
        "text_dim": "#d4a484",
        "warn": "#ff5e12",
        "danger": "#ff2a3a",
        "sentinel_armor": "#231e1b",
        "sentinel_eye": "#ff2a3a",
        "laser_harvest": "#ff9844",
        "laser_sanitize": "#52e5a8",
        "laser_defense": "#ff1e27",
        "wall_hex": "#ff7a22",
        "filament_strands": False,
    },
    "filament": {
        "id": "filament",
        "label": "Filament (Coil, Current & Dust)",
        "bg0": "#07080b",
        "bg1": "#101218",
        "bg2": "#181c24",
        "void_rgb": [7, 8, 11],
        "core_hex": "#ffecd2",
        "core_halo_hex": "#d4a860",
        "accent": "#c4a06a",
        "accent2": "#e4c896",
        "text": "#e8d4b0",
        "text_dim": "#d4c1a1",
        "warn": "#d4783c",
        "danger": "#ff3344",
        "sentinel_armor": "#181c24",
        "sentinel_eye": "#ff3344",
        "laser_harvest": "#d4a860",
        "laser_sanitize": "#b0c8d8",
        "laser_defense": "#ff2a3a",
        "wall_hex": "#c4a06a",
        "ice_rgb": [176, 200, 216],
        "gold_rgb": [212, 168, 96],
        "filament_strands": True,
    },
    "night": {
        "id": "night",
        "label": "Night (Brand Purple Ring & White Star)",
        "bg0": "#060a20",
        "bg1": "#0b0c26",
        "bg2": "#161436",
        "void_rgb": [6, 10, 32],
        "core_hex": "#ffffff",
        "core_halo_hex": "#8060b0",
        "accent": "#8050b0",
        "accent2": "#9088a8",
        "text": "#ffffff",
        "text_dim": "#847c9c",
        "warn": "#b060d0",
        "danger": "#ff2a55",
        "sentinel_armor": "#14132e",
        "sentinel_eye": "#ff2a55",
        "laser_harvest": "#a474e8",
        "laser_sanitize": "#50e2d0",
        "laser_defense": "#ff1e42",
        "wall_hex": "#8050b0",
        "filament_strands": False,
    },
    "matrix": {
        "id": "matrix",
        "label": "Zion Subterranean (Obsidian & Crimson)",
        "bg0": "#040508",
        "bg1": "#0a0e14",
        "bg2": "#121924",
        "void_rgb": [4, 5, 8],
        "core_hex": "#d4a484",
        "core_halo_hex": "#ff2a3a",
        "accent": "#ff2a3a",
        "accent2": "#00e5ff",
        "text": "#e6edf3",
        "text_dim": "#8b949e",
        "warn": "#ff7b00",
        "danger": "#ff1122",
        "sentinel_armor": "#141a22",
        "sentinel_eye": "#ff1122",
        "laser_harvest": "#00e5ff",
        "laser_sanitize": "#00ff88",
        "laser_defense": "#ff1122",
        "wall_hex": "#00e5ff",
        "filament_strands": True,
    },
}


def resolve_theme(theme_id: str | None) -> dict[str, Any]:
    raw = (theme_id or "sodium").strip().lower()
    if raw in THEME_PALETTES:
        return dict(THEME_PALETTES[raw])
    return dict(THEME_PALETTES["sodium"])


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(override_path: Path | None = None) -> dict[str, Any]:
    """Load default.yaml merged with data/config.local.yaml if present."""
    base: dict[str, Any] = {}
    if _DEFAULT_YAML.is_file():
        base = yaml.safe_load(_DEFAULT_YAML.read_text(encoding="utf-8")) or {}
    local_file = override_path or (data_dir() / "config.local.yaml")
    if local_file.is_file():
        local_data = yaml.safe_load(local_file.read_text(encoding="utf-8")) or {}
        if isinstance(local_data, dict):
            base = _deep_merge(base, local_data)
    return base


def save_local_preferences(
    *,
    theme: str | None = None,
    camera_mode: str | None = None,
    default_tier: str | None = None,
    override_path: Path | None = None,
) -> Path:
    """Persist user UI & swarm preferences to data/config.local.yaml."""
    local_file = override_path or (data_dir() / "config.local.yaml")
    existing: dict[str, Any] = {}
    if local_file.is_file():
        try:
            loaded = yaml.safe_load(local_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except OSError:
            existing = {}

    if theme is not None:
        existing.setdefault("ui", {})["theme"] = str(theme).strip().lower()
    if camera_mode is not None:
        existing.setdefault("ui", {})["camera_mode"] = str(camera_mode).strip().lower()
    if default_tier is not None:
        existing.setdefault("swarm", {})["default_tier"] = str(default_tier).strip().lower()

    local_file.parent.mkdir(parents=True, exist_ok=True)
    local_file.write_text(yaml.safe_dump(existing, sort_keys=False), encoding="utf-8")
    return local_file

