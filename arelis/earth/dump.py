"""Cited Earth-zone dump. Receipt, not a screenshot."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arelis.earth.runtime import EarthRuntime
from arelis.paths import outputs_dir

SCHEMA = 1
FRAME = "ECEF"
CENTER = "Earth"
UNITS = "SI"


def dumps_root() -> Path:
    return outputs_dir() / "physics" / "earth"


def _camera_block(camera: Any) -> dict[str, list[float]] | None:
    """Eye / look / up only. Never copy a URL or other string payload."""
    if camera is None:
        return None
    src: dict[str, Any]
    if hasattr(camera, "eye") and hasattr(camera, "look") and hasattr(camera, "up"):
        src = {"eye": camera.eye, "look": camera.look, "up": camera.up}
    elif isinstance(camera, dict):
        src = camera
    else:
        return None
    out: dict[str, list[float]] = {}
    for key in ("eye", "look", "up"):
        val = src.get(key) if isinstance(src, dict) else None
        if not isinstance(val, (list, tuple)) or len(val) < 3:
            continue
        try:
            out[key] = [float(val[0]), float(val[1]), float(val[2])]
        except (TypeError, ValueError):
            continue
    return out or None


def view_receipt(
    earth: EarthRuntime, *, camera: Any | None = None
) -> dict[str, Any]:
    """Shareable view: band, chips, one target. No stream URLs."""
    view = earth.last_view
    payload: dict[str, Any] = {
        "center": CENTER,
        "frame": FRAME,
        "live": earth.live,
        "layers": {key: on for key, on in earth.layers.items() if on},
        "track_id": earth.track_id,
        "ride_id": earth.ride_id,
        "target": earth.ride_id or earth.track_id,
        "display": {
            "grid": bool(earth.grid),
            "tiles": bool(earth.tiles),
            "buildings": bool(earth.buildings),
        },
    }
    if view is not None:
        payload["view"] = {
            "band": view.band,
            "lat": view.lat,
            "lon": view.lon,
            "alt_m": view.alt_m,
            "px_r": view.px_r,
        }
    cam = _camera_block(camera)
    if cam is not None:
        payload["camera"] = cam
    return payload


def dump_state(
    earth: EarthRuntime,
    *,
    root: Path | None = None,
    stamp: str | None = None,
    trigger: str = "dump",
    camera: Any | None = None,
) -> Path:
    base = root if root is not None else dumps_root()
    folder = _unique_folder(base, stamp or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    folder.mkdir(parents=True, exist_ok=True)
    rows = [e.to_row() for e in earth.store.all()]
    receipt = view_receipt(earth, camera=camera)
    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "center": CENTER,
        "frame": FRAME,
        "units": UNITS,
        "trigger": trigger,
        "active": earth.active,
        "live": earth.live,
        "n": len(rows),
        "layers": dict(earth.layers),
        "track_id": earth.track_id,
        "ride_id": earth.ride_id,
        "entered_unix": earth.entered_unix,
        "note": earth.note,
        "view": receipt.get("view"),
        "display": receipt.get("display"),
        "camera": receipt.get("camera"),
        "target": receipt.get("target"),
        "warning": (
            "Not for navigation, emergency, or targeting. "
            "Simulated layers are labeled simulated. "
            "Individual cars are a labeled hole."
        ),
    }
    (folder / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with (folder / "state.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    try:
        from arelis.physics.telemetry import emit

        emit("earth_dump", trigger=trigger, n=len(rows), live=earth.live)
    except Exception:
        pass
    return folder


def _unique_folder(base: Path, stamp: str) -> Path:
    folder = base / stamp
    if not folder.exists():
        return folder
    n = 2
    while True:
        alt = base / f"{stamp}-{n}"
        if not alt.exists():
            return alt
        n += 1
