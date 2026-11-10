"""Overseer frame math: LOD buckets, draw budget, entry Bezier, timeline.

Numbers follow Iris pass 5. Used by the Qt Quick 3D view and by tests.
No GPU claims; this only counts instances against exported mesh totals.
"""

from __future__ import annotations

import json
import math
import re
import time
import unicodedata
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arelis.ui import overseer_curves as _overseer_curves  # noqa: F401

CASTES = ("warden", "stalker", "harvester", "sanitizer", "tripwire")
PARTS = ("head",)
CASTE_COLOR = {
    "warden": "#a78bfa",
    "stalker": "#e879f9",
    "harvester": "#8fd3ff",
    "sanitizer": "#f2c56b",
    "tripwire": "#7ee0c8",
}
# Eye lenses (GAP.md item 1): caste colour; a fetching Harvester's eyes turn
# #2fc4ff, and red is only for a unit engaged on a real threat.
LENS_COLOR = {
    "warden": "#a473f0",
    "stalker": "#e879f9",
    "harvester": "#8fd3ff",
    "sanitizer": "#f2c56b",
    "tripwire": "#7ee0c8",
}
EYE_FETCHING = "#2fc4ff"
EYE_THREAT = "#ff2a3c"
# Unit size at the overview (BAND-SPEC.md "Unit scale at overview").
# Pass E heads are authored in metres (pod length 2.0 m), so UNIT_MESH_SCALE is 1.
# Chat-off 4.5 percent of width needs a Harvester of about 1.70 (1.31 x the
# BAND-SPEC 1.3). Sanitizers are capped at 1.2 so they do not fill the 5.3 m
# lane at 128 units. Fetching stays 1.31 x 1.9 so a live fetch still reads
# larger than an idle Harvester.
OVERVIEW_SCALE = {
    "sanitizer": 1.05,
    "warden": 1.25,
    "stalker": 1.25,
    "harvester": 1.3,
    "tripwire": 1.35,
}
FETCHING_SCALE = 1.9
UNIT_MESH_SCALE = 1.0
CHAT_OFF_SCALE_MULT = 1.31
SANITIZER_SCALE_CAP = 1.2
USE_CHAT_OFF_SCALE = True
LOD0_PX = 180.0
LOD1_PX = 60.0
HYST = 0.15
FOV_DEG = 35.0
# Chosen so 18 m at 35 mm on a 1306 px plate projects about 180 px.
UNIT_WORLD_H = 1.56
PARTICLE_BUDGET = 520
MOTE_FRACTION = 0.40
# orb 5 (core, filaments, 2 shells, one ornament draw for three rings
# plus beads), sources 2, tentacles 3, lanes, perimeter, conduits,
# particles, glyphs, 1 star draw (three parallax layers instanced)
SCENE_FIXED_DRAW = 16
MAX_UNIT_DRAW = 6  # 3 LOD x (1 head + 1 tentacle); tentacles stay in the fixed count
MAX_TRIS = 300_000


def asset_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "sentinel" / "overseer"


def load_mesh_report(path: Path | None = None) -> dict[str, Any]:
    report_path = path or (asset_dir() / "export_report.json")
    rows = json.loads(report_path.read_text())
    by_lod = {}
    for row in rows:
        parts = {}
        raw = row.get("tris_by_part") or {}
        for name, count in raw.items():
            # lod0_hull -> hull
            part = name.split("_", 1)[-1]
            if name.endswith("_head"):
                part = "head"
            elif name.endswith("_tentacle"):
                part = "tentacle"
            elif name.endswith("_hull"):
                part = "hull"
            elif name.endswith("_emissive"):
                part = "emissive"
            elif name.endswith("_lens"):
                part = "lens"
            parts[part] = int(count)
        by_lod[int(row["lod"])] = {
            "tris": int(row["tris"]), "parts": parts, "target": int(row["target"]),
            "strands": int(row.get("strands") or 0),
        }
    return by_lod


def projected_height_px(distance: float, viewport_h: float = 1306.0, scale: float = 1.0) -> float:
    d = max(0.1, float(distance))
    half = math.tan(math.radians(FOV_DEG) / 2.0)
    return (UNIT_WORLD_H * float(scale) * float(viewport_h)) / (d * 2.0 * half)


def choose_lod(height_px: float, prev_lod: int | None = None) -> int:
    enter0 = LOD0_PX * (1 + HYST)
    leave0 = LOD0_PX * (1 - HYST)
    enter1 = LOD1_PX * (1 + HYST)
    leave1 = LOD1_PX * (1 - HYST)
    if prev_lod is None:
        if height_px > LOD0_PX:
            return 0
        if height_px > LOD1_PX:
            return 1
        return 2
    lod = prev_lod
    if lod == 0:
        if height_px < leave0:
            lod = 2 if height_px < leave1 else 1
    elif lod == 1:
        if height_px > enter0:
            lod = 0
        elif height_px < leave1:
            lod = 2
    else:
        if height_px > enter0:
            lod = 0
        elif height_px > enter1:
            lod = 1
    return lod


def claw_open(state: str | None) -> float:
    s = str(state or "").upper()
    if "ENGAGED_DEFENSE" in s or s.endswith("DEFENSE"):
        return 0.85
    if "ENGAGED" in s or "VECTORING" in s or "PURSUIT" in s:
        return 0.7
    if "QUARANTIN" in s:
        return 0.3
    if "HARVEST" in s or "CARRY" in s:
        return 0.2
    if "PATROL" in s or not s or s == "IDLE":
        return 0.45
    return 0.45


def tentacle_speed(state: str | None) -> float:
    """GPU tentacle wave speed from real unit activity. Idle sways; busy curls faster."""
    s = str(state or "").upper()
    if "EMP" in s or "HALT" in s:
        return 0.05
    if "ENGAGED_DEFENSE" in s or s.endswith("DEFENSE"):
        return 2.5
    if "ENGAGED" in s or "VECTORING" in s or "PURSUIT" in s:
        return 2.2
    if "HARVEST" in s or "CARRY" in s or "RETURNING" in s:
        return 1.8
    if "QUARANTIN" in s:
        return 1.1
    if "PATROL" in s or not s or s == "IDLE":
        return 0.55
    return 0.55


# Caste bands (Iris BAND-SPEC.md, Nov 9). Spec space is +Z up; the scene is
# +Y up, so spec (x, y, z) draws at (x, z, -y). Values are the spec's fitted
# starting values. caste: (base radius, lane gap, tilt_x, tilt_y, height, lap s)
BAND_SPEC: dict[str, tuple[float, float, float, float, float, float]] = {
    "sanitizer": (3.6, 1.00, 0.30, 0.08, 0.9, 60.0),
    "warden": (7.95, 1.25, -0.16, 0.26, -0.5, 90.0),
    "harvester": (15.2, 1.35, 0.10, -0.18, 0.4, 120.0),
}
BAND_OF_CASTE = {
    "sanitizer": "sanitizer",
    "warden": "warden",
    "stalker": "warden",
    "harvester": "harvester",
}
PERIMETER_MIN = 35.0
PERIMETER_MARGIN = 10.0
SOURCE_PAST_PERIMETER = 5.0
TRIPWIRE_LAP_S = 180.0
TRIPWIRE_Y = 0.25
MAX_OVERSEER_UNITS = 128


def _patrolling(state: object) -> bool:
    # Only units the hive reports as idle; a missing state keeps its own position.
    s = str(state or "").upper()
    return s in {"IDLE", "DOCKED"} or "PATROL" in s


def band_layout(counts: dict[str, int]) -> dict[str, Any]:
    """Lane count, radii and perimeter from units per caste (spec scaling rule)."""
    bands: list[dict[str, Any]] = []
    width_h = 0.0
    radius_h = 0.0
    for band, (base, gap, tx, ty, height, lap) in BAND_SPEC.items():
        n = sum(c for caste, c in counts.items() if BAND_OF_CASTE.get(caste) == band)
        lanes = max(2, min(4, math.ceil(n / 12) if n else 2))
        radius = base + 1.1 * math.sqrt(max(n, 1))
        width = (lanes - 1) * gap
        if band == "harvester":
            radius_h, width_h = radius, width
        lane_rows = []
        for i in range(lanes):
            off = i - (lanes - 1) / 2.0
            omega = (2.0 * math.pi / lap) * (1.0 + 0.08 * (lanes - 1 - i) / (lanes - 1))
            lane_rows.append(
                {"r": round(radius + off * gap, 4), "z": round(off * 0.25, 4), "omega": omega}
            )
        bands.append({
            "caste": band, "units": n, "lanes": lane_rows, "radius": round(radius, 4),
            "width": round(width, 4), "tilt_x": tx, "tilt_y": ty, "height": height,
            "color": CASTE_COLOR[band],
        })
    perimeter = max(PERIMETER_MIN, radius_h + width_h / 2.0 + PERIMETER_MARGIN)
    return {
        "bands": bands,
        "perimeter": round(perimeter, 4),
        "sourceRadius": round(perimeter + SOURCE_PAST_PERIMETER, 4),
    }


def band_point(
    band: dict[str, Any], lane: dict[str, Any], theta: float
) -> tuple[float, float, float]:
    """Scene position of angle theta on one lane: Rx(tilt_x) * Ry(tilt_y), then height."""
    x, y, z = math.cos(theta) * lane["r"], math.sin(theta) * lane["r"], lane["z"]
    cy, sy = math.cos(band["tilt_y"]), math.sin(band["tilt_y"])
    x, z = x * cy + z * sy, -x * sy + z * cy
    cx, sx = math.cos(band["tilt_x"]), math.sin(band["tilt_x"])
    y, z = y * cx - z * sx, y * sx + z * cx
    return (x, z + band["height"], -y)


def _orbit(
    tilt_x: float, tilt_y: float, height: float, lane: dict[str, Any], theta: float
) -> list[float]:
    """[tilt_x, tilt_y, height, r, z, omega, theta]: the view moves a lane unit itself.

    band_point(band, lane, theta + omega * dt) is where the unit is dt seconds after
    this snapshot, so the view needs a new frame only when something else changes.
    """
    return [
        float(tilt_x), float(tilt_y), float(height),
        float(lane["r"]), float(lane["z"]), float(lane["omega"]),
        round(math.fmod(theta, 2.0 * math.pi), 6),
    ]


def place_band_units(
    units: list[dict[str, Any]], snapshot_ts: float | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Put idle units on their caste lane; working units keep their hive position.

    Lanes: units in a band are dealt round-robin in id order (creation order),
    evenly spaced, lanes interleaved, inner lanes lap 8% faster. Position is a
    pure function of the snapshot clock, so laps stay continuous between polls
    and the view extrapolates along the tangent velocity it is given.
    """
    t = float(snapshot_ts or 0.0)
    counts: dict[str, int] = {}
    for u in units:
        caste = str(u.get("caste") or "").lower()
        counts[caste] = counts.get(caste, 0) + 1
    layout = band_layout(counts)
    by_band = {b["caste"]: b for b in layout["bands"]}
    members: dict[str, list[int]] = {}
    tripwires: list[int] = []
    for idx, u in enumerate(units):
        caste = str(u.get("caste") or "").lower()
        if caste == "tripwire":
            tripwires.append(idx)
        elif caste in BAND_OF_CASTE:
            members.setdefault(BAND_OF_CASTE[caste], []).append(idx)
    out = [dict(u) for u in units]

    def put(
        idx: int,
        pos: tuple[float, float, float],
        vel: tuple[float, float, float],
        orbit: list[float],
    ) -> None:
        row = out[idx]
        if not _patrolling(row.get("state")):
            return
        row["position"] = [round(c, 4) for c in pos]
        row["velocity"] = [round(c, 4) for c in vel]
        speed = math.hypot(vel[0], vel[2])
        if speed > 1e-6:
            row["heading"] = [vel[0] / speed, 0.0, vel[2] / speed]
        row["orbit"] = orbit

    for band_id, idxs in members.items():
        band = by_band[band_id]
        lanes = band["lanes"]
        order = sorted(idxs, key=lambda k: str(units[k].get("unit_id") or ""))
        per_lane = [order[i :: len(lanes)] for i in range(len(lanes))]
        for i, lane_units in enumerate(per_lane):
            k = len(lane_units)
            if not k:
                continue
            lane = lanes[i]
            phase = i * 2.0 * math.pi / (k * len(lanes))
            for j, idx in enumerate(lane_units):
                theta = phase + 2.0 * math.pi * j / k + lane["omega"] * t
                a = band_point(band, lane, theta)
                b = band_point(band, lane, theta + 1e-3)
                vel = tuple((bb - aa) / 1e-3 * lane["omega"] for aa, bb in zip(a, b, strict=True))
                orbit = _orbit(band["tilt_x"], band["tilt_y"], band["height"], lane, theta)
                put(idx, a, vel, orbit)  # type: ignore[arg-type]
    n_trip = len(tripwires)
    if n_trip:
        r = layout["perimeter"]
        omega = 2.0 * math.pi / TRIPWIRE_LAP_S
        order = sorted(tripwires, key=lambda k: str(units[k].get("unit_id") or ""))
        for j, idx in enumerate(order):
            theta = 0.3 + 2.0 * math.pi * j / n_trip + omega * t
            pos = (math.cos(theta) * r, TRIPWIRE_Y, -math.sin(theta) * r)
            vel = (-math.sin(theta) * r * omega, 0.0, -math.cos(theta) * r * omega)
            ring = {"r": r, "z": 0.0, "omega": omega}
            put(idx, pos, vel, _orbit(0.0, 0.0, TRIPWIRE_Y, ring, theta))
    return out, layout


def apply_tentacle_layout(units: list[dict[str, Any]]) -> None:
    """lenMul and kappa from the unit's lane gap and radius (SPEC 4.2 / 5.2)."""
    from collections import defaultdict

    from arelis.ui.overseer_curves import lane_len_mul

    lanes: dict[tuple[float, float], list[int]] = defaultdict(list)
    for i, u in enumerate(units):
        orb = u.get("orbit")
        if isinstance(orb, (list, tuple)) and len(orb) >= 4:
            lanes[(round(float(orb[3]), 4), round(float(orb[2]), 4))].append(i)
        else:
            u.setdefault("lenMul", 1.0)
            u.setdefault("kappa", 0.0)
    for (radius, _height), idxs in lanes.items():
        gap = (2.0 * math.pi * max(radius, 0.1)) / max(len(idxs), 1)
        for i in idxs:
            scale = float(units[i].get("scale") or 1.0)
            units[i]["lenMul"] = round(lane_len_mul(gap, scale), 4)
            units[i]["kappa"] = round((1.0 / max(radius, 0.1)) * scale, 5)


# Front tentacle reach: one pair per open harvest fetch, capped at the
# three front pairs the close-up mesh has.
MAX_REACH_PAIRS = 3
OPEN_FETCH_STATUSES = frozenset({"active", "extracting", "sanitizing"})


def open_fetch_counts(
    units: list[dict[str, Any]] | None = None,
    nodes: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    """Open harvest fetches per unit id, from the snapshot only.

    The hive spawns one harvest_target node per fetch (metadata.unit_id names
    the unit) and removes it when the result is back, so an open node is an
    open request. A unit whose target_node_id points at an open node also
    counts it once.
    """
    open_nodes: dict[str, str] = {}
    per_unit: dict[str, set[str]] = {}
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        if str(node.get("kind") or "").lower() != "harvest_target":
            continue
        if str(node.get("status") or "active").lower() not in OPEN_FETCH_STATUSES:
            continue
        nid = str(node.get("node_id") or "")
        meta = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
        owner = str(meta.get("unit_id") or "")
        if nid:
            open_nodes[nid] = owner
        if owner:
            per_unit.setdefault(owner, set()).add(nid or f"anon-{len(per_unit)}")
    for unit in units or []:
        if not isinstance(unit, dict):
            continue
        uid = str(unit.get("unit_id") or "")
        tid = str(unit.get("target_node_id") or "")
        if uid and tid and tid in open_nodes:
            per_unit.setdefault(uid, set()).add(tid)
    return {uid: len(ids) for uid, ids in per_unit.items()}


def unit_fetching(unit: dict[str, Any]) -> bool:
    """A unit with an open harvest request, or one the hive reports harvesting."""
    state = str(unit.get("state") or "").upper()
    return int(unit.get("open_fetches") or 0) > 0 or state == "ENGAGED_HARVEST"


def view_scale(unit: dict[str, Any]) -> float:
    """Draw scale from the BAND-SPEC caste size, not the hive tier scale.

    The hive's tier scale (mk1 0.35, mk2 0.42, mk3 0.50) sizes separation in
    the hive and was drawn as is, so every unit was about a third of the
    BAND-SPEC overview size and its eye was under a pixel.
    """
    caste = str(unit.get("caste") or "warden").lower()
    if unit_fetching(unit):
        spec = FETCHING_SCALE
        if USE_CHAT_OFF_SCALE:
            spec *= CHAT_OFF_SCALE_MULT
    else:
        spec = OVERVIEW_SCALE.get(caste, 1.25)
        if USE_CHAT_OFF_SCALE:
            spec *= CHAT_OFF_SCALE_MULT
            if caste == "sanitizer":
                spec = min(spec, SANITIZER_SCALE_CAP)
    return round(spec * UNIT_MESH_SCALE, 4)


def eye_color(unit: dict[str, Any], caste: str) -> str:
    state = str(unit.get("state") or "").upper()
    if "ENGAGED_DEFENSE" in state:
        return EYE_THREAT
    if caste == "harvester" and unit_fetching(unit):
        return EYE_FETCHING
    return LENS_COLOR[caste]


# Hive activity for the starfield drift: open requests, saturating at this many.
ACTIVITY_FULL_REQUESTS = 3


def hive_activity(fetches: dict[str, int]) -> float:
    """0 when idle up to 1 at ACTIVITY_FULL_REQUESTS open requests."""
    return round(min(1.0, sum(fetches.values()) / ACTIVITY_FULL_REQUESTS), 4)


def unit_engaged_defense(unit: dict[str, Any]) -> bool:
    return "ENGAGED_DEFENSE" in str(unit.get("state") or "").upper()


def unit_engaged(unit: dict[str, Any]) -> bool:
    return "ENGAGED" in str(unit.get("state") or "").upper()


def threat_is_open(units: list[dict[str, Any]] | None, nodes: list[dict[str, Any]] | None) -> bool:
    if any(unit_engaged_defense(u) for u in units or [] if isinstance(u, dict)):
        return True
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        if str(node.get("kind") or "").lower() == "threat":
            return True
    return False


def apply_lod_policy(
    assigned: list[dict[str, Any]], selected_id: str | None = None
) -> list[dict[str, Any]]:
    """LOD1 for fetchers, engaged units and the focused unit; LOD0 only in close-up.

    choose_lod already promotes to LOD0 when the projected height is large enough.
    This only lifts overview (LOD2) units that must stay detailed, and never
    forces the nearest 16 to LOD1.
    """
    focus = str(selected_id or "")
    out = []
    for u in assigned:
        row = dict(u)
        lod = int(row.get("lod", 2))
        uid = str(row.get("unit_id") or "")
        must = unit_fetching(row) or unit_engaged(row) or (focus and uid == focus)
        if must and lod == 2:
            row["lod"] = 1
        if must and int(row["lod"]) >= 1:
            row["lod_forced"] = 1
        out.append(row)
    return out


def orb_energy(tok_rate: float) -> float:
    """0.3 idle floor to 1.0 at 60 tok/s. Never faked."""
    rate = max(0.0, float(tok_rate or 0.0))
    return round(0.3 + 0.7 * min(1.0, rate / 60.0), 4)


def memory_from_last_chat(snap: dict[str, Any] | None) -> int:
    """Memories still in context from before chat was suspended. 0 if unknown."""
    if not isinstance(snap, dict):
        return 0
    metrics = snap.get("metrics") if isinstance(snap.get("metrics"), dict) else {}
    for src in (snap, metrics):
        for key in ("memories_in_context", "memory_count", "context_memories"):
            v = src.get(key)
            if isinstance(v, int):
                return max(0, v)
            if isinstance(v, list):
                return len(v)
            if isinstance(v, float):
                return max(0, int(v))
    return 0


def tools_running(snap: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Running tools from the snapshot only. Empty when nothing is running."""
    if not isinstance(snap, dict):
        return []
    raw = snap.get("tools_running")
    if raw is None and isinstance(snap.get("metrics"), dict):
        raw = snap["metrics"].get("tools_running")
    if isinstance(raw, int):
        return [{"id": f"tool-{i}", "elapsed": 0.0, "timeout": 0.0} for i in range(max(0, raw))]
    out: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for i, row in enumerate(raw):
            if isinstance(row, str):
                out.append({"id": row, "elapsed": 0.0, "timeout": 0.0})
                continue
            if not isinstance(row, dict):
                continue
            timeout = float(row.get("timeout") or 0.0)
            elapsed = float(row.get("elapsed") or 0.0)
            out.append({
                "id": str(row.get("id") or row.get("name") or f"tool-{i}"),
                "elapsed": elapsed,
                "timeout": timeout,
            })
    return out


def orb_state(snap: dict[str, Any] | None, tok_rate: float = 0.0) -> dict[str, Any]:
    tools = tools_running(snap)
    memory = memory_from_last_chat(snap)
    lit_arc = [0.0, 0.0, 2.0]
    if tools:
        t0 = tools[0]
        if t0["timeout"] > 0:
            lit_arc = [0.0, min(1.0, t0["elapsed"] / t0["timeout"]) * 0.08, 2.0]
    return {
        "energy": orb_energy(tok_rate),
        "memoryCount": memory,
        "memoryLabel": f"Memory · {memory} from last chat",
        "toolsCount": len(tools),
        "toolsLabel": f"Tools {len(tools)} running",
        "toolsLitArc": lit_arc,
        "tools": tools,
        "results": orb_result_titles(snap),
    }


def srgb_to_linear(color: str) -> tuple[float, float, float]:
    """Convert an #rrggbb sRGB colour to linear light."""
    c = str(color or "").lstrip("#")
    if len(c) < 6:
        return (0.0, 0.0, 0.0)
    rgb = (int(c[0:2], 16) / 255.0, int(c[2:4], 16) / 255.0, int(c[4:6], 16) / 255.0)
    return tuple(round(ch ** 2.2, 6) for ch in rgb)  # type: ignore[return-value]


def heading_deg(heading: Any) -> float:
    if isinstance(heading, (int, float)):
        return float(heading) * 180.0 / math.pi
    if isinstance(heading, (list, tuple)) and len(heading) >= 3:
        return math.degrees(math.atan2(float(heading[2]), float(heading[0])))
    if isinstance(heading, (list, tuple)) and len(heading) >= 2:
        return math.degrees(math.atan2(float(heading[1]), float(heading[0])))
    return 0.0


def snapshot_units(snap: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not snap or not isinstance(snap, dict):
        return []
    if snap.get("demo") or snap.get("scenario") or snap.get("theater"):
        return []
    out = []
    for u in snap.get("units") or []:
        if not u or not u.get("unit_id"):
            continue
        if u.get("demo") or u.get("synthetic") or u.get("scenario"):
            continue
        out.append(u)
    return out


CASTE_ROLE = {
    "warden": "Defend",
    "stalker": "Hunt",
    "harvester": "Gather",
    "sanitizer": "Quarantine",
    "tripwire": "Watch",
}
LIST_ROW_PX = 44
LIST_POOL = 6
INSPECTOR_COLLAPSE_T = 0.7
UNAVAILABLE = "unavailable"
MISSION_MODES = (
    ("multi", "Multi-source research"),
    ("arxiv", "arXiv harvest"),
    ("horizons", "JPL Horizons"),
    ("wikipedia", "Wikipedia or URL harvest"),
    ("security_audit", "Host socket and Merkle sweep"),
)
LOG_FILTERS = ("all", "threat", "sanitize", "harvest", "tripwire")


def empty_task_label(state: object) -> str:
    if not state:
        return "idle"
    return str(state).replace("_", " ").lower()


def filter_swarm_units(units: list[dict[str, Any]] | None, query: str = "") -> list[dict[str, Any]]:
    rows = list(units or [])
    q = str(query or "").strip().lower()
    if not q:
        return rows
    out = []
    for unit in rows:
        hay = " ".join(
            str(unit.get(key) or "")
            for key in ("unit_id", "caste", "state", "current_task")
        ).lower()
        if q in hay:
            out.append(unit)
    return out


def _is_active(state: object) -> bool:
    """Counts toward a Swarm header's active number (and the status strip's engaged)."""
    s = str(state or "")
    return s.startswith("ENGAGED") or s in {"QUARANTINING", "VECTORING"}


def group_units(units: list[dict[str, Any]] | None, by: str = "caste") -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for unit in units or []:
        if by == "task":
            key = str(unit.get("current_task") or unit.get("state") or "idle")
        elif by == "ring":
            key = str(unit["ring"] if unit.get("ring") is not None else "unassigned")
        else:
            key = str(unit.get("caste") or "unknown")
        if key not in groups:
            groups[key] = {"key": key, "units": [], "active": 0}
            order.append(key)
        groups[key]["units"].append(unit)
        if _is_active(unit.get("state")):
            groups[key]["active"] += 1
    for key in order:
        groups[key]["units"].sort(
            key=lambda u: (
                0 if str(u.get("state") or "").startswith("ENGAGED") else 1,
                str(u.get("unit_id") or ""),
            )
        )
    return [groups[key] for key in order]


def swarm_rows(
    units: list[dict[str, Any]] | None,
    *,
    by: str = "caste",
    query: str = "",
    collapsed: set[str] | list[str] | None = None,
) -> list[dict[str, Any]]:
    hidden = set(collapsed or [])
    rows: list[dict[str, Any]] = []
    for group in group_units(filter_swarm_units(units, query), by):
        rows.append({
            "kind": "header",
            "key": group["key"],
            "count": len(group["units"]),
            "active": group["active"],
            "collapsed": group["key"] in hidden,
        })
        if group["key"] in hidden:
            continue
        for unit in group["units"]:
            rows.append({
                "kind": "unit",
                "key": group["key"],
                "unit_id": unit.get("unit_id"),
                "caste": unit.get("caste"),
                "role": CASTE_ROLE.get(str(unit.get("caste") or ""), unit.get("caste")),
                "state": unit.get("state"),
                "task": unit.get("current_task") or empty_task_label(unit.get("state")),
                "color": CASTE_COLOR.get(str(unit.get("caste") or ""), "#e0d4ff"),
            })
    return rows


def virtual_window(
    scroll_y: float,
    viewport_h: float,
    count: int,
    row_h: int = LIST_ROW_PX,
    pool: int = LIST_POOL,
) -> dict[str, int]:
    first = max(0, int(max(0.0, float(scroll_y)) // row_h))
    visible = max(1, int((float(viewport_h) + row_h - 1) // row_h))
    last = min(int(count), first + visible + int(pool))
    span = last - first
    first = min(first, max(0, int(count) - span))
    first = max(0, first)
    last = min(int(count), first + visible + int(pool))
    return {
        "first": first,
        "last": last,
        "alive": max(0, last - first),
        "rowH": int(row_h),
        "offsetPx": first * int(row_h),
        "spacer": max(0, int(count)) * int(row_h),
    }


def inspector_collapsed(distance: float, selected: str | None) -> bool:
    """True when the dock must stay hidden. Rank 3: only while a unit is selected."""
    return not bool(selected)


def last_event(entries: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """The newest telemetry row as the status strip shows it: time and a short summary."""
    rows = [e for e in entries or [] if isinstance(e, dict)]
    if not rows:
        return None
    entry = rows[-1]
    message = str(entry.get("message") or "")
    done = re.search(r"finished (\w+):(\w+) \(ok=(True|False)", message)
    began = re.search(r"deployed for (\w+):(\w+)", message)
    if done:
        summary = f"{done[1].title()} {done[2].replace('_', ' ')}, " + (
            "ok" if done[3] == "True" else "failed"
        )
    elif began:
        summary = f"{began[1].title()} {began[2].replace('_', ' ')} started"
    else:
        summary = " ".join(message.split()[:6])
    return {
        "seq": entry.get("seq"),
        "time": str(entry.get("iso_time") or "")[:8],
        "summary": summary,
    }


def pill_counts(
    units: list[dict[str, Any]] | None,
    metrics: dict[str, Any] | None = None,
    logs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The status strip's numbers (the header blocks), all from the snapshot."""
    counts = {caste: 0 for caste in CASTES}
    engaged = {caste: 0 for caste in CASTES}
    for unit in units or []:
        caste = str(unit.get("caste") or "").lower()
        if caste in counts:
            counts[caste] += 1
            engaged[caste] += _is_active(unit.get("state"))
    pills: dict[str, Any] = {
        "units": sum(counts.values()),
        **counts,
        "engaged": engaged,
        "lastEvent": last_event(logs),
    }
    if isinstance(metrics, dict) and "warrants_minted" in metrics:
        pills["warrants"] = int(metrics.get("warrants_minted") or 0)
    else:
        pills["warrants"] = UNAVAILABLE
    if isinstance(metrics, dict) and "security_events" in metrics:
        pills["threats"] = int(metrics.get("security_events") or 0)
    else:
        pills["threats"] = UNAVAILABLE
    return pills


def _caste_capabilities(castes: list[dict[str, Any]] | None, caste: str) -> list[str]:
    wanted = str(caste or "").lower()
    for row in castes or []:
        cid = str(row.get("caste_id") or row.get("caste") or "").lower()
        if cid != wanted:
            continue
        caps = row.get("allowed_capabilities") or row.get("capabilities")
        if caps:
            return [str(item) for item in caps if str(item or "").strip()]
    return []


def _unit_warrant(receipts: list[dict[str, Any]] | None, unit_id: str) -> str | None:
    uid = str(unit_id or "")
    for row in reversed(list(receipts or [])):
        if str(row.get("unit_id") or row.get("sentinel_unit") or "") != uid:
            continue
        digest = row.get("sha256")
        if digest:
            return str(digest)
    return None


# Live inspector rows the hive may report. Missing ones go in one dashed box.
_INSPECTOR_LIVE_FIELDS = (
    ("state", "State", "state"),
    ("target", "Target", "target"),
    ("last_action", "Last action", "last_action"),
    ("time_on_task", "Time on task", "time_on_task"),
    ("eyes", "Eyes", "eyes"),
    ("tentacles", "Tentacles", "tentacles"),
    ("warrant_hash", "Warrant hash", "warrant_hash"),
    ("sparkline", "2 min activity", "sparkline"),
)


def _inspector_field_value(unit: dict[str, Any], key: str, warrant: str | None) -> object | None:
    if key == "state":
        return unit.get("state") or None
    if key == "target":
        return unit.get("target_node_id") or None
    if key == "tentacles":
        return unit["tentacles"] if "tentacles" in unit else None
    if key == "eyes":
        return unit["eyes"] if "eyes" in unit else None
    if key == "last_action":
        return unit.get("last_action") or None
    if key == "time_on_task":
        return unit.get("time_on_task") or None
    if key == "warrant_hash":
        return warrant
    if key == "sparkline":
        return unit.get("sparkline") or unit.get("activity_2m") or None
    return None


def _inspector_recent(
    unit_id: str,
    entries: list[dict[str, Any]] | None,
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    uid = str(unit_id or "")
    if not uid:
        return []
    rows = [e for e in entries or [] if isinstance(e, dict) and str(e.get("unit_id") or "") == uid]
    out: list[dict[str, Any]] = []
    for entry in reversed(rows):
        iso = str(entry.get("iso_time") or "")
        time = iso[11:19] if len(iso) >= 19 and iso[10:11] in "T " else (iso[:8] if iso else "")
        out.append({
            "seq": entry.get("seq"),
            "time": time,
            "message": plain_log_message(entry),
            "raw": _raw_log_line(entry),
        })
        if len(out) >= limit:
            break
    return out


def inspector_card(
    unit: dict[str, Any] | None,
    *,
    castes: list[dict[str, Any]] | None = None,
    receipts: list[dict[str, Any]] | None = None,
    telemetry_log: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Dock card for the selected unit. Empty when nothing is selected.

    LIVE lists only fields the hive reported. Missing names go in one dashed
    box so the dock never repeats "unavailable". Capabilities are chips.
    Recent is the newest three log rows for this unit id.
    """
    if not unit:
        return {
            "unit_id": "",
            "caste": "",
            "role": "",
            "task": "",
            "state": "",
            "state_label": "",
            "live": [],
            "missing": [],
            "capabilities": [],
            "recent": [],
            "target": "",
            "last_action": "",
            "time_on_task": "",
            "eyes": "",
            "tentacles": "",
            "warrant_hash": "",
            "sparkline": "",
        }
    caste = str(unit.get("caste") or "")
    role = CASTE_ROLE.get(caste.lower(), "")
    state = str(unit.get("state") or "")
    warrant = _unit_warrant(receipts, str(unit.get("unit_id") or ""))
    live: list[dict[str, str]] = []
    missing: list[str] = []
    values: dict[str, object] = {}
    for key, label, _ in _INSPECTOR_LIVE_FIELDS:
        value = _inspector_field_value(unit, key, warrant)
        values[key] = value if value is not None else ""
        if value is None or value == "":
            missing.append(label)
        else:
            live.append({"key": key, "label": label, "value": str(value)})
    caps = _caste_capabilities(castes, caste)
    state_label = state.replace("_", " ").title() if state else ""
    return {
        "unit_id": unit.get("unit_id") or "",
        "caste": caste,
        "role": role,
        "task": unit.get("current_task") or empty_task_label(unit.get("state")),
        "state": state,
        "state_label": state_label,
        "live": live,
        "missing": missing,
        "capabilities": caps,
        "recent": _inspector_recent(str(unit.get("unit_id") or ""), telemetry_log),
        "target": values.get("target", ""),
        "last_action": values.get("last_action", ""),
        "time_on_task": values.get("time_on_task", ""),
        "eyes": values.get("eyes", ""),
        "tentacles": values.get("tentacles", ""),
        "warrant_hash": values.get("warrant_hash", ""),
        "sparkline": values.get("sparkline", ""),
    }


def _log_matches(entry: dict[str, Any], wanted: str, q: str) -> bool:
    level = str(entry.get("level") or "").upper()
    caste = str(entry.get("caste") or "").lower()
    src = str(entry.get("unit_id") or "").upper()
    if wanted == "threat":
        threat_levels = {"THREAT", "BLOCK", "CRITICAL", "WARDEN", "ALERT", "EMP"}
        if not (level in threat_levels or "warden" in caste):
            return False
    elif wanted == "sanitize":
        if not (level == "SANITIZE" or "sanitize" in caste or "SAN" in src):
            return False
    elif wanted == "harvest":
        if not (level in {"HARVEST", "WARRANT"} or "harvest" in caste or "HRV" in src):
            return False
    elif wanted == "tripwire":
        if not (level == "TRIPWIRE" or "tripwire" in caste or "TRP" in src):
            return False
    if q:
        hay = " ".join([
            str(entry.get("unit_id") or ""),
            str(entry.get("caste") or ""),
            str(entry.get("phase") or ""),
            str(entry.get("message") or ""),
            json.dumps(entry.get("details") or {}),
        ]).lower()
        if q not in hay:
            return False
    return True


def filter_logs(
    entries: list[dict[str, Any]] | None,
    filt: str = "all",
    query: str = "",
) -> list[dict[str, Any]]:
    wanted = str(filt or "all")
    q = str(query or "").strip().lower()
    out = [entry for entry in entries or [] if _log_matches(entry, wanted, q)]
    return list(reversed(out))


# "3-Sentinel HUNTER-SEEKER Pack (SNT-TRP-001 + SNT-TRP-002, SNT-TRP-003)"
_PACK_TAG = re.compile(r"(\d+)-Sentinel HUNTER-SEEKER Pack \([^)]*\)")
_PACK_RUN = re.compile(
    r"^(\d+)-Sentinel HUNTER-SEEKER Pack \([^)]*\) "
    r"(?:deployed for (\w+):(\w+)|finished (\w+):(\w+) \(ok=(True|False), title=(.*)\))$"
)
_OK_TAIL = re.compile(r" \(ok=(True|False), title=(.*)\)$")


def _pack_name(caste: str, n: str) -> str:
    return f"{str(caste or 'sentinel').title()} pack of {n}"


def plain_log_message(entry: dict[str, Any]) -> str:
    """Console wording: no "title=" or "ok=True" debug text, packs named by caste."""
    message = str(entry.get("message") or "")
    caste = str(entry.get("caste") or "")
    run = _PACK_RUN.match(message)
    if run:
        n = run[1]
        if run[2]:
            return f"{_pack_name(run[2], n)} started {run[3].replace('_', ' ')}"
        tail = "ok" if run[6] == "True" else "failed" + (f": {run[7]}" if run[7] else "")
        return f"{_pack_name(run[4], n)} ran {run[5].replace('_', ' ')}, {tail}"
    message = _PACK_TAG.sub(lambda m: _pack_name(caste, m[1]), message)
    tail = _OK_TAIL.search(message)
    if tail:
        end = "ok" if tail[1] == "True" else "failed" + (f": {tail[2]}" if tail[2] else "")
        message = message[: tail.start()] + ", " + end
    return message


def _raw_log_line(entry: dict[str, Any]) -> str:
    return (
        f"[{entry.get('iso_time') or ''}] [{entry.get('level') or ''}] "
        f"[{entry.get('unit_id') or ''}] ({entry.get('phase') or ''}) {entry.get('message') or ''}"
    )


REPLAY_WINDOW_S = 600.0
REPLAY_TICK_CAP = 1500
_THREAT_LEVELS = frozenset({"THREAT", "BLOCK", "CRITICAL", "ALERT", "EMP"})


def replay_kind(entry: dict[str, Any]) -> str:
    """Replay tick colour: fetch, result (in), tripwire (check), threat, or other."""
    level = str(entry.get("level") or "").upper()
    caste = str(entry.get("caste") or "").lower()
    message = str(entry.get("message") or "")
    if level in _THREAT_LEVELS:
        return "threat"
    if level == "TRIPWIRE" or caste == "tripwire":
        return "tripwire"
    if level in {"HARVEST", "WARRANT"} or caste == "harvester":
        if "deployed for" in message or "Deploying" in message:
            return "fetch"
        return "result"
    return "other"


class LogSession:
    """The console's session log, kept by the host across snapshots.

    The snapshot carries only the newest 60 telemetry rows, so repeats are
    counted here, once per new seq (no rescans). Rule A: identical rows (same
    caste, unit, level, phase and text; time ignored) merge into one row with
    a count and a first-to-last range. Rule B: a pack's "deployed for X" and
    its "finished X (ok=True)" merge into "<Caste> pack of N ran X, all ok";
    a deploy not finished yet is its own "running" row, and ok=False splits
    out as its own (failed) row.
    """

    RAW_LIMIT = 200
    GROUP_LIMIT = 200

    def __init__(self) -> None:
        self._last_seq: int | None = None
        self._raw: deque[dict[str, Any]] = deque(maxlen=self.RAW_LIMIT)
        self._groups: dict[tuple, dict[str, Any]] = {}
        # Replay strip: (seq, time, kind) of every row, kept past RAW_LIMIT
        # so the strip covers its whole 10 minutes on a busy hive.
        self._ticks: deque[tuple[int, float, str]] = deque(maxlen=REPLAY_TICK_CAP)

    def reset(self) -> None:
        self._last_seq = None
        self._raw.clear()
        self._groups.clear()
        self._ticks.clear()

    def replay_ticks(self, now: float) -> list[dict[str, Any]]:
        """One tick per event of the last REPLAY_WINDOW_S seconds, oldest first."""
        start = float(now) - REPLAY_WINDOW_S
        return [{"seq": q, "t": t, "kind": k} for q, t, k in self._ticks if start <= t <= now + 5.0]

    def ingest(self, entries: list[dict[str, Any]] | None) -> None:
        rows = [e for e in entries or [] if isinstance(e, dict)]
        if any(not isinstance(e.get("seq"), int) for e in rows):
            # No usable seq: treat the list as the whole session.
            self.reset()
            rows = [dict(e, seq=i + 1) for i, e in enumerate(rows)]
        elif rows and self._last_seq is not None and max(e["seq"] for e in rows) < self._last_seq:
            self.reset()  # the hive restarted and its seq began again
        for entry in sorted(rows, key=lambda e: e["seq"]):
            if self._last_seq is not None and entry["seq"] <= self._last_seq:
                continue
            self._last_seq = entry["seq"]
            self._raw.append(entry)
            self._add(entry)
            ts = entry.get("timestamp")
            if isinstance(ts, (int, float)) and not isinstance(ts, bool):
                self._ticks.append((entry["seq"], float(ts), replay_kind(entry)))
        if len(self._groups) > self.GROUP_LIMIT:
            keep = sorted(self._groups.items(), key=lambda kv: kv[1]["seq"])[-self.GROUP_LIMIT:]
            self._groups = dict(keep)

    def _add(self, entry: dict[str, Any]) -> None:
        message = str(entry.get("message") or "")
        caste = str(entry.get("caste") or "")
        unit = str(entry.get("unit_id") or "")
        run = _PACK_RUN.match(message)
        if run and (run[2] or run[6] == "True"):
            task = (run[2] or run[4], run[3] or run[5])
            group = self._groups.setdefault(
                ("pack", caste, unit, task),
                {"count": 0, "first": None, "entry": entry, "pending": None, "seq": entry["seq"]},
            )
            group["seq"] = entry["seq"]
            if group["first"] is None:
                group["first"] = entry
            if run[2]:
                group["pending"] = entry
                return
            group["count"] += 1
            group["pending"] = None
            group["entry"] = entry
            return
        if run:  # ok=False: the deploy is over; the failure is its own row
            pack = self._groups.get(("pack", caste, unit, (run[4], run[5])))
            if pack is not None:
                pack["pending"] = None
        key = ("same", caste, unit, entry.get("level"), entry.get("phase"), message)
        group = self._groups.setdefault(
            key, {"count": 0, "first": entry, "entry": entry, "pending": None, "seq": entry["seq"]}
        )
        group["count"] += 1
        group["entry"] = entry
        group["seq"] = entry["seq"]
        group["failed"] = bool(run)

    @staticmethod
    def _row(
        entry: dict[str, Any],
        *,
        count: int = 1,
        first: dict | None = None,
        message: str | None = None,
        failed: bool = False,
        running: bool = False,
    ) -> dict[str, Any]:
        last_t = str(entry.get("iso_time") or "")[:8]
        first_t = str((first or entry).get("iso_time") or "")[:8]
        return {
            "seq": entry.get("seq"),
            "time": last_t,
            "count": count,
            "range": f"{first_t} to {last_t}" if count > 1 and first_t != last_t else "",
            "unit_id": entry.get("unit_id") or "",
            "caste": entry.get("caste") or "",
            "level": entry.get("level") or "",
            "message": message if message is not None else plain_log_message(entry),
            "raw": _raw_log_line(entry),
            "failed": failed,
            "running": running,
        }

    def rows(
        self, filt: str = "all", query: str = "", repeats: bool = True
    ) -> list[dict[str, Any]]:
        """Console rows, newest first. repeats=False shows every line again."""
        wanted = str(filt or "all")
        q = str(query or "").strip().lower()
        if not repeats:
            return [self._row(e) for e in reversed(self._raw) if _log_matches(e, wanted, q)]
        out: list[dict[str, Any]] = []
        for key, group in self._groups.items():
            entry = group["entry"]
            if key[0] == "pack":
                pending = group["pending"]
                if pending is not None and _log_matches(pending, wanted, q):
                    running = plain_log_message(pending).replace(" started ", " running ", 1)
                    out.append(self._row(pending, message=running, running=True))
                if group["count"] and _log_matches(entry, wanted, q):
                    message = plain_log_message(entry)
                    if group["count"] > 1:
                        message = message[: -len(", ok")] + ", all ok"
                    count, first = group["count"], group["first"]
                    out.append(self._row(entry, count=count, first=first, message=message))
            elif _log_matches(entry, wanted, q):
                count, first = group["count"], group["first"]
                failed = bool(group.get("failed"))
                out.append(self._row(entry, count=count, first=first, failed=failed))
        out.sort(key=lambda r: r["seq"], reverse=True)
        return out


def _session_rows(
    snap: dict[str, Any] | None,
    session: LogSession | None,
    filt: str,
    query: str,
    repeats: bool,
) -> list[dict[str, Any]]:
    session = session if session is not None else LogSession()
    session.ingest((snap or {}).get("telemetry_log") if isinstance(snap, dict) else None)
    return session.rows(filt, query, repeats)


def build_hud(
    snap: dict[str, Any] | None,
    *,
    group_by: str = "caste",
    search: str = "",
    collapsed: set[str] | list[str] | None = None,
    selected_id: str = "",
    log_filter: str = "all",
    log_query: str = "",
    camera_distance: float = 76.0,
    log_session: LogSession | None = None,
    log_repeats: bool = True,
    dispatches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    units = snapshot_units(snap)
    selected = next((u for u in units if u.get("unit_id") == selected_id), None)
    metrics = (snap or {}).get("metrics") if isinstance(snap, dict) else None
    status_line = "hive live · all local · sending out blocked"
    if isinstance(snap, dict):
        emp = snap.get("emp")
        banner = snap.get("active_banner")
        if isinstance(emp, dict) and emp.get("tripped"):
            reason = str(emp.get("reason") or "swarm halted")
            status_line = f"EMP EMERGENCY STOP ACTIVE — {reason}"
        elif isinstance(banner, dict) and banner.get("title"):
            b_title = str(banner.get("title") or "").strip()
            b_sub = str(banner.get("subtitle") or "").strip()
            status_line = f"{b_title}: {b_sub}" if b_sub else b_title
    session = log_session if log_session is not None else LogSession()
    inspector = inspector_card(
        selected,
        castes=(snap or {}).get("castes") if isinstance(snap, dict) else None,
        receipts=(snap or {}).get("recent_receipts") if isinstance(snap, dict) else None,
        telemetry_log=(snap or {}).get("telemetry_log") if isinstance(snap, dict) else None,
    )
    inspector["origin"] = task_origin(selected, dispatches)
    logs = _session_rows(snap, session, log_filter, log_query, log_repeats)
    return {
        "pills": pill_counts(
            units,
            metrics if isinstance(metrics, dict) else None,
            (snap or {}).get("telemetry_log") if isinstance(snap, dict) else None,
        ),
        "swarmRows": swarm_rows(units, by=group_by, query=search, collapsed=collapsed),
        "inspector": inspector,
        "inspectorCollapsed": inspector_collapsed(camera_distance, selected_id or None),
        "logs": logs,
        "ticks": session.replay_ticks(time.time()),  # the strip's clock is local time too
        "title": "Sentinels",
        "statusLine": status_line,
    }


def task_origin(unit: dict[str, Any] | None, dispatches: list[dict[str, Any]] | None) -> str:
    """'task from Dispatch at 11:58 PM' when this unit is working on a Dispatch
    sent from the open Overseer. The hive names the target in the task
    ("Extracting arxiv: sparse"), so the newest Dispatch whose query the task
    names is its origin. Anything else has no known origin and says nothing.
    """
    if not unit or not dispatches or _patrolling(unit.get("state")):
        return ""
    task = str(unit.get("current_task") or "").lower()
    for sent in reversed(dispatches):
        query = str(sent.get("query") or "").strip().lower()[:40]
        at = sent.get("at")
        if query and query in task and isinstance(at, (int, float)):
            stamp = datetime.fromtimestamp(float(at)).strftime("%I:%M %p").lstrip("0")
            return f"task from Dispatch at {stamp}"
    return ""


ZOOM_MIN = 6.0
ZOOM_MAX = 110.0
ZOOM_NOTCH = 1.18
RUBBER = 0.08
PITCH_CLOSE_DEG = 22.0
PITCH_WIDE_DEG = 55.0
# Iris's wide frame (BAND-SPEC.md "Camera framing") at k = 1: camera at
# spec (0, -78, 44) looking at (0, 3, -6), i.e. 95.19 m from the look target
# at 31.68 deg pitch. OverseerView.qml fits the distance up from here so the
# perimeter and every source label sit in the area the HUD leaves free.
DEFAULT_CAMERA_DISTANCE = 95.1893
OVERVIEW_PITCH_DEG = 31.6864
CASTE_MIX = (
    ("warden", 0.34),
    ("harvester", 0.36),
    ("sanitizer", 0.12),
    ("tripwire", 0.12),
    ("stalker", 0.06),
)
SWARM_RINGS = (5.0, 10.0, 16.0, 23.0)


def zoom_t(distance: float) -> float:
    d = max(ZOOM_MIN, min(ZOOM_MAX, float(distance)))
    return math.log(d / ZOOM_MIN) / math.log(ZOOM_MAX / ZOOM_MIN)


PITCH_MID_DEG = 36.0
CLOSE_DISTANCE = 24.0  # frame the complete unit between responsive HUD panels
# coreFocus is a separate preset (orb centre, 22 deg pitch). It does not
# change the default 24 m unit focus or the overview scale.
CORE_FOCUS_PITCH = 22.0
CORE_FOCUS_MIN_DISTANCE = 10.0
CORE_FOCUS_MAX_DISTANCE = 24.0
CORE_FOCUS_BASE_DISTANCE = 15.0
ORB_CENTRE = (0.0, 1.6, 0.0)


def core_focus_distance(view_h: float, free_w: float) -> float:
    """Metres for the coreFocus preset: max(15, 20 * viewH / freeW)."""
    height = max(1.0, float(view_h or 1.0))
    width = max(1.0, float(free_w or 1.0))
    return max(CORE_FOCUS_BASE_DISTANCE, 20.0 * height / width)
MID_DISTANCE = 32.0
WIDE_DISTANCE = 96.0
CLOSE_BAND = (ZOOM_MIN, 9.0)
HIVE_TARGET = (0.0, 0.0, 0.0)
_PITCH_MARKS = (
    (ZOOM_MIN, PITCH_CLOSE_DEG),
    (9.0, PITCH_CLOSE_DEG),
    (MID_DISTANCE, 36.0),
    (WIDE_DISTANCE, PITCH_WIDE_DEG),
    (ZOOM_MAX, PITCH_WIDE_DEG),
)


def pitch_deg(distance: float) -> float:
    d = max(ZOOM_MIN, min(ZOOM_MAX, float(distance)))
    marks = _PITCH_MARKS
    if d <= marks[0][0]:
        return float(marks[0][1])
    for i in range(1, len(marks)):
        d0, p0 = marks[i - 1]
        d1, p1 = marks[i]
        if d <= d1:
            if d0 <= 0 or d1 <= 0 or d0 == d1:
                return float(p1)
            u = math.log(d / d0) / math.log(d1 / d0)
            return float(p0) + u * (float(p1) - float(p0))
    return float(marks[-1][1])



ZOOM_EASE_NOTCHES = 3.0


def zoom_pose(z: float, overview_distance: float) -> tuple[float, float]:
    """Distance and pitch z wheel notches in from the default frame (mirrors
    OverseerView.qml zoomPose): an even pitch ease onto the curve's 55 deg
    wide mark over ZOOM_EASE_NOTCHES, then the approved curve."""
    d0 = float(overview_distance)
    j = min(WIDE_DISTANCE, d0)
    n = ZOOM_EASE_NOTCHES
    if z <= 0:
        return d0, OVERVIEW_PITCH_DEG
    if z < n:
        u = z / n
        return d0 * (j / d0) ** u, OVERVIEW_PITCH_DEG + (pitch_deg(j) - OVERVIEW_PITCH_DEG) * u
    d = j / ZOOM_NOTCH ** (z - n)
    return d, pitch_deg(d)


def framing_name(distance: float) -> str:
    """Name the live distance against the approved bands; do not invent a shot."""
    d = float(distance)
    if CLOSE_BAND[0] <= d <= CLOSE_BAND[1]:
        return "close"
    if 18.0 <= d <= 40.0:
        return "mid"
    if d > 40.0:
        return "wide"
    return "unclassified"


def rubber_band(distance: float) -> float:
    lo = ZOOM_MIN * (1.0 - RUBBER)
    hi = ZOOM_MAX * (1.0 + RUBBER)
    return max(lo, min(hi, float(distance)))


def settle_distance(distance: float) -> float:
    return max(ZOOM_MIN, min(ZOOM_MAX, float(distance)))


def wheel_step(distance: float, notches: float) -> float:
    next_d = float(distance) * (ZOOM_NOTCH ** float(notches))
    return rubber_band(next_d)


def cursor_dolly(
    target: tuple[float, float, float],
    pivot: tuple[float, float, float],
    d_old: float,
    d_new: float,
) -> tuple[float, float, float]:
    if not d_old:
        return target
    s = d_new / d_old
    return (
        pivot[0] + (target[0] - pivot[0]) * s,
        pivot[1] + (target[1] - pivot[1]) * s,
        pivot[2] + (target[2] - pivot[2]) * s,
    )


def camera_eye(
    distance: float,
    pitch: float | None = None,
    target: tuple[float, float, float] | None = None,
) -> tuple[float, float, float]:
    p = math.radians(pitch_deg(distance) if pitch is None else pitch)
    d = float(distance)
    tx, ty, tz = HIVE_TARGET if target is None else target
    return (float(tx), float(ty) + math.sin(p) * d, float(tz) + math.cos(p) * d)


def unit_has_geometry(unit: dict[str, Any] | None) -> bool:
    """True when the snapshot actually sent coordinates (not a default origin)."""
    if not isinstance(unit, dict):
        return False
    pos = unit.get("position")
    if isinstance(pos, (list, tuple)) and len(pos) >= 2:
        return True
    return unit.get("x") is not None or unit.get("z") is not None


def unit_view_pos(unit: dict[str, Any]) -> tuple[float, float, float]:
    pos = unit.get("position") or [unit.get("x") or 0, unit.get("y") or 0, unit.get("z") or 0]
    x, y = float(pos[0]), float(pos[1])
    z = float(pos[2]) if len(pos) > 2 else 0.0
    # Hive kinematics are Y-up: (x, height, z) maps straight into Qt Quick 3D.
    return (x, y, z)


def focus_framing(unit: dict[str, Any] | None) -> dict[str, Any] | None:
    """Local camera focus: look at the unit's snapshot position at close range."""
    if not unit_has_geometry(unit):
        return None
    distance = CLOSE_DISTANCE
    return {
        "target": unit_view_pos(unit),
        "distance": distance,
        "pitch": pitch_deg(distance),
    }


def unit_camera_distance(unit: dict[str, Any], eye: tuple[float, float, float]) -> float:
    ux, uy, uz = unit_view_pos(unit)
    return max(0.1, math.dist((ux, uy, uz), eye))


def part_tris(lod: int, report: dict[int, dict[str, Any]]) -> int:
    row = report.get(int(lod)) or {}
    parts = row.get("parts") or {}
    head = int(parts.get("head") or 0)
    tent = int(parts.get("tentacle") or 0)
    strands = int(row.get("strands") or 0)
    if head or tent:
        return head + strands * tent
    return sum(int(parts.get(part) or 0) for part in PARTS)


def assigned_tris(units: list[dict[str, Any]], report: dict[int, dict[str, Any]]) -> int:
    total = 0
    for u in units:
        if u.get("culled"):
            continue
        total += part_tris(int(u.get("lod", 2)), report)
    return total


def enforce_budget(
    assigned: list[dict[str, Any]],
    report: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Demote smallest on-screen units, then cull, until unit tris fit MAX_TRIS."""
    rows = [dict(u) for u in assigned]
    for row in rows:
        row["culled"] = bool(row.get("culled"))
        row["lod"] = int(row.get("lod", 1))

    def key(row: dict[str, Any]) -> tuple[float, str]:
        return (float(row.get("height_px") or 0.0), str(row.get("unit_id") or ""))

    def protected(row: dict[str, Any]) -> bool:
        # Fetchers, engaged and focused units stay at least at LOD1.
        return bool(row.get("lod_forced")) or unit_fetching(row) or unit_engaged(row)

    while assigned_tris(rows, report) > MAX_TRIS:
        demote = [
            u for u in rows
            if not u["culled"] and int(u["lod"]) < 2
            and not (protected(u) and int(u["lod"]) == 1)
        ]
        if not demote:
            break
        demote.sort(key=key)
        demote[0]["lod"] = int(demote[0]["lod"]) + 1
    while assigned_tris(rows, report) > MAX_TRIS:
        visible = [u for u in rows if not u["culled"]]
        if not visible:
            break
        visible.sort(key=key)
        visible[0]["culled"] = True
    return rows


def layout_swarm(n: int = 100) -> list[dict[str, Any]]:
    """Approved caste mix on the 5/10/16/23 m rings."""
    labels: list[str] = []
    for caste, frac in CASTE_MIX:
        labels.extend([caste] * round(n * frac))
    while len(labels) < n:
        labels.append("warden")
    labels = labels[:n]
    units = []
    for i, caste in enumerate(labels):
        ring = SWARM_RINGS[i % len(SWARM_RINGS)]
        ang = (2.0 * math.pi * i) / max(1, n) + (i % 4) * 0.15
        units.append({
            "unit_id": f"{caste[:3].upper()}-{i:03d}",
            "caste": caste,
            "position": [ring * math.cos(ang), 0.4, ring * math.sin(ang)],
            "scale": 1.0,
        })
    return units


def clustered_swarm(n: int = 100) -> list[dict[str, Any]]:
    """All units packed near the origin (all-close stress case)."""
    units = []
    for i in range(n):
        units.append({
            "unit_id": f"CL-{i:03d}",
            "caste": CASTES[i % len(CASTES)],
            "position": [0.12 * (i % 10), 0.4, 0.12 * (i // 10)],
            "scale": 1.0,
        })
    return units


def validate_shader_text(name: str, text: str) -> list[str]:
    """Static snippet checks (not a GPU compile)."""
    errors: list[str] = []
    if "void MAIN()" not in text:
        errors.append(f"{name}: missing void MAIN()")
    if text.count("{") != text.count("}"):
        errors.append(f"{name}: unbalanced braces")
    if name in {"hull.vert", "emissive.vert"}:
        if "INSTANCE_DATA" not in text:
            errors.append(f"{name}: missing INSTANCE_DATA")
        if "uTime" not in text:
            errors.append(f"{name}: missing uTime")
    if name == "hull.frag":
        for token in ("uHull", "uRole", "CLEARCOAT_AMOUNT", "EMISSIVE_COLOR"):
            if token not in text:
                errors.append(f"{name}: missing {token}")
    if name == "tentacle.vert":
        for token in (
            "texelFetch", "INSTANCE_DATA", "VIEWPROJECTION_MATRIX", "rotation-minimising",
        ):
            if token not in text:
                errors.append(f"{name}: missing {token}")
    if name == "rim_hull.frag":
        for token in ("EMISSIVE_COLOR", "wearGain", "lipGain", "VAR_WORLD_NORMAL"):
            if token not in text:
                errors.append(f"{name}: missing {token}")
    return errors


def validate_overseer_shaders(asset_root: Path | None = None) -> list[str]:
    root = asset_root or (asset_dir() / "shaders")
    errors: list[str] = []
    for name in (
        "hull.vert", "hull.frag", "emissive.vert", "emissive.frag", "lens.vert", "lens.frag",
        "rim_hull.vert", "rim_hull.frag", "eye_lens.vert", "eye_lens.frag",
        "emission.vert", "emission_instanced.vert", "emission.frag",
        "orb_shell.vert", "orb_shell.frag",
        "source_node.frag", "tentacle.vert",
    ):
        path = root / name
        if not path.is_file():
            errors.append(f"{name}: missing file")
            continue
        errors.extend(validate_shader_text(name, path.read_text()))
    return errors


def assign_lods(
    units: list[dict[str, Any]],
    camera_distance: float,
    viewport_h: float = 1306.0,
    prev: dict[str, int] | None = None,
    pitch: float | None = None,
    target: tuple[float, float, float] | None = None,
) -> list[dict[str, Any]]:
    prev = prev or {}
    eye = camera_eye(camera_distance, pitch, target=target)
    assigned = []
    for u in units:
        uid = str(u.get("unit_id") or "")
        scale = float(u.get("scale") or 1.0)
        dist = unit_camera_distance(u, eye)
        height = projected_height_px(dist, viewport_h, scale)
        lod = choose_lod(height, prev.get(uid))
        row = dict(u)
        row["lod"] = lod
        row["height_px"] = height
        row["view_distance"] = dist
        row["culled"] = False
        assigned.append(row)
    return assigned


def bucket_key(caste: str, lod: int) -> str:
    return f"{caste}:{int(lod)}"


def build_buckets(units: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {
        f"{c}:{lod}": [] for c in CASTES for lod in (0, 1, 2)
    }
    for i, u in enumerate(units):
        if u.get("culled"):
            continue
        caste = str(u.get("caste") or "warden").lower()
        if caste not in CASTE_COLOR:
            caste = "warden"
        lod = int(u.get("lod", 1))
        lod = 0 if lod < 0 else 2 if lod > 2 else lod
        pos = u.get("position") or [u.get("x") or 0, u.get("y") or 0, u.get("z") or 0]
        x, y, z = float(pos[0]), float(pos[1]), float(pos[2] if len(pos) > 2 else 0)
        vel = u.get("velocity")
        if isinstance(vel, (list, tuple)) and len(vel) >= 3:
            vx, vy, vz = float(vel[0]), float(vel[1]), float(vel[2])
        else:
            vx = float(u.get("vx") or 0.0)
            vy = float(u.get("vy") or 0.0)
            vz = float(u.get("vz") or 0.0)
        state = str(u.get("state") or "")
        limp = 1.0 if "EMP" in state.upper() or "HALT" in state.upper() else 0.0
        raw_scale = u.get("scale")
        scale = float(raw_scale) if raw_scale is not None else 0.36
        dim = 0.2 if u.get("threat_dim") else 1.0
        tgt = u.get("harvest_target")
        target = None
        if isinstance(tgt, (list, tuple)) and len(tgt) >= 3:
            target = [float(tgt[0]), float(tgt[1]), float(tgt[2])]
        buckets[bucket_key(caste, lod)].append(
            {
                "unit_id": u.get("unit_id"),
                "caste": caste,
                "lod": lod,
                "index": int(u.get("unit_index") or i),
                "x": x,
                "y": y,
                "z": z,
                "vx": vx,
                "vy": vy,
                "vz": vz,
                "heading_deg": heading_deg(u.get("heading")),
                "scale": scale,
                "color": CASTE_COLOR[caste],
                "lens": LENS_COLOR[caste],
                "eye": eye_color(u, caste),
                "phase": float(u.get("phase") or (i * 1.7)),
                "claw": claw_open(state),
                "limp": limp,
                "speed": tentacle_speed(state),
                "reach": max(0, min(MAX_REACH_PAIRS, int(u.get("open_fetches") or 0))),
                "dim": dim,
                "eyeGain": 1.0,
                "threatMix": 1.0 if unit_engaged_defense(u) else 0.0,
                "target": target,
                "state": state,
                "lenMul": float(u.get("lenMul") or 1.0),
                "kappa": float(u.get("kappa") or 0.0),
                "eyeMul": 0.1 if limp else (0.0 if "DOCKED" in state.upper() else 1.0),
                "open_fetches": int(u.get("open_fetches") or 0),
            }
        )
        if u.get("orbit"):
            buckets[bucket_key(caste, lod)][-1]["orbit"] = list(u["orbit"])
    return buckets


# What the view derives itself between frames: a lane unit's place and heading
# (from its orbit) and a glyph trail's age (from its first sight).
_ORBIT_MOTION = frozenset({"x", "y", "z", "vx", "vy", "vz", "heading_deg"})


def scene_key(frame: dict[str, Any]) -> dict[str, Any]:
    """The part of a frame the view cannot work out on its own.

    Two polls with equal keys draw the same scene, so the second needs no
    applyFrame: idle lane units keep moving from their orbit in the view.
    """
    buckets = {}
    for key, rows in (frame.get("buckets") or {}).items():
        out = []
        for row in rows:
            orbit = row.get("orbit")
            if orbit:
                row = {k: v for k, v in row.items() if k not in _ORBIT_MOTION}
                row["orbit"] = orbit[:6]
            out.append(row)
        buckets[key] = out
    trails = [
        {k: v for k, v in t.items() if k != "age_s"} for t in frame.get("glyphTrails") or []
    ]
    rest = {
        k: v
        for k, v in frame.items()
        if k not in ("units", "prevLods", "buckets", "glyphTrails")
    }
    return {**rest, "buckets": buckets, "glyphTrails": trails}


def budget_from_buckets(
    buckets: dict[str, list[dict[str, Any]]],
    report: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    lod_counts = {0: 0, 1: 0, 2: 0}
    tris = 0
    unit_draw = 0
    active = []
    lod_used = {0: False, 1: False, 2: False}
    for caste in CASTES:
        for lod in (0, 1, 2):
            rows = buckets.get(bucket_key(caste, lod)) or []
            n = len(rows)
            lod_counts[lod] += n
            if n == 0:
                continue
            per = part_tris(lod, report)
            tris += per * n
            lod_used[lod] = True
            active.append({
                "caste": caste, "lod": lod, "part": "head",
                "count": n, "tris": per * n,
            })
    unit_draw = sum(1 for used in lod_used.values() if used)
    return {
        "unitTris": tris,
        "unitDrawCalls": unit_draw,
        "drawCalls": unit_draw + SCENE_FIXED_DRAW,
        "lodCounts": lod_counts,
        "activeModels": active,
        "withinTriBudget": tris <= MAX_TRIS,
        "withinDrawBudget": unit_draw <= MAX_UNIT_DRAW,
    }


MAX_CONDUIT_INSTANCES = 192
CONDUIT_ACTIVE_STATES = {
    "ENGAGED_HARVEST",
    "ENGAGED_SANITIZE",
    "ENGAGED_DEFENSE",
    "ENGAGED_EXECUTION",
    "VECTORING",
    "RETURNING",
    "QUARANTINING",
    "HARVESTING",
    "CARRYING_WARRANT",
}
NODE_KIND_COLOR = {
    "bastion": "#a78bfa",
    "harvest_target": "#38bdf8",
    "threat": "#f43f5e",
    "quarantine": "#f2c56b",
    "memory_crystal": "#22d3ee",
    "merkle_root": "#7ee0c8",
}

# Fixed edge sources for the Overseer. Beams light only on a real harvest fetch.
HARVEST_SOURCE_EDGE_R = PERIMETER_MIN + SOURCE_PAST_PERIMETER
HARVEST_SOURCES: tuple[tuple[str, str, float, str], ...] = (
    # id, label, angle_radians (spec space, BAND-SPEC.md), color.
    # Horizons takes the spec's PubMed slot (62 deg); the hive has no PubMed source.
    ("arxiv", "arXiv", math.radians(8.0), "#8fd3ff"),
    ("wikipedia", "Wikipedia", math.radians(128.0), "#a78bfa"),
    ("horizons", "Horizons", math.radians(62.0), "#7ee0c8"),
    ("web", "Web", math.radians(160.0), "#e879f9"),
)
HARVEST_SOURCE_IDS = {row[0] for row in HARVEST_SOURCES}


def normalize_harvest_source(action: object, target: object = None) -> str:
    """Map a harvester action or URL onto a fixed edge source id, or empty."""
    a = str(action or "").strip().lower()
    t = str(target or "").strip().lower()
    blob = f"{a} {t}"
    if a in HARVEST_SOURCE_IDS:
        return a
    if "arxiv" in blob:
        return "arxiv"
    if "wikipedia" in blob or "wiki" in blob:
        return "wikipedia"
    if "horizons" in blob or "ssd.jpl" in blob:
        return "horizons"
    if a in {"url", "web", "fetch", "fetch_url"} or t.startswith("http://") or t.startswith("https://"):
        return "web"
    return ""


def active_harvest_sources(
    units: list[dict[str, Any]] | None = None,
    nodes: list[dict[str, Any]] | None = None,
) -> set[str]:
    """Sources with a live harvest fetch in this snapshot. No timers; snapshot only.

    A harvest_target node exists only while the harvester is vectoring or
    extracting, so its metadata.action/target is the primary signal. A unit
    lights a source only when its task or action normalizes to a known source
    id (arxiv, wikipedia, horizons, web). Bare HARVEST/CARRY state alone does
    not light Web.
    """
    active: set[str] = set()
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        if str(node.get("kind") or "").lower() != "harvest_target":
            continue
        meta = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
        sid = normalize_harvest_source(meta.get("action"), meta.get("target") or node.get("label"))
        if sid:
            active.add(sid)
    for unit in units or []:
        if not isinstance(unit, dict):
            continue
        task = str(unit.get("current_task") or unit.get("task") or "")
        action = unit.get("action")
        sid = normalize_harvest_source(action, task)
        if sid:
            active.add(sid)
    return active



def source_open_counts(
    units: list[dict[str, Any]] | None = None,
    nodes: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    """Open harvest requests per fixed edge source, from the snapshot only."""
    counts = {sid: 0 for sid, *_ in HARVEST_SOURCES}
    seen: set[str] = set()
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        if str(node.get("kind") or "").lower() != "harvest_target":
            continue
        meta = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
        sid = normalize_harvest_source(meta.get("action"), meta.get("target") or node.get("label"))
        if not sid:
            continue
        counts[sid] = counts.get(sid, 0) + 1
        uid = str(meta.get("unit_id") or "")
        if uid:
            seen.add(uid)
    for unit in units or []:
        if not isinstance(unit, dict):
            continue
        uid = str(unit.get("unit_id") or "")
        if uid and uid in seen:
            continue
        task = unit.get("current_task") or unit.get("task")
        sid = normalize_harvest_source(unit.get("action"), task)
        if sid:
            counts[sid] = counts.get(sid, 0) + 1
    return counts


def source_world_pos(sid: str, radius: float | None = None) -> tuple[float, float, float]:
    edge_r = float(radius) if radius else HARVEST_SOURCE_EDGE_R
    for name, _label, angle, _color in HARVEST_SOURCES:
        if name == sid:
            x = edge_r * math.cos(angle)
            z = -edge_r * math.sin(angle)
            return (x, 3.0, z)
    return (edge_r, 3.0, 0.0)


def build_source_nodes(
    counts: dict[str, int], radius: float | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Glass + emissive instances and their 2D labels for the five edge sources."""
    nodes: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    for sid, label, _angle, color in HARVEST_SOURCES:
        x, y, z = source_world_pos(sid, radius)
        nx, ny, nz = _clamp_conduit_coord(x, y, z)
        n_open = int(counts.get(sid) or 0)
        hot = n_open > 0
        row = {
            "id": sid,
            "label": label,
            "x": nx, "y": ny, "z": nz,
            "color": color,
            "open": n_open,
            "lit": 1.0 if hot else 0.15,
            "scale": 1.25 if hot else 1.0,
            "hot": hot,
            "status": f"{n_open} requests open" if hot else "idle",
        }
        nodes.append(row)
        labels.append({
            "id": sid, "label": label, "x": nx, "y": ny, "z": nz,
            "hot": hot, "color": color, "open": n_open, "status": row["status"],
        })
    return nodes, labels


def harvest_target_of(
    unit: dict[str, Any], radius: float | None = None
) -> list[float] | None:
    sid = normalize_harvest_source(unit.get("action"), unit.get("current_task") or unit.get("task"))
    if not sid:
        return None
    x, y, z = source_world_pos(sid, radius)
    return [x, y, z]


def build_harvest_source_conduits(
    active: set[str] | None = None, radius: float | None = None
) -> list[dict[str, Any]]:
    """Beam packets only when a harvest fetch is active. Labels are stashed for the view."""
    hot = set(active or ())
    out: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    edge_r = float(radius) if radius else HARVEST_SOURCE_EDGE_R
    for i, (sid, label, _angle, color) in enumerate(HARVEST_SOURCES):
        is_hot = sid in hot
        # Spec space (x, y) on the ground maps to scene (x, -z).
        x, y, z = source_world_pos(sid, edge_r)
        nx, ny, nz = _clamp_conduit_coord(x, y, z)
        labels.append({
            "id": sid,
            "label": label,
            "x": nx,
            "y": ny,
            "z": nz,
            "hot": is_hot,
            "color": color,
            "open": 1 if is_hot else 0,
            "status": "1 requests open" if is_hot else "idle",
        })
        # Beacons are Pass C source_glass / source_emissive meshes, not conduit spheres.
        if not is_hot:
            continue
        # Beam: packets from the edge source inward to the core while fetching.
        arc_y = max(ny, 0.5) + 2.6
        cx, cy, cz = _clamp_conduit_coord(nx * 0.5, arc_y, nz * 0.5)
        beam_n = 5
        for k in range(beam_n):
            out.append({
                "id": f"source-beam:{sid}:{k}",
                "kind": "packet",
                "sx": nx, "sy": ny, "sz": nz,
                "cx": cx, "cy": cy, "cz": cz,
                "ex": 0.0, "ey": 0.4, "ez": 0.0,
                "phase": ((k / beam_n) + i * 0.17) % 1.0,
                "speed": 1.55,
                "scale": 14.0,
                "color": color,
                "source_id": sid,
            })
    # Stash labels on the first beacon via a sibling return; caller uses build_frame.
    build_harvest_source_conduits.last_labels = labels  # type: ignore[attr-defined]
    return out




# Glyph trails: the real title and URL of a harvest result arc from its
# source node back to the core. Brief: at most 4 live trails x 2 lanes x
# 60 glyphs (a fifth ends the oldest early). The head reaches the core in
# 2.5 s; the trail lives 5 s so its last letter also flies into the core.
GLYPH_TRAIL_MAX = 4
GLYPH_LANE_MAX = 60
GLYPH_CAP = 1500
GLYPH_TRAIL_LIFE_S = 5.0


def _ascii_glyphs(text: object) -> str:
    """Printable ASCII only (the atlas); accents fold, anything else drops."""
    folded = unicodedata.normalize("NFKD", str(text or ""))
    out = "".join(ch for ch in folded if " " <= ch <= "~")
    return " ".join(out.split())


def orb_result_titles(snap: dict[str, Any] | None, limit: int = 8) -> list[str]:
    """Recent harvest titles for the results orbit, as 'Source  title'."""
    if not isinstance(snap, dict):
        return []
    receipts = snap.get("recent_receipts")
    if not isinstance(receipts, list):
        metrics = snap.get("metrics") if isinstance(snap.get("metrics"), dict) else {}
        receipts = metrics.get("recent_receipts") if isinstance(metrics, dict) else []
    if not isinstance(receipts, list):
        return []
    labels = {sid: label for sid, label, *_ in HARVEST_SOURCES}
    out: list[str] = []
    seen: set[str] = set()
    for row in reversed(receipts):
        if not isinstance(row, dict):
            continue
        if row.get("ok") is False:
            continue
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        title = _ascii_glyphs(meta.get("title") or row.get("title"))
        if not title:
            continue
        sid = normalize_harvest_source(meta.get("action"), row.get("source") or meta.get("source"))
        source = labels.get(sid, "")
        text = f"{source}  {title}" if source else title
        text = " ".join(text.split())
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _receipt_epoch(at: object) -> float | None:
    try:
        stamp = datetime.fromisoformat(str(at))
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp.timestamp()


def build_glyph_trails(
    receipts: list[dict[str, Any]] | None,
    snapshot_ts: float | None,
) -> list[dict[str, Any]]:
    """Trails for harvest results minted in the last GLYPH_TRAIL_LIFE_S seconds.

    Snapshot only: each ok harvester receipt that names a title and a known
    source gives one trail (title lane, URL lane). No title, no trail.
    """
    try:
        now = float(snapshot_ts) if snapshot_ts is not None else None
    except (TypeError, ValueError):
        now = None
    if not receipts or now is None:
        return []
    origins = {
        row["id"]: row for row in getattr(build_harvest_source_conduits, "last_labels", []) or []
    }
    found: list[tuple[float, dict[str, Any]]] = []
    for r in receipts:
        if not isinstance(r, dict) or not r.get("ok"):
            continue
        if str(r.get("caste") or "").lower() != "harvester":
            continue
        meta = r.get("metadata") if isinstance(r.get("metadata"), dict) else {}
        title = _ascii_glyphs(meta.get("title"))[:GLYPH_LANE_MAX]
        if not title:
            continue
        sid = normalize_harvest_source(meta.get("action"), r.get("source"))
        origin = origins.get(sid)
        if origin is None:
            continue
        minted = _receipt_epoch(r.get("at"))
        if minted is None:
            continue
        age = now - minted
        if age < -0.5 or age > GLYPH_TRAIL_LIFE_S:
            continue
        url = _ascii_glyphs(re.sub(r"^https?://", "", str(r.get("source") or "")))[:GLYPH_LANE_MAX]
        found.append((max(0.0, age), {
            "id": str(r.get("receipt_id") or f"{sid}:{minted}"),
            "source_id": sid,
            "age_s": round(max(0.0, age), 3),
            "lanes": [title, url] if url else [title],
            "color": origin["color"],
            "x": origin["x"],
            "y": origin["y"],
            "z": origin["z"],
        }))
    found.sort(key=lambda item: item[0])
    trails: list[dict[str, Any]] = []
    glyphs = 0
    for _age, trail in found[:GLYPH_TRAIL_MAX]:
        n = sum(len(lane) for lane in trail["lanes"])
        if glyphs + n > GLYPH_CAP:
            break
        glyphs += n
        trails.append(trail)
    return trails


def _clamp_conduit_coord(
    x: float, y: float, z: float, limit: float = 46.0
) -> tuple[float, float, float]:
    r = math.hypot(x, z)
    if r > limit and r > 0.0:
        scale = limit / r
        x *= scale
        z *= scale
    y = max(-limit, min(limit, y))
    return (round(x, 4), round(y, 4), round(z, 4))


def conduit_position_3d(
    spec: dict[str, Any], scene_time: float = 0.0
) -> tuple[float, float, float, float]:
    """Evaluate a 3D conduit particle or node beacon at scene_time -> (x, y, z, scale)."""
    kind = str(spec.get("kind") or "packet")
    phase = float(spec.get("phase") or 0.0)
    base_scale = float(spec.get("scale") or 0.75)
    t_sec = float(scene_time)
    if kind == "node":
        sc = base_scale * (0.88 + 0.22 * math.sin(t_sec * 3.2 + phase * 6.2831853))
        return (float(spec["sx"]), float(spec["sy"]), float(spec["sz"]), sc)
    speed = float(spec.get("speed") or 0.75)
    t = (phase + t_sec * speed) % 1.0
    if t < 0.0:
        t += 1.0
    u = 1.0 - t
    sx, sy, sz = float(spec["sx"]), float(spec["sy"]), float(spec["sz"])
    cx, cy, cz = float(spec["cx"]), float(spec["cy"]), float(spec["cz"])
    ex, ey, ez = float(spec["ex"]), float(spec["ey"]), float(spec["ez"])
    px = u * u * sx + 2.0 * u * t * cx + t * t * ex
    py = u * u * sy + 2.0 * u * t * cy + t * t * ey
    pz = u * u * sz + 2.0 * u * t * cz + t * t * ez
    pulse = 0.65 + 0.55 * math.sin(t * math.pi)
    return (px, py, pz, base_scale * pulse)


def build_conduits(
    units: list[dict[str, Any]] | None = None,
    nodes: list[dict[str, Any]] | None = None,
    fx_events: list[dict[str, Any]] | None = None,
    *,
    active_sources: set[str] | None = None,
    source_radius: float | None = None,
) -> list[dict[str, Any]]:
    """Build hardware-instanced 3D conduit packet and node beacon descriptors."""
    out: list[dict[str, Any]] = []
    # Fixed harvest source edge beacons first (beams only when a real fetch is active).
    if active_sources is None:
        source_active = active_harvest_sources(units, nodes)
    else:
        source_active = active_sources
    out.extend(build_harvest_source_conduits(source_active, radius=source_radius))
    node_map: dict[str, tuple[float, float, float, str]] = {}

    for i, node in enumerate(nodes or []):
        if not isinstance(node, dict):
            continue
        pos = node.get("position")
        if not isinstance(pos, (list, tuple)) or len(pos) < 2:
            continue
        nx, ny, nz = _clamp_conduit_coord(
            float(pos[0]),
            float(pos[1]),
            float(pos[2]) if len(pos) > 2 else 0.0,
        )
        kind = str(node.get("kind") or "bastion").lower()
        sev = str(node.get("severity") or "none").lower()
        status = str(node.get("status") or "active").lower()
        hot = (
            sev in {"medium", "high", "critical"}
            or kind in {"threat", "harvest_target"}
            or status in {"extracting", "sanitizing", "blocked", "quarantined"}
        )
        color = str(node.get("color") or (
            "#f43f5e" if sev in {"high", "critical"} else NODE_KIND_COLOR.get(kind, "#38bdf8")
        ))
        nid = str(node.get("node_id") or f"node-{i}")
        node_map[nid] = (nx, ny, nz, color)
        # An idle hive node (a listening bastion port, a memory crystal, a
        # merkle root) has no visual in the motion brief. Drawn at the hive's own
        # coordinates, its beacon and stream were the lilac dots scattered on
        # and between the rings. Only a node with something happening draws.
        if not hot:
            continue
        out.append({
            "id": f"beacon:{nid}",
            "kind": "node",
            "sx": nx, "sy": ny, "sz": nz,
            "cx": nx, "cy": ny, "cz": nz,
            "ex": nx, "ey": ny, "ez": nz,
            "phase": (i * 0.19) % 1.0,
            "speed": 0.0,
            "scale": 1.65,
            "color": color,
        })
        pkt_count = 5
        speed = 1.05
        arc_y = max(ny, 0.4) + 2.4
        cx, cy, cz = _clamp_conduit_coord(nx * 0.5, arc_y, nz * 0.5)
        for k in range(pkt_count):
            if len(out) >= MAX_CONDUIT_INSTANCES:
                return out[:MAX_CONDUIT_INSTANCES]
            out.append({
                "id": f"node-stream:{nid}:{k}",
                "kind": "packet",
                "sx": nx, "sy": ny, "sz": nz,
                "cx": cx, "cy": cy, "cz": cz,
                "ex": 0.0, "ey": 0.0, "ez": 0.0,
                "phase": ((k / pkt_count) + i * 0.11) % 1.0,
                "speed": speed,
                "scale": 0.86,
                "color": color,
            })

    for i, u in enumerate(units or []):
        if not isinstance(u, dict) or u.get("culled"):
            continue
        state = str(u.get("state") or "").upper()
        laser_active = bool(u.get("laser_active"))
        carrying_orb = bool(u.get("carrying_orb"))
        if not (laser_active or carrying_orb or state in CONDUIT_ACTIVE_STATES):
            continue
        pos = u.get("position") or [u.get("x") or 0, u.get("y") or 0, u.get("z") or 0]
        ux, uy, uz = _clamp_conduit_coord(
            float(pos[0]),
            float(pos[1]),
            float(pos[2]) if len(pos) > 2 else 0.0,
        )
        caste = str(u.get("caste") or "warden").lower()
        base_color = CASTE_COLOR.get(caste, "#a78bfa")
        uid = str(u.get("unit_id") or f"u-{i}")

        lt = u.get("laser_target") or u.get("target_position")
        tnid = str(u.get("target_node_id") or "")
        if not lt and tnid and tnid in node_map:
            tx, ty, tz, _ = node_map[tnid]
            lt = [tx, ty, tz]
        engaged_beam_states = {
            "ENGAGED_DEFENSE",
            "ENGAGED_HARVEST",
            "ENGAGED_SANITIZE",
            "ENGAGED_EXECUTION",
            "VECTORING",
        }
        if laser_active or (lt and state in engaged_beam_states):
            if isinstance(lt, (list, tuple)) and len(lt) >= 2:
                tx, ty, tz = _clamp_conduit_coord(
                    float(lt[0]),
                    float(lt[1]),
                    float(lt[2]) if len(lt) > 2 else 0.0,
                )
            else:
                tx, ty, tz = (0.0, 0.0, 0.0)
            lkind = str(u.get("laser_kind") or "").lower()
            beam_color = (
                # Rose only for a real engagement. Every Warden laser carries
                # laser_kind "defense", including the routine socket patrol
                # (VECTORING), which takes the Warden caste colour instead.
                "#f43f5e" if "DEFENSE" in state
                else "#38bdf8" if ("HARVEST" in state or lkind == "harvest")
                else "#f2c56b" if ("SANITIZE" in state or lkind == "sanitize")
                else base_color
            )
            mx, my, mz = _clamp_conduit_coord(
                (ux + tx) * 0.5,
                max(uy, ty) + 0.55,
                (uz + tz) * 0.5,
            )
            beam_n = 5 if laser_active else 3
            for k in range(beam_n):
                if len(out) >= MAX_CONDUIT_INSTANCES:
                    return out[:MAX_CONDUIT_INSTANCES]
                out.append({
                    "id": f"beam:{uid}:{k}",
                    "kind": "beam",
                    "sx": ux, "sy": uy, "sz": uz,
                    "cx": mx, "cy": my, "cz": mz,
                    "ex": tx, "ey": ty, "ez": tz,
                    "phase": ((k / beam_n) + i * 0.13) % 1.0,
                    "speed": 1.85 if laser_active else 1.15,
                    "scale": 0.85 if laser_active else 0.65,
                    "color": beam_color,
                })

        # The hive sends orb_color (the caste eye colour, Warden #ff2a3a) on every unit,
        # carrying or not. Only a carried orb takes it; a stream is the caste colour.
        orb_color = str(u.get("orb_color") or "#22d3ee") if carrying_orb else base_color
        arc_h = max(uy, 0.5) + (2.1 if carrying_orb else 1.45)
        cx, cy, cz = _clamp_conduit_coord(ux * 0.48, arc_h, uz * 0.48)
        stream_n = 4 if (carrying_orb or "ENGAGED" in state) else 3
        for k in range(stream_n):
            if len(out) >= MAX_CONDUIT_INSTANCES:
                return out[:MAX_CONDUIT_INSTANCES]
            out.append({
                "id": f"hive-conduit:{uid}:{k}",
                "kind": "orb" if carrying_orb else "packet",
                "sx": ux, "sy": uy, "sz": uz,
                "cx": cx, "cy": cy, "cz": cz,
                "ex": 0.0, "ey": 0.0, "ez": 0.0,
                "phase": ((k / stream_n) + i * 0.17) % 1.0,
                "speed": 1.35 if carrying_orb else 0.92,
                "scale": 0.94 if carrying_orb else 0.72,
                "color": orb_color,
            })

    for i, fx in enumerate(fx_events or []):
        if not isinstance(fx, dict):
            continue
        orig = fx.get("origin") or fx.get("position") or [0.0, 0.0, 0.0]
        tgt = fx.get("target") or [0.0, 0.0, 0.0]
        if not isinstance(orig, (list, tuple)) or len(orig) < 2:
            continue
        sx, sy, sz = _clamp_conduit_coord(
            float(orig[0]),
            float(orig[1]),
            float(orig[2]) if len(orig) > 2 else 0.0,
        )
        ex, ey, ez = _clamp_conduit_coord(
            float(tgt[0]) if isinstance(tgt, (list, tuple)) and len(tgt) >= 2 else 0.0,
            float(tgt[1]) if isinstance(tgt, (list, tuple)) and len(tgt) >= 2 else 0.0,
            float(tgt[2]) if isinstance(tgt, (list, tuple)) and len(tgt) > 2 else 0.0,
        )
        cx, cy, cz = _clamp_conduit_coord((sx + ex) * 0.5, max(sy, ey, 0.5) + 2.0, (sz + ez) * 0.5)
        fx_color = str(fx.get("color") or "#38bdf8")
        for k in range(4):
            if len(out) >= MAX_CONDUIT_INSTANCES:
                return out[:MAX_CONDUIT_INSTANCES]
            out.append({
                "id": f"fx:{i}:{k}",
                "kind": "packet",
                "sx": sx, "sy": sy, "sz": sz,
                "cx": cx, "cy": cy, "cz": cz,
                "ex": ex, "ey": ey, "ez": ez,
                "phase": (k / 4.0),
                "speed": 1.65,
                "scale": 0.95,
                "color": fx_color,
            })

    return out[:MAX_CONDUIT_INSTANCES]


def build_frame(
    units: list[dict[str, Any]],
    camera_distance: float,
    viewport_h: float = 1306.0,
    prev_lods: dict[str, int] | None = None,
    report: dict[int, dict[str, Any]] | None = None,
    target: tuple[float, float, float] | None = None,
    *,
    nodes: list[dict[str, Any]] | None = None,
    fx_events: list[dict[str, Any]] | None = None,
    receipts: list[dict[str, Any]] | None = None,
    snapshot_ts: float | None = None,
    selected_id: str | None = None,
    snap: dict[str, Any] | None = None,
    tok_rate: float = 0.0,
) -> dict[str, Any]:
    report = report or load_mesh_report()
    units, layout = place_band_units(list(units)[:MAX_OVERSEER_UNITS], snapshot_ts)
    fetches = open_fetch_counts(units, nodes)
    threat_open = threat_is_open(units, nodes)
    opens = source_open_counts(units, nodes)
    source_nodes, source_labels = build_source_nodes(opens, radius=layout["sourceRadius"])
    for i, u in enumerate(units):
        u["open_fetches"] = fetches.get(str(u.get("unit_id") or ""), 0)
        u["scale"] = view_scale(u)
        u["unit_index"] = i
        u["threat_dim"] = bool(threat_open and not unit_engaged_defense(u))
        tgt = harvest_target_of(u, layout["sourceRadius"])
        if tgt:
            u["harvest_target"] = tgt
    apply_tentacle_layout(units)
    assigned = assign_lods(units, camera_distance, viewport_h, prev_lods, target=target)
    assigned = apply_lod_policy(assigned, selected_id=selected_id)
    assigned = enforce_budget(assigned, report)
    buckets = build_buckets(assigned)
    budget = budget_from_buckets(buckets, report)
    source_active = active_harvest_sources(assigned, nodes)
    conduits = build_conduits(
        assigned,
        nodes=nodes,
        fx_events=fx_events,
        active_sources=source_active,
        source_radius=layout["sourceRadius"],
    )
    glyph_trails = build_glyph_trails(receipts, snapshot_ts)
    prev = {str(u.get("unit_id")): int(u["lod"]) for u in assigned if not u.get("culled")}
    for u in assigned:
        if u.get("culled"):
            prev[str(u.get("unit_id"))] = int(u["lod"])
    orb = orb_state(snap, tok_rate)
    return {
        "units": assigned,
        "buckets": buckets,
        "budget": budget,
        "prevLods": prev,
        "conduits": conduits,
        "sourceLabels": source_labels,
        "sourceNodes": source_nodes,
        "activeSources": sorted(source_active),
        "glyphTrails": glyph_trails,
        "bands": layout["bands"],
        "perimeter": layout["perimeter"],
        "hiveActivity": hive_activity(fetches),
        "threatOpen": threat_open,
        "orb": orb,
    }


def out_cubic(t: float) -> float:
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return 1.0 - (1.0 - t) ** 3


def in_out_sine(t: float) -> float:
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return 0.5 - 0.5 * math.cos(math.pi * t)


def bezier(
    p0: tuple[float, float], p1: tuple[float, float], p2: tuple[float, float], t: float
) -> tuple[float, float]:
    u = 1.0 - t
    return (
        u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
        u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
    )


def _span(ms: float, start: float, end: float) -> float:
    if end <= start:
        return 1.0 if ms >= end else 0.0
    return max(0.0, min(1.0, (ms - start) / (end - start)))


def entry_timeline(
    ms: float, *, reduced: bool = False, reversing: bool = False
) -> dict[str, float | bool]:
    if reduced:
        t = _span(ms, 0, 200)
        fade = 0.20
        return {
            "moteRadius": 7.0,
            "moteAlpha": 1.0,
            "fade": fade,
            "edge": t,
            "fill": t * 0.58,
            "reveal": t,
            "moteFlight": t,
            "panelTop": t,
            "panelLeft": t,
            "panelRight": t,
            "panelConsole": t,
            "panelTags": t,
            "inputLive": ms >= 200,
            "duration": 200,
        }
    duration = 500 if reversing else 1600
    fade_end = 500 if reversing else 650
    fade_t = in_out_sine(_span(ms, 0, fade_end))
    fade = 1.0 - fade_t * 0.80
    swell = in_out_sine(_span(ms, 0, 200))
    dim = in_out_sine(_span(ms, 500, 900))
    mote_r = 4.0 + 3.0 * swell
    mote_a = swell * (1.0 - 0.60 * dim)
    if reversing:
        # Exit: panels out first, scene collapses, mote returns.
        panel = 1.0 - out_cubic(_span(ms, 0, 180))
        reveal = 1.0 - out_cubic(_span(ms, 80, 500))
        flight = 1.0 - out_cubic(_span(ms, 0, 500))
        return {
            "moteRadius": 7.0,
            "moteAlpha": 1.0,
            "fade": 0.20 + 0.80 * out_cubic(_span(ms, 0, 500)),
            "edge": reveal,
            "fill": reveal * 0.58,
            "reveal": reveal,
            "moteFlight": flight,
            "panelTop": panel,
            "panelLeft": panel,
            "panelRight": panel,
            "panelConsole": panel,
            "panelTags": panel,
            "inputLive": False,
            "duration": 500,
        }
    return {
        "moteRadius": mote_r,
        "moteAlpha": max(0.0, mote_a) if swell else 0.0,
        "fade": fade,
        "edge": in_out_sine(_span(ms, 200, 700)),
        "fill": out_cubic(_span(ms, 300, 850)) * 0.58,
        "reveal": out_cubic(_span(ms, 300, 1100)),
        "moteFlight": out_cubic(_span(ms, 900, 1350)),
        "panelTop": out_cubic(_span(ms, 950, 1300)),
        "panelLeft": out_cubic(_span(ms, 1050, 1400)),
        "panelRight": out_cubic(_span(ms, 1120, 1470)),
        "panelConsole": out_cubic(_span(ms, 1180, 1530)),
        "panelTags": out_cubic(_span(ms, 1250, 1600)),
        "inputLive": ms >= 1250,
        "duration": duration,
        "moteCloseX": in_out_sine(_span(ms, 900 + 0.6 * 450, 1350)),
    }


def particle_paths(
    units: list[dict[str, Any]],
    *,
    width: float = 2110.0,
    height: float = 1306.0,
    mote: tuple[float, float] = (2064.0, 48.0),
    count: int = PARTICLE_BUDGET,
) -> list[dict[str, Any]]:
    n_mote = round(count * MOTE_FRACTION)
    ends: list[tuple[float, float]] = []
    for u in units:
        pos = u.get("position") or [u.get("x") or 0, u.get("y") or 0]
        # Map a world x,y roughly into the inset so paths have landing targets.
        ends.append((width * 0.5 + float(pos[0]) * 18.0, height * 0.55 - float(pos[1]) * 18.0))
    if not ends:
        ends = [(width * (0.2 + 0.6 * (i / max(1, count - 1))), height * 0.5) for i in range(count)]
    while len(ends) < count:
        ends.extend(ends[: count - len(ends)])
    paths = []
    for i in range(count):
        from_mote = i < n_mote
        if from_mote:
            start = mote
        else:
            gx = (i * 97) % int(width)
            gy = (i * 53) % int(height)
            start = (float(gx), float(gy))
        end = ends[i]
        # Bowed control point.
        mid = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0 - 180.0)
        start_ms = 100.0 + (250.0 * (i / max(1, count - 1)))
        paths.append({
            "fromMote": from_mote, "start": start, "control": mid,
            "end": end, "startMs": start_ms,
        })
    return paths


def particle_position(path: dict[str, Any], ms: float) -> tuple[float, float, float]:
    """Return (x, y, visible 0..1). Flight 520-760 ms after each start, out cubic."""
    local = ms - float(path["startMs"])
    if local < 0:
        return path["start"][0], path["start"][1], 0.0
    t = out_cubic(local / 240.0) if local < 240 else 1.0
    x, y = bezier(tuple(path["start"]), tuple(path["control"]), tuple(path["end"]), t)
    visible = 1.0 if local < 660 else max(0.0, 1.0 - (local - 660) / 80.0)
    return x, y, visible


def hud_mask_rects(
    width: int,
    height: int,
    *,
    emp: bool = False,
    badges: bool = False,
    full: bool = False,
    qml_hud: bool = False,
) -> list[tuple[int, int, int, int]]:
    """HUD plates that keep mouse events. The leftover hole is the 3D viewport."""
    w, h = int(width), int(height)
    if full:
        return [(0, 0, w, h)]
    if qml_hud:
        rects: list[tuple[int, int, int, int]] = []
    else:
        rects = [
            (0, 0, w, 86),
            (0, 0, min(440, w), h),
            (max(0, w - 460), 86, min(460, w), min(536, max(0, h - 86))),
            (0, max(0, h - 230), min(1650, w), min(230, h)),
        ]
    if emp:
        rects.append((max(0, w // 2 - 320), 72, min(640, w), 88))
    if badges:
        rects.append((max(0, w // 2 - 240), 90, min(480, w), 44))
    return rects


# Dock column (Iris rank 3): 360 wide, 24 from the right edge, 16 gap to the well.
DOCK_WIDTH = 360.0
DOCK_GAP = 16.0
HUD_HEADER_H = 72.0
HUD_DISPATCH_H = 48.0 + 20.0 + 12.0


def _free_viewport_edges(
    width: float,
    height: float,
    inspector_open: bool,
) -> tuple[float, float, float, float]:
    # Mirrors OverseerView.freeViewportRect: full-bleed scene, 2 percent
    # margin, header text on top, Dispatch bar at the bottom, and the dock
    # column on the right only while it is open. The drawers never count.
    w = max(1.0, float(width))
    h = max(1.0, float(height))
    mx = float(round(w * 0.02))
    my = float(round(h * 0.02))
    left = mx
    top = my + HUD_HEADER_H
    right = w - ((mx + DOCK_WIDTH + DOCK_GAP) if inspector_open else mx)
    if right <= left:
        right = w
    bottom = max(top + 1.0, h - my - HUD_DISPATCH_H)
    return left, top, right, bottom


def free_viewport_shift(
    width: float,
    height: float,
    inspector_open: bool,
) -> tuple[float, float]:
    """Lens shift that centres content in the panel-free region (v5 Space)."""
    w = max(1.0, float(width))
    h = max(1.0, float(height))
    left, top, right, bottom = _free_viewport_edges(w, h, inspector_open)
    cx = (left + right) / 2.0
    cy = (top + bottom) / 2.0
    return (-(cx - w / 2.0) / w, (cy - h / 2.0) / h)


def free_viewport_center(
    width: float,
    height: float,
    inspector_open: bool,
) -> tuple[float, float]:
    """Pixel centre of the panel-free well (top-left origin)."""
    left, top, right, bottom = _free_viewport_edges(width, height, inspector_open)
    return ((left + right) / 2.0, (top + bottom) / 2.0)


def lens_shift_offset(
    distance: float,
    pitch: float,
    width: float,
    height: float,
    inspector_open: bool,
) -> tuple[float, float, float]:
    """World-space camera translation matching OverseerView.lensShiftOffset."""
    sx, sy = free_viewport_shift(width, height, inspector_open)
    p = math.radians(float(pitch))
    d = float(distance)
    vis_h = 2.0 * d * math.tan(math.radians(FOV_DEG) / 2.0)
    aspect = (float(width) / float(height)) if height > 1 and width > 1 else (2110.0 / 1306.0)
    vis_w = vis_h * aspect
    return (sx * vis_w, sy * vis_h * math.cos(p), -sy * vis_h * math.sin(p))


def project_world_to_viewport(
    world: tuple[float, float, float],
    distance: float,
    pitch: float | None,
    target: tuple[float, float, float],
    width: float,
    height: float,
    inspector_open: bool,
) -> tuple[float, float]:
    """Project a world point through the product camera (35 deg vertical + lens shift).

    Returns pixel coordinates with origin at the top-left of the view.
    """
    pdeg = pitch_deg(distance) if pitch is None else float(pitch)
    p = math.radians(pdeg)
    eye = camera_eye(distance, pdeg, target=target)
    sh = lens_shift_offset(distance, pdeg, width, height, inspector_open)
    cam = (eye[0] + sh[0], eye[1] + sh[1], eye[2] + sh[2])
    dx = float(world[0]) - cam[0]
    dy = float(world[1]) - cam[1]
    dz = float(world[2]) - cam[2]
    c, s = math.cos(p), math.sin(p)
    vx = dx
    vy = dy * c - dz * s
    vz = dy * s + dz * c
    depth = -vz
    if depth <= 1e-9:
        return (float("nan"), float("nan"))
    half = math.tan(math.radians(FOV_DEG) / 2.0)
    aspect = (float(width) / float(height)) if height > 1 and width > 1 else (2110.0 / 1306.0)
    ndc_x = vx / (depth * half * aspect)
    ndc_y = vy / (depth * half)
    px = (ndc_x * 0.5 + 0.5) * float(width)
    py = (0.5 - ndc_y * 0.5) * float(height)
    return (px, py)


def camera_evidence(
    distance: Any,
    pitch: Any,
    target: tuple[Any, Any, Any] | None = None,
    selected_id: str | None = None,
) -> dict[str, Any]:
    """Report live camera numbers only. Omit anything that was not read."""
    out: dict[str, Any] = {}
    if distance is not None:
        out["cameraDistance"] = float(distance)
        out["framing"] = framing_name(float(distance))
    if pitch is not None:
        out["cameraPitch"] = float(pitch)
    if target is not None:
        out["cameraTargetX"] = float(target[0])
        out["cameraTargetY"] = float(target[1])
        out["cameraTargetZ"] = float(target[2])
    if selected_id is not None:
        out["selectedUnitId"] = str(selected_id)
    return out


def point_in_rects(x: int, y: int, rects: list[tuple[int, int, int, int]]) -> bool:
    for rx, ry, rw, rh in rects:
        if rx <= x < rx + rw and ry <= y < ry + rh:
            return True
    return False


def fetch_snapshot(host: str, port: int, token: str, opener: Any = None) -> dict[str, Any]:
    """GET /api/snapshot with the session token header. Never log the token."""
    import urllib.request

    req = urllib.request.Request(
        f"http://{host}:{int(port)}/api/snapshot",
        headers={"X-Sentinel-Token": token, "Accept": "application/json"},
        method="GET",
    )
    get = opener or urllib.request.urlopen
    with get(req, timeout=2.0) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))



def coerce_hud_payload(payload: Any) -> dict[str, Any]:
    """Turn a QML hudCommand payload into a plain dict."""
    if isinstance(payload, dict):
        return payload
    to_var = getattr(payload, "toVariant", None)
    if callable(to_var):
        value = to_var()
        if isinstance(value, dict):
            return value
    return {}


def resolve_hud_command(
    name: str,
    payload: Any = None,
    selected_unit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Plan a HUD action on an existing route, or refuse it.

    Recall is not caste scale-down: that can retire a different unit.
    Retask is refused: Hive._acquire_unit returns the preferred unit when
    that id is still in the hive and the caste matches, including when the
    unit is busy or not PATROLLING (sentinel/core/hive.py:579-583), but if
    the id is missing it falls through to another PATROLLING unit, a spawn,
    or any unit of that caste (:585-599). dispatch_task then recruits
    wingmen from other units (:737-739). There is no fail-closed per-unit
    route, and a UI precheck cannot close that race. Retire posts
    retire_unit for the selected id only (hive.retire_unit pops that id
    or returns False). Emergency halt never includes restore. Camera
    focus frames the selected unit locally from snapshot geometry and
    does not post a hive route. coreFocus and exit_core are also local
    view actions: they move the camera only, and never post a hive
    route or write a status under the composer.
    """
    data = coerce_hud_payload(payload)
    selected = selected_unit if isinstance(selected_unit, dict) else {}
    selected_id = str(selected.get("unit_id") or "").strip()
    payload_id = str(data.get("unit_id") or "").strip()
    name = str(name or "")

    def refuse(status: str) -> dict[str, Any]:
        return {
            "ok": False,
            "path": None,
            "body": None,
            "status": status,
            "name": name,
        }

    def accept(path: str, body: dict[str, Any], status: str) -> dict[str, Any]:
        return {
            "ok": True,
            "path": path,
            "body": body,
            "status": status,
            "name": name,
        }

    if name == "focus":
        uid = payload_id or selected_id
        if not uid:
            return refuse("Unavailable: focus needs a selected unit")
        if payload_id and selected_id and payload_id != selected_id:
            return refuse("Unavailable: focus id does not match the selected unit")
        return {
            "ok": True,
            "path": None,
            "body": None,
            "status": "",
            "name": name,
            "local": True,
        }
    if name in {"fit_swarm", "fitSwarm"}:
        return {
            "ok": True,
            "path": None,
            "body": None,
            "status": "",
            "name": name,
            "local": True,
        }
    if name in {"core_focus", "coreFocus", "exit_core", "exitCore"}:
        return {
            "ok": True,
            "path": None,
            "body": None,
            "status": "",
            "name": name,
            "local": True,
        }
    if name == "recall":
        return refuse(
            "Unavailable: no per-unit recall route; caste scale-down can "
            "affect a different unit"
        )
    if name == "deploy":
        selected_caste = str(selected.get("caste") or "").strip().lower()
        payload_caste = str(data.get("caste") or "").strip().lower()
        if payload_caste and selected_caste and payload_caste != selected_caste:
            return refuse(
                "Unavailable: deploy caste does not match the selected unit"
            )
        caste = selected_caste or payload_caste
        if not caste:
            return refuse(
                "Unavailable: deploy needs a caste (existing scale-up)"
            )
        return accept(
            "/api/overseer/scale",
            {"caste": caste, "delta": 1},
            "Deploy requested",
        )
    if name in {"emp_restore", "restore"}:
        return refuse(
            "Unavailable: emergency restore is not available from this HUD"
        )
    if name == "emp_halt":
        return accept(
            "/api/overseer/emp",
            {"reason": str(data.get("reason") or "Overseer emergency stop")},
            "Emergency stop requested",
        )
    if name == "dispatch":
        return accept(
            "/api/overseer/mission",
            {
                "mode": str(data.get("mode") or "multi"),
                "query": str(data.get("query") or ""),
            },
            "Mission requested",
        )
    if name == "retire":
        if not selected_id:
            return refuse("Unavailable: retire requires a selected unit")
        if payload_id and payload_id != selected_id:
            return refuse(
                "Unavailable: retire would not match the selected unit"
            )
        return accept(
            "/api/command",
            {"op": "retire_unit", "unit_id": selected_id},
            "Retire requested",
        )
    if name == "retask":
        return refuse(
            "Unavailable: dispatch_task is not fail-closed on the selected "
            "unit; if that unit is gone the hive acquires another of the "
            "same caste or spawns one"
        )
    return refuse(f"Unavailable: no existing route for {name}")


def command_status(ok: bool, body: Any) -> str:
    """HUD status for a finished bridge request. A completed HTTP request can
    still carry a backend refusal; show the hive's reason, not a bare failure."""
    if not ok:
        return "Request failed: Sentinel did not answer"
    if isinstance(body, dict) and body.get("ok") is False:
        reason = " ".join(str(body.get("error") or "").split())[:160]
        return f"Refused: {reason}" if reason else "Refused by Sentinel"
    if not isinstance(body, dict):
        return "Request failed: Sentinel did not answer"
    return "Request completed"


def post_overseer(
    host: str,
    port: int,
    token: str,
    path: str,
    payload: dict[str, Any] | None = None,
    opener: Any = None,
) -> dict[str, Any]:
    """POST an existing Overseer route with the session token header. Never log the token."""
    import urllib.error
    import urllib.request

    dest = path if str(path).startswith("/") else f"/{path}"
    body = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        f"http://{host}:{int(port)}{dest}",
        data=body,
        headers={
            "X-Sentinel-Token": token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    get = opener or urllib.request.urlopen
    try:
        with get(req, timeout=4.0) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        # The bridge answers a refusal (400) with {"ok": false, "error": ...}.
        raw = exc.read()
        try:
            refused = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            refused = {}
        if not isinstance(refused, dict):
            refused = {}
        return {"ok": False, "error": str(refused.get("error") or f"HTTP {exc.code}")}
    return json.loads(raw.decode("utf-8") or "{}")
