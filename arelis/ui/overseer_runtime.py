"""Overseer frame math: LOD buckets, draw budget, entry Bezier, timeline.

Numbers follow Iris pass 5. Used by the Qt Quick 3D view and by tests.
No GPU claims; this only counts instances against exported mesh totals.
"""

from __future__ import annotations

import json
import math
import re
from collections import deque
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
    if selected:
        return False
    return zoom_t(distance) > INSPECTOR_COLLAPSE_T


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


def _caste_capabilities(castes: list[dict[str, Any]] | None, caste: str) -> str:
    wanted = str(caste or "").lower()
    for row in castes or []:
        cid = str(row.get("caste_id") or row.get("caste") or "").lower()
        if cid != wanted:
            continue
        caps = row.get("allowed_capabilities") or row.get("capabilities")
        if caps:
            return ", ".join(str(item) for item in caps)
    return UNAVAILABLE


def _unit_warrant(receipts: list[dict[str, Any]] | None, unit_id: str) -> str:
    uid = str(unit_id or "")
    for row in reversed(list(receipts or [])):
        if str(row.get("unit_id") or row.get("sentinel_unit") or "") != uid:
            continue
        digest = row.get("sha256")
        if digest:
            return str(digest)
    return UNAVAILABLE


def inspector_card(
    unit: dict[str, Any] | None,
    *,
    castes: list[dict[str, Any]] | None = None,
    receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not unit:
        return {
            "unit_id": "",
            "state": UNAVAILABLE,
            "target": UNAVAILABLE,
            "last_action": UNAVAILABLE,
            "time_on_task": UNAVAILABLE,
            "eyes": UNAVAILABLE,
            "tentacles": UNAVAILABLE,
            "capabilities": UNAVAILABLE,
            "warrant_hash": UNAVAILABLE,
            "sparkline": UNAVAILABLE,
        }
    return {
        "unit_id": unit.get("unit_id") or "",
        "state": unit.get("state") or UNAVAILABLE,
        "target": unit.get("target_node_id") or UNAVAILABLE,
        "last_action": UNAVAILABLE,
        "time_on_task": UNAVAILABLE,
        "eyes": UNAVAILABLE,
        "tentacles": unit["tentacles"] if "tentacles" in unit else UNAVAILABLE,
        "capabilities": _caste_capabilities(castes, str(unit.get("caste") or "")),
        "warrant_hash": _unit_warrant(receipts, str(unit.get("unit_id") or "")),
        "sparkline": UNAVAILABLE,
        "caste": unit.get("caste"),
        "task": unit.get("current_task") or empty_task_label(unit.get("state")),
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

    def reset(self) -> None:
        self._last_seq = None
        self._raw.clear()
        self._groups.clear()

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
    return {
        "pills": pill_counts(
            units,
            metrics if isinstance(metrics, dict) else None,
            (snap or {}).get("telemetry_log") if isinstance(snap, dict) else None,
        ),
        "swarmRows": swarm_rows(units, by=group_by, query=search, collapsed=collapsed),
        "inspector": inspector_card(
            selected,
            castes=(snap or {}).get("castes") if isinstance(snap, dict) else None,
            receipts=(snap or {}).get("recent_receipts") if isinstance(snap, dict) else None,
        ),
        "inspectorCollapsed": inspector_collapsed(camera_distance, selected_id or None),
        "logs": _session_rows(snap, log_session, log_filter, log_query, log_repeats),
        "title": "Sentinels",
        "statusLine": status_line,
    }


ZOOM_MIN = 6.0
ZOOM_MAX = 110.0
ZOOM_NOTCH = 1.18
RUBBER = 0.08
PITCH_CLOSE_DEG = 22.0
PITCH_WIDE_DEG = 55.0
# Smallest dolly on the 6..110 / pitch_deg curve that keeps the 23 m
# ring inside a 2110x1306 35 mm plate (not the 110 m "fit swarm" stop).
DEFAULT_CAMERA_DISTANCE = 76.0
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
    parts = (report.get(int(lod)) or {}).get("parts") or {}
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

    while assigned_tris(rows, report) > MAX_TRIS:
        demote = [u for u in rows if not u["culled"] and int(u["lod"]) < 2]
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
    return errors


def validate_overseer_shaders(asset_root: Path | None = None) -> list[str]:
    root = asset_root or (asset_dir() / "shaders")
    errors: list[str] = []
    for name in (
        "hull.vert", "hull.frag", "emissive.vert", "emissive.frag", "lens.vert", "lens.frag",
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
        buckets[bucket_key(caste, lod)].append(
            {
                "unit_id": u.get("unit_id"),
                "caste": caste,
                "lod": lod,
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


def _clamp_conduit_coord(
    x: float, y: float, z: float, limit: float = 36.0
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
) -> list[dict[str, Any]]:
    """Build hardware-instanced 3D conduit packet and node beacon descriptors."""
    out: list[dict[str, Any]] = []
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
        out.append({
            "id": f"beacon:{nid}",
            "kind": "node",
            "sx": nx, "sy": ny, "sz": nz,
            "cx": nx, "cy": ny, "cz": nz,
            "ex": nx, "ey": ny, "ez": nz,
            "phase": (i * 0.19) % 1.0,
            "speed": 0.0,
            "scale": 1.65 if hot else 1.25,
            "color": color,
        })
        pkt_count = 5 if hot else 2
        speed = 1.05 if hot else 0.42
        arc_y = max(ny, 0.4) + (2.4 if hot else 1.35)
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
                "scale": 0.86 if hot else 0.58,
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
) -> dict[str, Any]:
    report = report or load_mesh_report()
    assigned = assign_lods(units, camera_distance, viewport_h, prev_lods, target=target)
    assigned = enforce_budget(assigned, report)
    buckets = build_buckets(assigned)
    budget = budget_from_buckets(buckets, report)
    conduits = build_conduits(assigned, nodes=nodes, fx_events=fx_events)
    prev = {str(u.get("unit_id")): int(u["lod"]) for u in assigned if not u.get("culled")}
    for u in assigned:
        if u.get("culled"):
            prev[str(u.get("unit_id"))] = int(u["lod"])
    return {
        "units": assigned,
        "buckets": buckets,
        "budget": budget,
        "prevLods": prev,
        "conduits": conduits,
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


def free_viewport_shift(
    width: float,
    height: float,
    inspector_open: bool,
) -> tuple[float, float]:
    """Lens shift that centres content in the panel-free region (v5 Space)."""
    w = max(1.0, float(width))
    h = max(1.0, float(height))
    left = min(440.0, w * 0.26)
    top = 86.0
    right = w - (min(460.0, w * 0.28) if inspector_open else 20.0)
    if right <= left:
        right = w
    bottom = max(top + 1.0, h - 230.0)
    cx = (left + right) / 2.0
    cy = (top + bottom) / 2.0
    return (-(cx - w / 2.0) / w, (cy - h / 2.0) / h)


def free_viewport_center(
    width: float,
    height: float,
    inspector_open: bool,
) -> tuple[float, float]:
    """Pixel centre of the panel-free well (top-left origin)."""
    w = max(1.0, float(width))
    h = max(1.0, float(height))
    left = min(440.0, w * 0.26)
    top = 86.0
    right = w - (min(460.0, w * 0.28) if inspector_open else 20.0)
    if right <= left:
        right = w
    bottom = max(top + 1.0, h - 230.0)
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
    does not post a hive route.
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


def post_overseer(
    host: str,
    port: int,
    token: str,
    path: str,
    payload: dict[str, Any] | None = None,
    opener: Any = None,
) -> dict[str, Any]:
    """POST an existing Overseer route with the session token header. Never log the token."""
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
    with get(req, timeout=4.0) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8") or "{}")
