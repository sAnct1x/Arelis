"""Draw Earth-zone entities on the solar plate. Same sodium chrome."""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPen, QPolygonF

from arelis.earth.entity import Entity
from arelis.earth.frames import (
    earth_spin_jd,
    ecef_to_ecliptic,
    ecef_to_lla,
    ecliptic_offset_to_ecef,
    lla_to_ecef,
)
from arelis.earth.runtime import get_earth
from arelis.earth.viewshed import viewshed_points
from arelis.physics.scene import SolarSystem
from arelis.ui.theme import color

# Theme sodium, not harvest gold. Hue lock is #ff7a22; gold was the yellow wash.
_INK_ROLE: dict[str, str] = {
    "flights": "amber",
    "drones": "warn",
    "military": "warn",
    "vessels": "accent2",
    "radar": "hint",
    "satellites": "hint",
    "iss": "text",
    "quakes": "warn",
    "fires": "warn",
    "weather": "accent2",
    "radio": "text_dim",
    "cameras": "amber",
    "traffic": "dim",
    "sites": "dim",
    "people": "text",
}
_CHIP_SHORT: dict[str, str] = {
    "military": "Military",
    "satellites": "Sats",
    "quakes": "Quakes",
}
_CHIP_H = 22
_CHIP_GAP = 4
_CHIP_PAD = 8


def earth_chip_items() -> tuple[tuple[str, str], ...]:
    """Click targets: live, optional tiles, then every catalog layer."""
    from arelis.earth.catalog import LAYERS

    items = [("live", "Live"), ("tiles", "Tiles")]
    for spec in LAYERS:
        items.append((spec.id, _CHIP_SHORT.get(spec.id, spec.title)))
    return tuple(items)


def layout_earth_chips(
    fm: QFontMetrics, left: int, top: int, width: int
) -> tuple[list[tuple[str, QRect]], QRect]:
    """Wrap sodium chips under the HUD. Same plate width as status."""
    inner_left = left + _CHIP_PAD
    inner_right = left + width - _CHIP_PAD
    x = inner_left
    y = top + _CHIP_PAD
    hits: list[tuple[str, QRect]] = []
    for kind, label in earth_chip_items():
        w = fm.horizontalAdvance(label) + 16
        if x > inner_left and x + w > inner_right:
            x = inner_left
            y += _CHIP_H + _CHIP_GAP
        hits.append((kind, QRect(x, y, w, _CHIP_H)))
        x += w + _CHIP_GAP
    bottom = y + _CHIP_H + _CHIP_PAD
    return hits, QRect(left, top, width, max(_CHIP_H + 2 * _CHIP_PAD, bottom - top))


_INK_A: dict[str, int] = {
    "flights": 210,
    "drones": 220,
    "military": 230,
    "vessels": 190,
    "radar": 200,
    "satellites": 150,
    "iss": 255,
    "quakes": 210,
    "fires": 220,
    "weather": 190,
    "radio": 180,
    "cameras": 220,
    "traffic": 110,
    "sites": 170,
    "people": 240,
}


def _ink(layer: str, *, hot: bool = False) -> QColor:
    c = QColor(color(_INK_ROLE.get(layer, "dim")))
    c.setAlpha(255 if hot else _INK_A.get(layer, 170))
    return c


def earth_jd(system: SolarSystem) -> float:
    return earth_spin_jd(system.epoch_jd, system.t)


def entity_world(
    system: SolarSystem, entity: Entity
) -> tuple[float, float, float] | None:
    earth = system.nbody.find("Earth")
    if earth is None:
        return None
    jd = earth_jd(system)
    return ecef_to_ecliptic(
        (earth.x, earth.y, earth.z), (entity.x, entity.y, entity.z), jd
    )


def paint_earth(painter: QPainter, panel: Any, system: SolarSystem) -> None:
    earth = get_earth()
    if earth is None or not earth.active:
        return
    earth.tick()
    globe = system.nbody.find("Earth")
    if globe is None:
        return
    disc = panel._proj((globe.x, globe.y, globe.z))
    px_r = panel._true_px(globe.radius, disc[2]) if disc is not None else 0.0
    if px_r < 10.0:
        return
    if earth.tiles and px_r > 220.0:
        _paint_osm_tiles(painter, panel, system, globe, disc, px_r)
    visible = earth.visible()
    if px_r < 28.0:
        wanted = {"iss"}
    elif px_r < 72.0:
        wanted = {"iss", "satellites"}
    else:
        wanted = {e.layer for e in visible}
        if px_r < 220.0:
            wanted.discard("traffic")
    track = earth.track_id
    ride = earth.ride_id
    n_cam = sum(1 for e in visible if e.layer == "cameras")
    label_cams = n_cam <= 12
    ordered = sorted(
        visible,
        key=lambda e: (e.layer == "iss", e.id in {track, ride}),
    )
    for ent in ordered:
        if ent.layer not in wanted:
            continue
        world = entity_world(system, ent)
        if world is None:
            continue
        proj = panel._proj(world)
        if proj is None:
            continue
        sx, sy, depth = proj
        if depth <= 0:
            continue
        if disc is not None and _occulted(sx, sy, depth, disc, globe.radius, panel):
            continue
        hot = ent.id in {track, ride}
        ink = _ink(ent.layer, hot=hot)
        if ent.layer == "cameras" and px_r > 160:
            _paint_viewshed(painter, panel, system, ent, disc, globe.radius)
        if ent.layer == "radar" and px_r > 160:
            _paint_radar_frame(painter, panel, system, ent, disc, globe.radius)
        ix, iy = int(sx), int(sy)
        if ent.layer == "iss":
            ring = QColor(color("amber"))
            ring.setAlpha(220)
            painter.setPen(QPen(ring, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPoint(ix, iy), 7, 7)
            painter.setBrush(ink)
            painter.setPen(QPen(ink, 1))
            painter.drawEllipse(QPoint(ix, iy), 3, 3)
        elif ent.layer == "cameras":
            painter.setPen(QPen(ink, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(ix - 2, iy - 2, 5, 5)
        elif ent.layer == "drones":
            painter.setPen(QPen(ink, 1))
            painter.setBrush(ink)
            painter.drawEllipse(QPoint(ix, iy), 2, 2)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(ix - 3, iy - 3, 7, 7)
        elif ent.layer == "people":
            painter.setPen(QPen(ink, 1))
            painter.setBrush(ink)
            painter.drawEllipse(QPoint(ix, iy), 3, 3)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPoint(ix, iy), 6, 6)
        elif ent.layer == "radar":
            painter.setPen(QPen(ink, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            diamond = QPolygonF(
                [
                    QPointF(ix, iy - 4),
                    QPointF(ix + 4, iy),
                    QPointF(ix, iy + 4),
                    QPointF(ix - 4, iy),
                ]
            )
            painter.drawPolygon(diamond)
        elif ent.layer == "quakes":
            painter.setPen(QPen(ink, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            mag = float(ent.meta.get("mag") or 3.0)
            rad = max(3, min(10, int(mag)))
            painter.drawEllipse(QPoint(ix, iy), rad, rad)
        elif ent.layer == "fires":
            painter.setPen(QPen(ink, 1))
            painter.setBrush(ink)
            painter.drawEllipse(QPoint(ix, iy), 2, 2)
        else:
            r = 3 if hot else 2
            painter.setPen(QPen(ink, 1))
            painter.setBrush(ink)
            painter.drawEllipse(QPoint(ix, iy), r, r)
        if hot:
            halo = QColor(color("amber"))
            halo.setAlpha(180)
            painter.setPen(QPen(halo, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPoint(ix, iy), 9, 9)
        show_cam = ent.layer == "cameras" and (hot or label_cams)
        show_people = ent.layer == "people"
        if hot or ent.layer == "iss" or show_people or (
            px_r > 160 and (ent.layer == "radio" or show_cam or ent.layer == "radar")
        ):
            painter.setPen(color("text") if hot or ent.layer == "iss" else color("text_dim"))
            painter.drawText(ix + 8, iy - 4, ent.label)


def hit_entity(
    panel: Any, system: SolarSystem, px: float, py: float
) -> Entity | None:
    earth = get_earth()
    if earth is None or not earth.active:
        return None
    best: Entity | None = None
    best_d = 14.0
    for ent in earth.visible():
        world = entity_world(system, ent)
        if world is None:
            continue
        proj = panel._proj(world)
        if proj is None or proj[2] <= 0:
            continue
        d = math.hypot(proj[0] - px, proj[1] - py)
        if d < best_d:
            best_d = d
            best = ent
    return best


def ride_eye(
    system: SolarSystem, entity: Entity
) -> tuple[float, float, float] | None:
    """Camera a few radii behind the contact, looking at Earth."""
    world = entity_world(system, entity)
    earth = system.nbody.find("Earth")
    if world is None or earth is None:
        return None
    wx, wy, wz = world
    ex, ey, ez = earth.x, earth.y, earth.z
    dx, dy, dz = wx - ex, wy - ey, wz - ez
    n = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
    standoff = max(80_000.0, 0.08 * n)
    return (wx + dx / n * standoff, wy + dy / n * standoff, wz + dz / n * standoff)


def _occulted(
    sx: float,
    sy: float,
    depth: float,
    disc: tuple[float, float, float],
    radius: float,
    panel: Any,
) -> bool:
    """Hide points on the far side of the globe."""
    dx, dy = sx - disc[0], sy - disc[1]
    pr = panel._true_px(radius, disc[2])
    if math.hypot(dx, dy) > pr:
        return False
    return depth > disc[2] + radius * 0.15


def inspect_caption(entity: Entity) -> str:
    lat, lon, alt = ecef_to_lla(entity.x, entity.y, entity.z)
    extra = ""
    if entity.coverage is not None:
        extra = f"\n{entity.coverage.kind}: {entity.coverage.note}"
    return (
        f"{entity.label}\n"
        f"{entity.id}  {entity.layer}  {entity.freshness}\n"
        f"{lat:.2f}°, {lon:.2f}°  {alt/1000.0:.0f} km\n"
        f"{entity.cite}{extra}"
    )


def _paint_osm_tiles(
    painter: QPainter,
    panel: Any,
    system: SolarSystem,
    globe: Any,
    disc: tuple[float, float, float] | None,
    px_r: float,
) -> None:
    from arelis.earth.tiles import tiles_for_view, zoom_for_disc

    eye = getattr(panel, "_eye", None)
    if not isinstance(eye, tuple) or len(eye) < 3 or disc is None:
        return
    jd = earth_jd(system)
    offset = (eye[0] - globe.x, eye[1] - globe.y, eye[2] - globe.z)
    ecef = ecliptic_offset_to_ecef(offset, jd)
    lat, lon, _alt = ecef_to_lla(ecef[0], ecef[1], ecef[2])
    zoom = zoom_for_disc(px_r)
    radius = 1 if px_r < 520.0 else 2
    for tile in tiles_for_view(lat, lon, zoom, radius=radius):
        png = tile.get("png")
        corners = tile.get("corners")
        if not isinstance(png, (bytes, bytearray)) or not isinstance(corners, list):
            continue
        image = QImage.fromData(png)
        if image.isNull():
            continue
        screen: list[QPointF] = []
        for pair in corners:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            ecef_c = lla_to_ecef(float(pair[0]), float(pair[1]), 0.0)
            world = ecef_to_ecliptic((globe.x, globe.y, globe.z), ecef_c, jd)
            proj = panel._proj(world)
            if proj is None or proj[2] <= 0:
                screen = []
                break
            if _occulted(proj[0], proj[1], proj[2], disc, globe.radius, panel):
                continue
            screen.append(QPointF(proj[0], proj[1]))
        if len(screen) < 3:
            continue
        xs = [p.x() for p in screen]
        ys = [p.y() for p in screen]
        w = max(4.0, max(xs) - min(xs))
        h = max(4.0, max(ys) - min(ys))
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        target = QRect(int(cx - w / 2), int(cy - h / 2), int(w), int(h))
        painter.setOpacity(0.55)
        painter.drawImage(target, image)
        painter.setOpacity(1.0)


def _paint_viewshed(
    painter: QPainter,
    panel: Any,
    system: SolarSystem,
    entity: Entity,
    disc: tuple[float, float, float] | None,
    radius: float,
) -> None:
    pts = viewshed_points(entity)
    if len(pts) < 3:
        return
    globe = system.nbody.find("Earth")
    if globe is None:
        return
    jd = earth_jd(system)
    origin = (globe.x, globe.y, globe.z)
    screen: list[QPointF] = []
    for ecef in pts:
        world = ecef_to_ecliptic(origin, ecef, jd)
        proj = panel._proj(world)
        if proj is None or proj[2] <= 0:
            return
        if disc is not None and _occulted(proj[0], proj[1], proj[2], disc, radius, panel):
            continue
        screen.append(QPointF(proj[0], proj[1]))
    if len(screen) < 3:
        return
    fill = QColor(color("amber"))
    fill.setAlpha(32)
    edge = QColor(color("amber"))
    edge.setAlpha(110)
    painter.setBrush(fill)
    painter.setPen(QPen(edge, 1))
    painter.drawPolygon(QPolygonF(screen))


def _paint_radar_frame(
    painter: QPainter,
    panel: Any,
    system: SolarSystem,
    entity: Entity,
    disc: tuple[float, float, float] | None,
    radius: float,
) -> None:
    ring = entity.meta.get("footprint_ll")
    if not isinstance(ring, list) or len(ring) < 3:
        return
    globe = system.nbody.find("Earth")
    if globe is None:
        return
    jd = earth_jd(system)
    origin = (globe.x, globe.y, globe.z)
    screen: list[QPointF] = []
    for pair in ring:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        try:
            lat = float(pair[0])
            lon = float(pair[1])
        except (TypeError, ValueError):
            continue
        ecef = lla_to_ecef(lat, lon, 0.0)
        world = ecef_to_ecliptic(origin, ecef, jd)
        proj = panel._proj(world)
        if proj is None or proj[2] <= 0:
            return
        if disc is not None and _occulted(proj[0], proj[1], proj[2], disc, radius, panel):
            continue
        screen.append(QPointF(proj[0], proj[1]))
    if len(screen) < 3:
        return
    fill = QColor(color("hint"))
    fill.setAlpha(28)
    edge = QColor(color("hint"))
    edge.setAlpha(120)
    painter.setBrush(fill)
    painter.setPen(QPen(edge, 1))
    painter.drawPolygon(QPolygonF(screen))
