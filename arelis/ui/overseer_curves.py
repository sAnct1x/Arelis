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
