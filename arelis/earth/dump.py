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


def dump_state(
    earth: EarthRuntime,
    *,
    root: Path | None = None,
    stamp: str | None = None,
    trigger: str = "dump",
) -> Path:
    base = root if root is not None else dumps_root()
    folder = _unique_folder(base, stamp or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    folder.mkdir(parents=True, exist_ok=True)
    rows = [e.to_row() for e in earth.store.all()]
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
