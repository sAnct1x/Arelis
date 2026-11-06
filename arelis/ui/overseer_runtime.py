"""Overseer frame math: LOD buckets, draw budget, entry Bezier, timeline.

Numbers follow Iris pass 5. Used by the Qt Quick 3D view and by tests.
No GPU claims; this only counts instances against exported mesh totals.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

CASTES = ("warden", "stalker", "harvester", "sanitizer", "tripwire")
PARTS = ("hull", "emissive", "lens")
CASTE_COLOR = {
    "warden": "#a78bfa",
    "stalker": "#e879f9",
    "harvester": "#8fd3ff",
    "sanitizer": "#f2c56b",
    "tripwire": "#7ee0c8",
}
LENS_COLOR = {
    "warden": "#5a1cff",
    "stalker": "#c010e0",
    "harvester": "#0a7cff",
    "sanitizer": "#ff8a00",
    "tripwire": "#7ee0c8",
}
LOD0_PX = 180.0
LOD1_PX = 60.0
HYST = 0.15
FOV_DEG = 35.0
# Chosen so 18 m at 35 mm on a 1306 px plate projects about 180 px.
UNIT_WORLD_H = 1.56
PARTICLE_BUDGET = 520
MOTE_FRACTION = 0.40
SCENE_FIXED_DRAW = 10
MAX_UNIT_DRAW = 45  # 5 castes x 3 LOD x 3 parts
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
            if name.endswith("_hull"):
                part = "hull"
            elif name.endswith("_emissive"):
                part = "emissive"
            elif name.endswith("_lens"):
                part = "lens"
            parts[part] = int(count)
        by_lod[int(row["lod"])] = {
            "tris": int(row["tris"]), "parts": parts, "target": int(row["target"])
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


def heading_deg(heading: Any) -> float:
    if isinstance(heading, (int, float)):
        return float(heading) * 180.0 / math.pi
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


def assign_lods(
    units: list[dict[str, Any]],
    camera_distance: float,
    viewport_h: float = 1306.0,
    prev: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    prev = prev or {}
    assigned = []
    for u in units:
        uid = str(u.get("unit_id") or "")
        scale = float(u.get("scale") or 1.0)
        height = projected_height_px(camera_distance, viewport_h, scale)
        lod = choose_lod(height, prev.get(uid))
        row = dict(u)
        row["lod"] = lod
        row["height_px"] = height
        assigned.append(row)
    return assigned


def bucket_key(caste: str, lod: int) -> str:
    return f"{caste}:{int(lod)}"


def build_buckets(units: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {
        f"{c}:{lod}": [] for c in CASTES for lod in (0, 1, 2)
    }
    for i, u in enumerate(units):
        caste = str(u.get("caste") or "warden").lower()
        if caste not in CASTE_COLOR:
            caste = "warden"
        lod = int(u.get("lod", 1))
        lod = 0 if lod < 0 else 2 if lod > 2 else lod
        pos = u.get("position") or [u.get("x") or 0, u.get("y") or 0, u.get("z") or 0]
        x, y, z = float(pos[0]), float(pos[1]), float(pos[2] if len(pos) > 2 else 0)
        state = str(u.get("state") or "")
        limp = 1.0 if "EMP" in state.upper() or "HALT" in state.upper() else 0.0
        scale = float(u.get("scale") or 1.0)
        buckets[bucket_key(caste, lod)].append(
            {
                "unit_id": u.get("unit_id"),
                "caste": caste,
                "lod": lod,
                "x": x,
                "y": y,
                "z": z,
                "heading_deg": heading_deg(u.get("heading")),
                "scale": scale,
                "color": CASTE_COLOR[caste],
                "lens": LENS_COLOR[caste],
                "phase": float(u.get("phase") or (i * 1.7)),
                "claw": claw_open(state),
                "limp": limp,
            }
        )
    return buckets


def budget_from_buckets(
    buckets: dict[str, list[dict[str, Any]]],
    report: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    lod_counts = {0: 0, 1: 0, 2: 0}
    tris = 0
    unit_draw = 0
    active = []
    for caste in CASTES:
        for lod in (0, 1, 2):
            rows = buckets.get(bucket_key(caste, lod)) or []
            n = len(rows)
            lod_counts[lod] += n
            if n == 0:
                continue
            parts = (report.get(lod) or {}).get("parts") or {}
            for part in PARTS:
                part_tris = int(parts.get(part) or 0)
                tris += part_tris * n
                unit_draw += 1
                active.append({
                    "caste": caste, "lod": lod, "part": part,
                    "count": n, "tris": part_tris * n,
                })
    return {
        "unitTris": tris,
        "unitDrawCalls": unit_draw,
        "drawCalls": unit_draw + SCENE_FIXED_DRAW,
        "lodCounts": lod_counts,
        "activeModels": active,
        "withinTriBudget": tris <= MAX_TRIS,
        "withinDrawBudget": unit_draw <= MAX_UNIT_DRAW,
    }


def build_frame(
    units: list[dict[str, Any]],
    camera_distance: float,
    viewport_h: float = 1306.0,
    prev_lods: dict[str, int] | None = None,
    report: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    report = report or load_mesh_report()
    assigned = assign_lods(units, camera_distance, viewport_h, prev_lods)
    buckets = build_buckets(assigned)
    budget = budget_from_buckets(buckets, report)
    prev = {str(u.get("unit_id")): int(u["lod"]) for u in assigned}
    return {"units": assigned, "buckets": buckets, "budget": budget, "prevLods": prev}


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
) -> list[tuple[int, int, int, int]]:
    """HUD plates that keep mouse events. The leftover hole is the 3D viewport."""
    w, h = int(width), int(height)
    if full:
        return [(0, 0, w, h)]
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
