"""Disk cache of fetched JPL Horizons VECTORS. Not an invented catalog."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from arelis.paths import models_dir
from arelis.physics.horizons import VectorState

SCHEMA = 1
SOURCE = "JPL Horizons VECTORS"


def vectors_dir() -> Path:
    return models_dir() / "astro" / "vectors"


def cache_path(day_iso: str) -> Path:
    return vectors_dir() / f"{day_iso}.json"


def load_cached(day_iso: str) -> dict[str, VectorState] | None:
    path = cache_path(day_iso)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if raw.get("schema") != SCHEMA or raw.get("source") != SOURCE:
        return None
    if raw.get("date") != day_iso:
        return None
    bodies = raw.get("bodies")
    if not isinstance(bodies, dict) or "Sun" not in bodies:
        return None
    states: dict[str, VectorState] = {}
    for name, row in bodies.items():
        if not isinstance(name, str) or not isinstance(row, dict):
            return None
        try:
            jd = row.get("jd")
            states[name] = VectorState(
                float(row["x"]),
                float(row["y"]),
                float(row["z"]),
                float(row["vx"]),
                float(row["vy"]),
                float(row["vz"]),
                units="SI",
                epoch_jd=float(jd) if jd is not None else None,
            )
        except (KeyError, TypeError, ValueError):
            return None
    if "Sun" not in states:
        return None
    return states


def vectors_hash(states: dict[str, VectorState], day_iso: str) -> str:
    """SHA-256 of the canonical Horizons VECTORS payload. Not a cache-schema bump.

    Center SSB, ECLIPJ2000, SI, date, and each body's x/y/z/vx/vy/vz/jd.
    Stable across load from disk vs the live fetch that wrote that disk.
    """
    payload = {
        "center": "SSB",
        "frame": "ECLIPJ2000",
        "units": "SI",
        "date": day_iso,
        "bodies": {
            name: {
                "x": st.x,
                "y": st.y,
                "z": st.z,
                "vx": st.vx,
                "vy": st.vy,
                "vz": st.vz,
                "jd": st.epoch_jd,
            }
            for name, st in sorted(states.items())
        },
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("ascii")).hexdigest()


def save_cached(day_iso: str, states: dict[str, VectorState]) -> None:
    if "Sun" not in states:
        return
    vectors_dir().mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SCHEMA,
        "source": SOURCE,
        "center": "SSB",
        "frame": "ECLIPJ2000",
        "units": "SI",
        "date": day_iso,
        "bodies": {
            name: {
                "x": st.x,
                "y": st.y,
                "z": st.z,
                "vx": st.vx,
                "vy": st.vy,
                "vz": st.vz,
                "jd": st.epoch_jd,
            }
            for name, st in states.items()
        },
    }
    cache_path(day_iso).write_text(json.dumps(payload), encoding="utf-8")


def cached_days() -> list[str]:
    root = vectors_dir()
    if not root.is_dir():
        return []
    days: list[str] = []
    for path in root.glob("*.json"):
        stem = path.stem
        try:
            date.fromisoformat(stem)
        except ValueError:
            continue
        if load_cached(stem) is not None:
            days.append(stem)
    days.sort()
    return days


def nearest_cached(day_iso: str) -> tuple[str, dict[str, VectorState]] | None:
    """Closest labeled Horizons VECTOR dump on disk, or None."""
    days = cached_days()
    if not days:
        return None
    try:
        want = date.fromisoformat(day_iso)
    except ValueError:
        day = days[-1]
        loaded = load_cached(day)
        return (day, loaded) if loaded else None
    day = min(days, key=lambda item: abs((date.fromisoformat(item) - want).days))
    loaded = load_cached(day)
    return (day, loaded) if loaded else None
