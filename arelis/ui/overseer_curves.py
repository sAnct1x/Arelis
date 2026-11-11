"""Tentacle control points and the RGBA32F curve texture for Overseer Pass C.

Control points are in world metres, 8 per tentacle, rows = unitIndex * 16 + slot.
The QML type is registered as Arelis.Overseer.OverseerCurveTex when this
module is imported (overseer_runtime imports it on load).
"""

from __future__ import annotations

import array
import math
from typing import Any

from PySide6.QtCore import Property, QByteArray, QSize, Slot
from PySide6.QtQml import QmlElement
from PySide6.QtQuick3D import QQuick3DTextureData

QML_IMPORT_NAME = "Arelis.Overseer"
QML_IMPORT_MAJOR_VERSION = 1

CURVE_WIDTH = 8
CURVE_ROWS = 2048  # 128 units x 16 tentacle slots
MAX_UNITS = 128
SLOTS = 16
ROOT_LOD2 = (-1.67, 0.02, 0.0)
ROOT_LOD1 = (-2.08, 0.02, 0.0)
LENGTH_LOD2 = 1.3
LENGTH_LOD1 = 2.4
LENGTH_LOD0 = 2.8
TENTACLES_BY_LOD = (14, 8, 4)


def _wave_hz(speed: float) -> float:
    # Idle 0.6 Hz at speed 0.55, busy 2.0 Hz at speed 2.2 (MOTION-BRIEF).
    u = max(0.0, min(1.0, (float(speed) - 0.55) / 1.65))
    return 0.6 + 1.4 * u


def _curl(speed: float) -> float:
    u = max(0.0, min(1.0, (float(speed) - 0.55) / 1.65))
    return 0.4 + 0.6 * u


def tentacle_dir(slot: int, count: int) -> tuple[float, float, float]:
    """Unit-space direction of one tail tentacle, mostly along -X."""
    n = max(1, int(count))
    # Even slots on the +Z side, odd on -Z, stacked in Y so pairs splay.
    pair = slot // 2
    side = 1.0 if (slot % 2) == 0 else -1.0
    layers = max(1, (n + 1) // 2)
    y = (pair - (layers - 1) / 2.0) * 0.35
    z = side * (0.55 + 0.12 * pair)
    x = -1.0
    mag = math.sqrt(x * x + y * y + z * z) or 1.0
    return (x / mag, y / mag, z / mag)


def _qrot(yaw_deg: float, pitch_deg: float, roll_deg: float):
    """Yaw around +Y, then pitch around +X, then roll around +Z, as a 3x3."""
    y = math.radians(yaw_deg)
    p = math.radians(pitch_deg)
    r = math.radians(roll_deg)
    cy, sy = math.cos(y), math.sin(y)
    cp, sp = math.cos(p), math.sin(p)
    cr, sr = math.cos(r), math.sin(r)
    # R = Rz(roll) * Rx(pitch) * Ry(yaw) applied to column vectors: world = R * local.
    # Qt euler is z, then x, then y, i.e. R = Ry * Rx * Rz.
    # Match Qt Quick 3D Node: rotation applied in order z, then x, then y.
    r00 = cy * cr + sy * sp * sr
    r01 = sy * sp * cr - cy * sr
    r02 = sy * cp
    r10 = cp * sr
    r11 = cp * cr
    r12 = -sp
    r20 = -sy * cr + cy * sp * sr
    r21 = cy * sp * cr + sy * sr
    r22 = cy * cp
    return (r00, r01, r02, r10, r11, r12, r20, r21, r22)


def _xf(m, p: tuple[float, float, float], origin: tuple[float, float, float], scale: float):
    x, y, z = p[0] * scale, p[1] * scale, p[2] * scale
    return (
        origin[0] + m[0] * x + m[1] * y + m[2] * z,
        origin[1] + m[3] * x + m[4] * y + m[5] * z,
        origin[2] + m[6] * x + m[7] * y + m[8] * z,
    )


def ease_out_cubic(t: float) -> float:
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return 1.0 - (1.0 - t) ** 3


def control_points(
    *,
    pose: tuple[float, float, float],
    yaw: float,
    pitch: float = 0.0,
    roll: float = 0.0,
    scale: float = 1.0,
    lod: int = 2,
    slot: int = 0,
    time: float = 0.0,
    speed: float = 0.55,
    limp: float = 0.0,
    reach: float = 0.0,
    target: tuple[float, float, float] | None = None,
    phase: float = 0.0,
) -> list[tuple[float, float, float]]:
    """Eight world-space Catmull-Rom points for one tentacle."""
    lod = 0 if lod < 0 else 2 if lod > 2 else lod
    count = TENTACLES_BY_LOD[lod]
    root = ROOT_LOD2 if lod == 2 else ROOT_LOD1
    length = (LENGTH_LOD2, LENGTH_LOD1, LENGTH_LOD0)[2 - lod] if lod in (0, 1, 2) else LENGTH_LOD2
    length = LENGTH_LOD2 if lod == 2 else (LENGTH_LOD1 if lod == 1 else LENGTH_LOD0)
    direction = tentacle_dir(slot, count)
    m = _qrot(yaw, pitch, roll)
    origin = pose
    hz = _wave_hz(speed)
    curl = _curl(speed) * (1.0 - 0.7 * limp)
    amp = 0.16 * scale * (1.0 - 0.75 * limp)
    pts: list[tuple[float, float, float]] = []
    world_root = _xf(m, root, origin, scale)
    # A pair of "front" tentacles (slots 0,1 then 2,3...) reaches toward the source.
    pair = slot // 2
    reach_w = 0.0
    if reach > 0.0 and target is not None and pair < math.ceil(reach):
        reach_w = max(0.0, min(1.0, float(reach) - pair))
        reach_w = 1.0 if reach_w > 1.0 else reach_w
        if reach >= pair + 1:
            reach_w = 1.0
        elif reach > pair:
            reach_w = reach - pair
    for i in range(CURVE_WIDTH):
        u = i / 7.0
        # Rest pose along the tail direction, with a slight downward curl.
        local_u = (
            root[0] + direction[0] * length * u,
            root[1] + direction[1] * length * u - curl * 0.25 * u * u * length,
            root[2] + direction[2] * length * u,
        )
        wave = math.sin(u * 5.5 + time * hz * 2.0 * math.pi + phase + slot) * amp * u
        wave2 = math.cos(u * 4.2 + time * hz * 2.0 * math.pi * 1.7 + phase) * amp * 0.7 * u
        # Wave in the plane perpendicular to the tentacle.
        px, py, pz = local_u
        px += wave * direction[2]
        py += wave2
        pz += -wave * direction[0]
        world = _xf(m, (px, py, pz), origin, scale)
        if reach_w > 0.0 and target is not None:
            # Blend the tip toward the source; the root stays on the hull.
            tx = world_root[0] + (target[0] - world_root[0]) * u
            ty = world_root[1] + (target[1] - world_root[1]) * u
            tz = world_root[2] + (target[2] - world_root[2]) * u
            k = reach_w * ease_out_cubic(u)
            world = (
                world[0] + (tx - world[0]) * k,
                world[1] + (ty - world[1]) * k,
                world[2] + (tz - world[2]) * k,
            )
        pts.append(world)
    return pts


def pack_rows(units: list[dict[str, Any]], time: float) -> array.array:
    """Pack all tentacle control points into an 8 x 2048 RGBA32F buffer."""
    buf = array.array("f", [0.0] * (CURVE_WIDTH * CURVE_ROWS * 4))
    for unit in units:
        idx = int(unit.get("index") or 0)
        if idx < 0 or idx >= MAX_UNITS:
            continue
        lod = int(unit.get("lod", 2))
        count = TENTACLES_BY_LOD[0 if lod < 0 else 2 if lod > 2 else lod]
        pose = (
            float(unit.get("x") or 0.0),
            float(unit.get("y") or 0.0),
            float(unit.get("z") or 0.0),
        )
        yaw = float(unit.get("yaw") or 0.0)
        pitch = float(unit.get("pitch") or 0.0)
        roll = float(unit.get("roll") or 0.0)
        scale = float(unit.get("scale") or 1.0)
        speed = float(unit.get("speed") if unit.get("speed") is not None else 0.55)
        limp = float(unit.get("limp") or 0.0)
        reach = float(unit.get("reach") or 0.0)
        phase = float(unit.get("phase") or 0.0)
        tgt = unit.get("target")
        target = None
        if isinstance(tgt, (list, tuple)) and len(tgt) >= 3:
            target = (float(tgt[0]), float(tgt[1]), float(tgt[2]))
        for slot in range(count):
            row = idx * SLOTS + slot
            pts = control_points(
                pose=pose, yaw=yaw, pitch=pitch, roll=roll, scale=scale,
                lod=lod, slot=slot, time=time, speed=speed, limp=limp,
                reach=reach, target=target, phase=phase,
            )
            for i, p in enumerate(pts):
                off = (row * CURVE_WIDTH + i) * 4
                buf[off] = p[0]
                buf[off + 1] = p[1]
                buf[off + 2] = p[2]
                buf[off + 3] = 1.0
    return buf


@QmlElement
class OverseerCurveTex(QQuick3DTextureData):
    """8 x 2048 RGBA32F control-point table, refreshed each frame from unit poses."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSize(QSize(CURVE_WIDTH, CURVE_ROWS))
        self.setFormat(QQuick3DTextureData.Format.RGBA32F)
        self.setHasTransparency(False)
        self.setTextureData(QByteArray(b"\x00" * (CURVE_WIDTH * CURVE_ROWS * 16)))
        self._count = 0

    def _count_get(self) -> int:
        return self._count

    def _count_set(self, n: int) -> None:
        self._count = int(n)

    unitCount = Property(int, _count_get, _count_set)  # noqa: N815

    @Slot("QVariant", float)
    def refresh(self, units, time: float) -> None:
        rows: list[dict[str, Any]] = []
        if units is None:
            units = []
        # QML can pass a JS array of objects or a Python list.
        try:
            n = len(units)
        except TypeError:
            n = 0
        for i in range(n):
            row = units[i]
            if hasattr(row, "toVariant"):
                row = row.toVariant()
            if isinstance(row, dict):
                rows.append(row)
        buf = pack_rows(rows, float(time))
        self.setTextureData(QByteArray(buf.tobytes()))
        self._count = len(rows)

# --- Pass E: per-unit state texture and static strand table -----------------
# The Pass C curve texture packed 8 world-space Catmull-Rom points per
# tentacle, but refresh() received a QML array of objects that did not
# convert to Python dicts, so every row stayed zero and the shader wrote
# NaN positions. Pass E uploads a flat float array instead (one 32-float
# row per unit) and evaluates the centreline in the vertex shader.

UNIT_TEX_WIDTH = 8
UNIT_TEX_ROWS = 128
UNIT_FLOATS = UNIT_TEX_WIDTH * 4  # 32
STRAND_TEX_WIDTH = 6
STRAND_TEX_ROWS = 64
STRANDS_BY_LOD = (19, 13, 10)
TRAIL_BY_LOD = (15, 11, 8)
ARMS_BY_LOD = (4, 2, 2)
HEAD_L = 2.0
TRAIL_LEN = 2.2 * HEAD_L
COLLAR_X = -0.93
COLLAR_RY, COLLAR_RZ = 0.30, 0.36
ARM_ROOTS = (
    (0.62, -0.40, 0.38),
    (0.62, -0.40, -0.38),
    (0.50, -0.45, 0.20),
    (0.50, -0.45, -0.20),
)
R0, R1 = 0.085, 0.038
ARM_LEN = (1.15, 0.80)
ARM_R = ((0.07, 0.04), (0.045, 0.028))
CLAW_LEN = (0.22, 0.42, 0.26)
CLAW_TIP_R = (1.0, 2.0, 1.4)
GOLD = 2.399963
BEAD_R = 0.16
DEFAULT_HOLD = (1.05, -0.72, 0.0)
HEAD_TRIS = (13092, 6056, 1192)  # fix-c05bb78 head v2
TENTACLE_TRIS = (1792, 648, 66)


def _hsh(i: int, k: int = 0) -> float:
    x = math.sin(i * 12.9898 + k * 78.233) * 43758.5453
    return x - math.floor(x)


def _bez_len(p0, p1, p2, p3, samples: int = 64) -> float:
    total = 0.0
    prev = p0
    for k in range(1, samples):
        u = k / (samples - 1)
        v = 1.0 - u
        p = (
            v * v * v * p0[0] + 3 * v * v * u * p1[0] + 3 * v * u * u * p2[0] + u * u * u * p3[0],
            v * v * v * p0[1] + 3 * v * v * u * p1[1] + 3 * v * u * u * p2[1] + u * u * u * p3[1],
            v * v * v * p0[2] + 3 * v * v * u * p1[2] + 3 * v * u * u * p2[2] + u * u * u * p3[2],
        )
        total += math.dist(prev, p)
        prev = p
    return total


def _coil_params(
    root: tuple[float, float, float], side: float, length: float
) -> tuple[float, float, float]:
    rc = BEAD_R + 0.11
    h = DEFAULT_HOLD
    c3 = (h[0] - rc, h[1], h[2] + 0.14 * side)
    c1 = (root[0] - 0.55, root[1] - 0.75, root[2] + 0.62 * side)
    c2 = (c3[0] - 0.9, c3[1] - 0.55, c3[2] + 0.38 * side)
    lead_len = _bez_len(root, c1, c2, c3)
    turns = min(1.6, max(0.6, (length - lead_len) / (2.0 * math.pi * rc)))
    uc = min(0.8, max(0.35, lead_len / max(length, 1e-6)))
    return uc, turns, lead_len


def bezier_fit_k(p0, d1, d2, p3, length: float) -> float:
    """Handle length k so the cubic is about `length` long (CPU, once per hold)."""
    lo, hi = 0.0, 6.0
    for _ in range(24):
        k = 0.5 * (lo + hi)
        p1 = (p0[0] + d1[0] * k, p0[1] + d1[1] * k, p0[2] + d1[2] * k)
        p2 = (p3[0] + d2[0] * k, p3[1] + d2[1] * k, p3[2] + d2[2] * k)
        if _bez_len(p0, p1, p2, p3) < length:
            lo = k
        else:
            hi = k
    return 0.5 * (lo + hi)


def lane_len_mul(gap: float, scale: float) -> float:
    """Lt = clamp(gap - 0.35 Lh, 1.6 Lh, 2.4 Lh); lenMul = Lt / (2.2 Lh)."""
    lh = HEAD_L * max(float(scale), 1e-4)
    lt = min(max(float(gap) - 0.35 * lh, 1.6 * lh), 2.4 * lh)
    return lt / (2.2 * lh)


def unit_tris(lod: int) -> int:
    lod = 0 if lod < 0 else 2 if lod > 2 else lod
    return HEAD_TRIS[lod] + STRANDS_BY_LOD[lod] * TENTACLE_TRIS[lod]


def strand_table(lod: int) -> list[dict[str, Any]]:
    """Static per-strand data for one unit at one LOD (SPEC 5.2 / sentinel_anim.strands)."""
    lod = 0 if lod < 0 else 2 if lod > 2 else lod
    out: list[dict[str, Any]] = []
    n = TRAIL_BY_LOD[lod]
    for k in range(n):
        rr = math.sqrt((k + 0.5) / n) * 0.84
        th = k * GOLD + 0.4
        o = (0.0, math.sin(th), math.cos(th))
        b = (0.0, math.cos(th), -math.sin(th))
        root = (
            COLLAR_X - 0.02,
            0.02 + COLLAR_RY * rr * math.sin(th),
            COLLAR_RZ * rr * math.cos(th),
        )
        length = TRAIL_LEN * (0.86 + 0.28 * _hsh(k, 1))
        out.append({
            "kind": 0.0, "slot": k, "root": root, "o": o, "b": b, "rr": rr,
            "L": length, "r0": R0, "r1": R1, "phi": k * GOLD,
            "clawLen": CLAW_LEN[0], "clawR": CLAW_TIP_R[0],
            "side": 0.0, "big": 0.0, "role": 0.0, "roleSign": 0.0,
            "uc": 0.55, "turns": 1.0, "leadLen": 0.0,
        })
    trails = out[:]
    for sgn in (1.0, -1.0):
        cand = [d for d in trails if d["root"][2] * sgn > 0.02]
        if not cand:
            continue
        low = min(cand, key=lambda d: d["root"][1] - 0.3 * abs(d["root"][2]))
        low["role"] = 1.0
        low["roleSign"] = sgn
        uc, turns, lead = _coil_params(low["root"], sgn, low["L"])
        low["uc"], low["turns"], low["leadLen"] = uc, turns, lead
    for d in sorted(trails, key=lambda d: -d["root"][1])[:4]:
        d["role"] = 2.0
        d["roleSign"] = 1.0 if d["root"][2] >= 0 else -1.0
    for a in range(ARMS_BY_LOD[lod]):
        big = a < 2
        side = 1.0 if a % 2 == 0 else -1.0
        root = ARM_ROOTS[a]
        length = ARM_LEN[0 if big else 1]
        r0, r1 = ARM_R[0 if big else 1]
        out.append({
            "kind": 1.0, "slot": n + a, "root": root, "o": (0.0, 0.0, side),
            "b": (0.0, 1.0, 0.0), "rr": 0.0, "L": length, "r0": r0, "r1": r1,
            "phi": a * 1.3, "clawLen": CLAW_LEN[1 if big else 2],
            "clawR": CLAW_TIP_R[1 if big else 2], "side": side,
            "big": 1.0 if big else 0.0, "role": 0.0, "roleSign": 0.0,
            "uc": 0.55, "turns": 1.0, "leadLen": 0.0,
        })
    return out


def pack_strand_tex() -> array.array:
    """6 x 64 RGBA32F; row = lod * 20 + slot."""
    buf = array.array("f", [0.0] * (STRAND_TEX_WIDTH * STRAND_TEX_ROWS * 4))
    for lod in (0, 1, 2):
        for sd in strand_table(lod):
            row = lod * 20 + int(sd["slot"])
            if row < 0 or row >= STRAND_TEX_ROWS:
                continue
            off = row * STRAND_TEX_WIDTH * 4
            root, o, b = sd["root"], sd["o"], sd["b"]
            vals = [
                root[0], root[1], root[2], sd["L"],
                o[0], o[1], o[2], sd["rr"],
                b[0], b[1], b[2], sd["phi"],
                sd["r0"], sd["r1"], sd["clawLen"], sd["clawR"],
                sd["kind"], sd["side"], sd["big"], sd["role"],
                sd["roleSign"], sd["uc"], sd["turns"], sd["leadLen"],
            ]
            for i, v in enumerate(vals):
                buf[off + i] = float(v)
    return buf


def pack_unit_flat(values) -> array.array:
    """Pack a flat list of up to 128 * 32 floats into the unit texture."""
    buf = array.array("f", [0.0] * (UNIT_TEX_WIDTH * UNIT_TEX_ROWS * 4))
    try:
        n = len(values)
    except TypeError:
        return buf
    n = min(n, UNIT_TEX_ROWS * UNIT_FLOATS)
    for i in range(n):
        try:
            item = values[i]
            if hasattr(item, "toVariant"):
                item = item.toVariant()
            buf[i] = float(item)
        except (TypeError, ValueError):
            buf[i] = 0.0
    return buf


@QmlElement
class OverseerUnitTex(QQuick3DTextureData):
    """8 x 128 RGBA32F unit state table, written from a flat float array."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSize(QSize(UNIT_TEX_WIDTH, UNIT_TEX_ROWS))
        self.setFormat(QQuick3DTextureData.Format.RGBA32F)
        self.setHasTransparency(False)
        self.setTextureData(QByteArray(b"\x00" * (UNIT_TEX_WIDTH * UNIT_TEX_ROWS * 16)))
        self._count = 0

    def _count_get(self) -> int:
        return self._count

    def _count_set(self, n: int) -> None:
        self._count = int(n)

    unitCount = Property(int, _count_get, _count_set)  # noqa: N815

    @Slot(list)
    def refreshFlat(self, values) -> None:
        buf = pack_unit_flat(values)
        self.setTextureData(QByteArray(buf.tobytes()))
        try:
            self._count = min(UNIT_TEX_ROWS, len(values) // UNIT_FLOATS)
        except TypeError:
            self._count = 0

    @Slot(int, result="QVariant")
    def sampleRow(self, row: int):
        raw = bytes(self.textureData())
        r = int(row)
        if r < 0 or r >= UNIT_TEX_ROWS or len(raw) < (r + 1) * UNIT_FLOATS * 4:
            return []
        off = r * UNIT_FLOATS
        return list(array.array("f", raw[off * 4 : (off + UNIT_FLOATS) * 4]))


@QmlElement
class OverseerStrandTex(QQuick3DTextureData):
    """6 x 64 RGBA32F static strand table, built once from strand_table()."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSize(QSize(STRAND_TEX_WIDTH, STRAND_TEX_ROWS))
        self.setFormat(QQuick3DTextureData.Format.RGBA32F)
        self.setHasTransparency(False)
        buf = pack_strand_tex()
        self.setTextureData(QByteArray(buf.tobytes()))
