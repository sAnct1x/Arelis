"""Cited solar-state dump. The receipt, not a screenshot.

Headless: no Qt. Writes manifest.json + state.jsonl under
outputs/physics/solar/<utc>/. Belt tracers are omitted unless asked.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arelis.paths import outputs_dir
from arelis.physics.constants import BODY_BY_NAME, G_SI
from arelis.physics.horizons import VectorState
from arelis.physics.ic_store import vectors_hash
from arelis.physics.parker import CITE as WIND_CITE
from arelis.physics.scene import SolarSystem

SCHEMA = 1
FRAME = "ECLIPJ2000"
CENTER = "SSB"
UNITS = "SI"

OVERLAY_CITES: dict[str, str] = {
    "gravity": "Newtonian Φ / Hill / iso-|g|. Not GR.",
    "magnetic": "Earth magnetopause. Shue 1998, ram from Parker. Not IGRF.",
    "wind": WIND_CITE,
    "grid": "Body-fixed IAU WGCCRE 2015 when that frame exists.",
    "osculating": "Two-body Kepler about the catalog parent.",
    "trails": "Recent IAS15 path, not a fitted orbit.",
    "graphs": "Energy residual HUD, not a publication plot.",
    "lagrange": "Sun-Earth / Sun-Jupiter CR3BP sketches. Not N-body equilibria.",
}


def ic_hash(states: dict[str, VectorState], day_iso: str) -> str:
    """SHA-256 of the Horizons VECTORS used at load. Same as vectors_hash."""
    return vectors_hash(states, day_iso)


def dumps_root() -> Path:
    return outputs_dir() / "physics" / "solar"


def dump_state(
    system: SolarSystem,
    *,
    include_tracers: bool = False,
    camera: dict[str, Any] | None = None,
    root: Path | None = None,
    stamp: str | None = None,
    trigger: str = "dump",
) -> Path:
    """Write one cited snapshot. Returns the folder. Does not capture GL."""
    base = root if root is not None else dumps_root()
    folder = _unique_folder(base, stamp or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    folder.mkdir(parents=True, exist_ok=True)
    rows = _state_rows(system, include_tracers=include_tracers)
    tracers_omitted = (not include_tracers) and any(
        p.tracer for p in system.nbody.particles
    )
    manifest = {
        "schema": SCHEMA,
        "center": CENTER,
        "frame": FRAME,
        "units": UNITS,
        "trigger": trigger,
        "t_s": system.t,
        "ic_date": system.ic_date,
        "ic_hash": system.ic_hash,
        "epoch_tdb": system.epoch_tdb,
        "epoch_jd": system.epoch_jd,
        "integrator": system.integrator_note,
        "energy_residual": system.energy_residual(),
        "counterfactual": system.counterfactual,
        "paused": system.paused,
        "rate": system.rate,
        "lock": system.lock,
        "n": len(rows),
        "tracers_omitted": tracers_omitted,
        "still": False,
        "still_note": "GL still not in this bundle.",
        "camera": camera,
        "overlay": _overlay_block(system),
        "layers": {
            "measured": True,
            "model": _model_flags(system),
            "instrument": [],
        },
    }
    (folder / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        json.dumps(row, separators=(",", ":"), ensure_ascii=True) for row in rows
    ]
    (folder / "state.jsonl").write_text(
        ("\n".join(lines) + ("\n" if lines else "")),
        encoding="utf-8",
    )
    return folder


def dump_on_leave(
    *,
    camera: dict[str, Any] | None = None,
    root: Path | None = None,
) -> Path | None:
    """Receipt when leaving the solar lab. No-op if nothing is loaded. Never raises."""
    from arelis.physics.runtime import get_system

    system = get_system()
    if system is None:
        return None
    try:
        return dump_state(system, camera=camera, root=root, trigger="leave")
    except OSError:
        return None


def _unique_folder(base: Path, stamp: str) -> Path:
    folder = base / stamp
    if not folder.exists():
        return folder
    n = 2
    while True:
        candidate = base / f"{stamp}-{n}"
        if not candidate.exists():
            return candidate
        n += 1


def _gm_for(name: str, mass: float) -> float:
    spec = BODY_BY_NAME.get(name)
    if spec is not None:
        return float(spec.gm)
    return float(mass) * G_SI


def _include_particle(system: SolarSystem, *, tracer: bool, name: str, include_tracers: bool) -> bool:
    if include_tracers:
        return True
    if not tracer:
        return True
    return name == system.lock


def _state_rows(
    system: SolarSystem, *, include_tracers: bool
) -> list[dict[str, Any]]:
    t = system.t
    rows: list[dict[str, Any]] = []
    for p in system.nbody.particles:
        if not _include_particle(
            system, tracer=p.tracer, name=p.name, include_tracers=include_tracers
        ):
            continue
        rows.append(
            {
                "t": t,
                "name": p.name,
                "r": [p.x, p.y, p.z],
                "v": [p.vx, p.vy, p.vz],
                "gm": _gm_for(p.name, p.mass),
                "kind": p.kind,
            }
        )
    return rows


def _overlay_block(system: SolarSystem) -> dict[str, dict[str, Any]]:
    flags = _model_flags(system)
    return {
        name: {"on": on, "cite": OVERLAY_CITES[name]}
        for name, on in flags.items()
    }


def _model_flags(system: SolarSystem) -> dict[str, bool]:
    return {
        "gravity": system.overlay.show_gravity,
        "magnetic": system.overlay.show_magnetic,
        "wind": system.overlay.show_wind,
        "grid": system.overlay.show_grid,
        "osculating": system.show_osculating,
        "trails": system.show_trails,
        "graphs": system.show_graphs,
        "lagrange": system.show_lagrange,
    }
