"""Draw Earth-zone entities on the solar plate. Same sodium chrome."""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QImage,
    QPainter,
    QPen,
    QPolygonF,
    QTransform,
)

from arelis.earth.entity import Entity
from arelis.earth.frames import (
    earth_spin_jd,
    ecef_to_ecliptic,
    ecef_to_lla,
    ecef_vel_to_ecliptic,
    ecliptic_offset_to_ecef,
    enu_axes,
    enu_to_ecef,
    lla_to_ecef,
)
from arelis.earth.lod import (
    EarthView,
    LookBBox,
    chip_layers,
    paint_layers,
    view_from_eye,
)
from arelis.earth.look import describe as look_describe
from arelis.earth.look import has_look
from arelis.earth.runtime import get_earth
from arelis.earth.viewshed import viewshed_points
from arelis.physics.scene import SolarSystem
from arelis.ui.earth_marks import heading_of, paint_mark
from arelis.ui.theme import color

# Decoded rasters. fromData every tile every frame was the city-band hitch.
_TILE_IMAGES: dict[tuple[str, int, int, int], QImage] = {}
_TILE_IMAGE_CAP = 64

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


def earth_chip_items(band: str = "") -> tuple[tuple[str, str], ...]:
    """Band type, live, then only the layers this distance can show."""
    from arelis.earth.catalog import LAYER_BY_ID, LAYERS
    from arelis.earth.copy import band_phrase, live_chip_label

    label = band_phrase(band) if band else "on Earth"
    items = [("band", label), ("live", live_chip_label(on=False))]
    items.append(("grid", "Grid"))
    if band in {"near", "city", ""}:
        items.append(("tiles", "Streets"))
    if band in {"city", ""}:
        items.append(("buildings", "Buildings"))
    wanted = chip_layers(band)
    specs = LAYERS if wanted is None else [LAYER_BY_ID[k] for k in wanted if k in LAYER_BY_ID]
    for spec in specs:
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
    band = ""
    try:
        from arelis.earth.runtime import get_earth as _zone

        z = _zone()
        if z is not None and z.last_view is not None:
            band = z.last_view.band
    except Exception:
        band = ""
    for kind, label in earth_chip_items(band):
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
_FRESH_SCALE: dict[str, float] = {
    "live": 1.0,
    "delayed": 0.88,
    "interpolated": 0.82,
    "dead-reckoned": 0.55,
    "simulated": 0.72,
    "reconstructed": 0.78,
    "stale": 0.32,
    "unavailable": 0.22,
}
_HEADING_LAYERS = frozenset({"flights", "drones", "military", "vessels"})


def _ink(layer: str, *, hot: bool = False, freshness: str = "") -> QColor:
    c = QColor(color(_INK_ROLE.get(layer, "dim")))
    base = 255 if hot else _INK_A.get(layer, 170)
    if not hot:
        base = max(40, int(base * _FRESH_SCALE.get(freshness, 1.0)))
    c.setAlpha(base)
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


def _view_from_panel(
    panel: Any, system: SolarSystem, globe: Any, px_r: float
) -> EarthView:
    pose = getattr(panel, "_earth_cam", None)
    eye_ecef = getattr(pose, "eye", None) if pose is not None else None
    look = getattr(pose, "look", None) if pose is not None else None
    if isinstance(eye_ecef, tuple) and len(eye_ecef) >= 3:
        return view_from_eye(
            eye_ecef,
            px_r=px_r,
            locked=True,
            look_ecef=look if look else None,
        )
    jd = earth_jd(system)
    eye = getattr(panel, "_eye", None)
    if not isinstance(eye, tuple) or len(eye) < 3:
        return EarthView(band="space", px_r=px_r)
    offset = (eye[0] - globe.x, eye[1] - globe.y, eye[2] - globe.z)
    ecef = ecliptic_offset_to_ecef(offset, jd)
    return view_from_eye(ecef, px_r=px_r, locked=False)


def sync_earth_view(panel: Any, system: SolarSystem) -> EarthView | None:
    """Keep LOD/live honest when Cesium owns the planet (no Qt paint_earth)."""
    earth = get_earth()
    if earth is None or not earth.active:
        return None
    globe = system.nbody.find("Earth")
    if globe is None:
        return None
    disc = panel._proj((globe.x, globe.y, globe.z))
    px_r = panel._true_px(globe.radius, disc[2]) if disc is not None else 0.0
    view = _view_from_panel(panel, system, globe, px_r)
    earth.note_view(view)
    earth.tick()
    return view


def _paint_borders(
    painter: QPainter,
    panel: Any,
    system: SolarSystem,
    globe: Any,
    disc: tuple[float, float, float] | None,
    view: EarthView,
) -> None:
    """Country fill, then country and state lines. Landfall — not a feed."""
    from arelis.earth.land import (
        country_fills,
        country_rings,
        ecef_rings,
        ring_boxes,
        state_rings,
    )

    if disc is None:
        return
    jd = earth_jd(system)
    origin = (globe.x, globe.y, globe.z)
    eye_ecef = _eye_ecef(panel, globe, jd)
    fill = QColor(color("text_dim"))
    fill.setAlpha(48)
    country = QColor(color("text_dim"))
    country.setAlpha(150)
    state = QColor(color("dim"))
    state.setAlpha(110)
    step = 4 if view.px_r < 80 else 2 if view.px_r < 200 else 1
    if view.px_r >= 18.0:
        fills = country_fills()
        strokes = country_rings()
        # Albedo already reads land once the disc is large; fills are the
        # expensive screenspace polygons and they hid the texture seam.
        if view.px_r < 80.0:
            _fill_rings(
                painter,
                panel,
                origin,
                jd,
                disc,
                globe.radius,
                _pick_ecef(
                    fills, ecef_rings("fills", fills), ring_boxes("fills", fills),
                    view, eye_ecef,
                ),
                step,
                fill,
            )
        _stroke_rings(
            painter,
            panel,
            origin,
            jd,
            disc,
            globe.radius,
            _pick_ecef(
                strokes,
                ecef_rings("countries", strokes),
                ring_boxes("countries", strokes),
                view,
                eye_ecef,
            ),
            step,
            country,
        )
    # States once the disc is close enough that a province can be a line.
    if view.band in {"near", "city"} or view.px_r >= 180.0 or (
        view.band == "approach" and view.bbox is not None
    ):
        states = state_rings()
        _stroke_rings(
            painter,
            panel,
            origin,
            jd,
            disc,
            globe.radius,
            _pick_ecef(
                states,
                ecef_rings("states", states),
                ring_boxes("states", states),
                view,
                eye_ecef,
            ),
            max(1, step),
            state,
        )


def _eye_ecef(
    panel: Any, globe: Any, jd: float
) -> tuple[float, float, float] | None:
    pose = getattr(panel, "_earth_cam", None)
    if pose is not None and getattr(pose, "eye", None):
        return pose.eye
    eye = getattr(panel, "_eye", None)
    if not isinstance(eye, tuple) or len(eye) < 3:
        return None
    return ecliptic_offset_to_ecef(
        (eye[0] - globe.x, eye[1] - globe.y, eye[2] - globe.z), jd
    )


def _ring_in_look(
    box: LookBBox,
    south: float,
    north: float,
    west: float,
    east: float,
    pad: float = 4.0,
) -> bool:
    if north < box.south - pad or south > box.north + pad:
        return False
    if east - west > 180.0 or box.wraps():
        return True
    return not (east < box.west - pad or west > box.east + pad)


def _on_sphere(
    ecef: tuple[float, float, float], radius: float
) -> tuple[float, float, float]:
    """Land caches unit directions; buildings still arrive in metres."""
    n = math.sqrt(ecef[0] * ecef[0] + ecef[1] * ecef[1] + ecef[2] * ecef[2])
    if n <= 1e-12:
        return ecef
    scale = radius / n
    return (ecef[0] * scale, ecef[1] * scale, ecef[2] * scale)


def _faces_eye(
    ring: list[tuple[float, float, float]],
    eye_ecef: tuple[float, float, float],
) -> bool:
    ex, ey, ez = eye_ecef
    for x, y, z in ring:
        if x * ex + y * ey + z * ez > 0.0:
            return True
    return False


def _pick_ecef(
    rings: list[list[tuple[float, float]]],
    ecef: list[list[tuple[float, float, float]]],
    boxes: list[tuple[float, float, float, float]],
    view: EarthView,
    eye_ecef: tuple[float, float, float] | None,
) -> list[list[tuple[float, float, float]]]:
    out: list[list[tuple[float, float, float]]] = []
    clip = view.bbox if view.band in {"approach", "near", "city"} else None
    for _ring, xyz, box in zip(rings, ecef, boxes, strict=False):
        if not xyz:
            continue
        if clip is not None and not _ring_in_look(clip, *box):
            continue
        if eye_ecef is not None and not _faces_eye(xyz, eye_ecef):
            continue
        out.append(xyz)
    return out


def _ring_polylines(
    panel: Any,
    origin: tuple[float, float, float],
    jd: float,
    disc: tuple[float, float, float],
    radius: float,
    rings: list[list[tuple[float, float, float]]],
    step: int,
) -> list[list[QPointF]]:
    stride = max(1, int(step))
    out: list[list[QPointF]] = []
    for ring in rings:
        pts: list[QPointF] = []
        for ecef in ring[::stride]:
            world = ecef_to_ecliptic(origin, _on_sphere(ecef, radius), jd)
            proj = panel._proj(world)
            if proj is None or proj[2] <= 0:
                if len(pts) >= 2:
                    out.append(pts)
                pts = []
                continue
            if _occulted(proj[0], proj[1], proj[2], disc, radius, panel):
                if len(pts) >= 2:
                    out.append(pts)
                pts = []
                continue
            pts.append(QPointF(proj[0], proj[1]))
        if len(pts) >= 2:
            out.append(pts)
    return out


def _fill_rings(
    painter: QPainter,
    panel: Any,
    origin: tuple[float, float, float],
    jd: float,
    disc: tuple[float, float, float],
    radius: float,
    rings: list[list[tuple[float, float, float]]],
    step: int,
    ink: QColor,
) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(ink)
    for pts in _ring_polylines(panel, origin, jd, disc, radius, rings, step):
        if len(pts) >= 3:
            painter.drawPolygon(QPolygonF(pts))


def _stroke_rings(
    painter: QPainter,
    panel: Any,
    origin: tuple[float, float, float],
    jd: float,
    disc: tuple[float, float, float],
    radius: float,
    rings: list[list[tuple[float, float, float]]],
    step: int,
    ink: QColor,
    width: int = 1,
) -> None:
    painter.setPen(QPen(ink, max(1, int(width))))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for pts in _ring_polylines(panel, origin, jd, disc, radius, rings, step):
        painter.drawPolyline(QPolygonF(pts))


def paint_earth(painter: QPainter, panel: Any, system: SolarSystem) -> None:
    earth = get_earth()
    if earth is None or not earth.active:
        return
    globe = system.nbody.find("Earth")
    if globe is None:
        return
    disc = panel._proj((globe.x, globe.y, globe.z))
    px_r = panel._true_px(globe.radius, disc[2]) if disc is not None else 0.0
    if px_r < 10.0:
        return
    view = sync_earth_view(panel, system)
    if view is None:
        return
    from arelis.earth.tiles import want_ground

    draped = False
    if want_ground(px_r, view.band):
        draped = _paint_ground_tiles(
            painter, panel, system, globe, disc, px_r, view, source="gibs"
        )
    if not draped:
        _paint_borders(painter, panel, system, globe, disc, view)
    if px_r >= 140.0:
        _paint_places(painter, panel, system, globe, disc, view)
    if earth.tiles and (px_r > 160.0 or view.band in {"near", "city"}):
        _paint_ground_tiles(
            painter, panel, system, globe, disc, px_r, view, source="osm"
        )
    if earth.buildings and view.band == "city":
        _paint_buildings(painter, panel, system, globe, disc, view)
    visible = earth.visible()
    wanted = paint_layers(view.band)
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
        ink = _ink(ent.layer, hot=hot, freshness=ent.freshness)
        if ent.layer == "cameras" and px_r > 160:
            _paint_viewshed(painter, panel, system, ent, disc, globe.radius)
        if ent.layer == "radar" and px_r > 160:
            _paint_radar_frame(painter, panel, system, ent, disc, globe.radius)
        ix, iy = int(sx), int(sy)
        mag = ent.meta.get("mag")
        mag_f = float(mag) if isinstance(mag, (int, float)) else None
        heading = None
        if ent.layer in _HEADING_LAYERS:
            heading = _screen_heading(panel, system, ent, ix, iy)
        paint_mark(
            painter,
            float(ix),
            float(iy),
            ent.layer,
            band=view.band,
            heading_deg=heading,
            freshness="" if hot else ent.freshness,
            hot=hot,
            look=ent.layer == "cameras" and has_look(ent.id),
            mag=mag_f,
            ink=ink,
        )
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


def screen_to_lla(
    panel: Any, system: SolarSystem, px: float, py: float
) -> tuple[float, float] | None:
    """Pixel on the Earth disc → geographic lat/lon. None if the ray misses."""
    globe = system.nbody.find("Earth")
    if globe is None:
        return None
    eye = getattr(panel, "_eye", None)
    basis = getattr(panel, "_basis", None)
    if not isinstance(eye, tuple) or basis is None:
        return None
    fx, fy, fz = basis
    w = max(panel.width(), 1)
    h = max(panel.height(), 1)
    fov = panel._fov_y()
    sy = 1.0 / math.tan(fov * 0.5)
    sx = sy / (w / h)
    ndc_x = (float(px) / w) * 2.0 - 1.0
    ndc_y = 1.0 - (float(py) / h) * 2.0
    dx = (ndc_x / sx) * fx[0] + (ndc_y / sy) * fy[0] + fz[0]
    dy = (ndc_x / sx) * fx[1] + (ndc_y / sy) * fy[1] + fz[1]
    dz = (ndc_x / sx) * fx[2] + (ndc_y / sy) * fy[2] + fz[2]
    nl = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
    dx, dy, dz = dx / nl, dy / nl, dz / nl
    ox = eye[0] - globe.x
    oy = eye[1] - globe.y
    oz = eye[2] - globe.z
    r = globe.radius
    b = ox * dx + oy * dy + oz * dz
    c = ox * ox + oy * oy + oz * oz - r * r
    disc = b * b - c
    if disc < 0.0:
        return None
    t = -b - math.sqrt(disc)
    if t <= 0.0:
        t = -b + math.sqrt(disc)
    if t <= 0.0:
        return None
    hit = (ox + dx * t, oy + dy * t, oz + dz * t)
    jd = earth_jd(system)
    ecef = ecliptic_offset_to_ecef(hit, jd)
    lat, lon, _alt = ecef_to_lla(*ecef)
    return lat, lon


def hit_geo(
    panel: Any, system: SolarSystem, px: float, py: float
) -> dict[str, Any] | None:
    """Country or city under the click. Contacts still win in hit_entity."""
    pair = screen_to_lla(panel, system, px, py)
    if pair is None:
        return None
    lat, lon = pair
    from arelis.earth.land import hit_country, nearest_place

    place = nearest_place(lat, lon, max_deg=0.85)
    if place is not None:
        name, plat, plon = place
        return {"kind": "city", "name": name, "lat": plat, "lon": plon}
    name = hit_country(lat, lon)
    if name:
        return {"kind": "country", "name": name, "lat": lat, "lon": lon}
    return {"kind": "earth", "name": "Earth", "lat": lat, "lon": lon}


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


def ride_pose(
    system: SolarSystem, entity: Entity
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
] | None:
    """Eye, look-at, and Earth-radial up for sitting on a contact."""
    world = entity_world(system, entity)
    earth = system.nbody.find("Earth")
    if world is None or earth is None:
        return None
    wx, wy, wz = world
    ex, ey, ez = earth.x, earth.y, earth.z
    dx, dy, dz = wx - ex, wy - ey, wz - ez
    n = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
    ux, uy, uz = dx / n, dy / n, dz / n
    sit = max(40.0, min(250.0, 0.00002 * n))
    eye = (wx + ux * sit, wy + uy * sit, wz + uz * sit)
    jd = earth_jd(system)
    vx, vy, vz = ecef_vel_to_ecliptic((entity.vx, entity.vy, entity.vz), jd)
    speed = math.sqrt(vx * vx + vy * vy + vz * vz)
    if speed >= 0.5:
        look = (wx + vx, wy + vy, wz + vz)
    else:
        look = (ex, ey, ez)
    return (eye, look, (ux, uy, uz))


def look_from_pose(
    system: SolarSystem, entity: Entity
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
] | None:
    """Stand in the published frustum. Eye at the pin, look along heading."""
    heading = entity.meta.get("heading_deg")
    lat = entity.meta.get("lat")
    lon = entity.meta.get("lon")
    if heading is None or lat is None or lon is None:
        return None
    try:
        heading_f = float(heading)
        lat_f = float(lat)
        lon_f = float(lon)
        range_m = float(entity.meta.get("range_m") or 200.0)
    except (TypeError, ValueError):
        return None
    earth = system.nbody.find("Earth")
    if earth is None:
        return None
    alt_m = 12.0
    eye_ecef = lla_to_ecef(lat_f, lon_f, alt_m)
    dist = max(40.0, min(range_m, 400.0) * 0.55)
    rad = math.radians(heading_f)
    look_ecef = enu_to_ecef(
        lat_f,
        lon_f,
        math.sin(rad) * dist,
        math.cos(rad) * dist,
        -2.0,
        alt_m=alt_m,
    )
    _east, _north, up_ecef = enu_axes(lat_f, lon_f)
    jd = earth_jd(system)
    origin = (earth.x, earth.y, earth.z)
    eye = ecef_to_ecliptic(origin, eye_ecef, jd)
    look = ecef_to_ecliptic(origin, look_ecef, jd)
    up = ecef_vel_to_ecliptic(up_ecef, jd)
    n = math.sqrt(up[0] * up[0] + up[1] * up[1] + up[2] * up[2]) or 1.0
    return (eye, look, (up[0] / n, up[1] / n, up[2] / n))


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
    bits = [f"{lat:.2f}°, {lon:.2f}°", f"{alt/1000.0:.0f} km"]
    spd = entity.speed()
    if spd >= 0.5:
        bits.append(f"{spd:.0f} m/s")
    mag = entity.meta.get("mag")
    if isinstance(mag, (int, float)):
        bits.append(f"M{float(mag):.1f}")
    from arelis.earth.copy import inspect_kind_line

    lines = [
        entity.label,
        inspect_kind_line(entity.layer, entity.freshness),
        f"{entity.id}  {entity.layer}  {entity.freshness}",
    ]
    if entity.source:
        lines.append(entity.source)
    lines.append("  ".join(bits))
    if entity.cite:
        lines.append(entity.cite)
    if entity.coverage is not None:
        lines.append(f"{entity.coverage.kind}: {entity.coverage.note}")
    look_line = look_describe(entity.id, layer=entity.layer)
    if look_line:
        lines.append(look_line)
    return "\n".join(lines)


def _screen_heading(
    panel: Any,
    system: SolarSystem,
    entity: Entity,
    ix: int,
    iy: int,
) -> float | None:
    """Screen degrees clockwise from up so the air/sea nose is the track."""
    speed = entity.speed()
    if speed < 0.5:
        return heading_of(entity)
    scale = 40_000.0 / speed
    tip = Entity(
        id=entity.id,
        cls=entity.cls,
        layer=entity.layer,
        label=entity.label,
        x=entity.x + entity.vx * scale,
        y=entity.y + entity.vy * scale,
        z=entity.z + entity.vz * scale,
    )
    world = entity_world(system, tip)
    if world is None:
        return heading_of(entity)
    proj = panel._proj(world)
    if proj is None or proj[2] <= 0:
        return heading_of(entity)
    return math.degrees(math.atan2(proj[0] - ix, iy - proj[1]))


def _paint_places(
    painter: QPainter,
    panel: Any,
    system: SolarSystem,
    globe: Any,
    disc: tuple[float, float, float] | None,
    view: EarthView,
) -> None:
    from arelis.earth.land import places, places_dense

    if disc is None:
        return
    found = places_dense() if view.band in {"near", "city"} else places()
    if not found:
        return
    jd = earth_jd(system)
    origin = (globe.x, globe.y, globe.z)
    radius = globe.radius
    selected = getattr(panel, "_place", None)
    sel_name = selected.get("name") if isinstance(selected, dict) else ""
    cap = 12 if view.band == "space" else 24 if view.band == "approach" else 48
    ranked = sorted(
        found,
        key=lambda row: (row[1] - view.lat) ** 2
        + (((row[2] - view.lon + 180.0) % 360.0) - 180.0) ** 2,
    )
    painter.setPen(color("text_dim"))
    n = 0
    for name, lat, lon in ranked:
        ecef = lla_to_ecef(lat, lon, 0.0)
        world = ecef_to_ecliptic(origin, _on_sphere(ecef, radius), jd)
        proj = panel._proj(world)
        if proj is None or proj[2] <= 0:
            continue
        if _occulted(proj[0], proj[1], proj[2], disc, radius, panel):
            continue
        if n >= cap and name != sel_name:
            continue
        n += 1
        ix, iy = int(proj[0]), int(proj[1])
        hot = name == sel_name
        painter.setPen(color("text") if hot else color("text_dim"))
        painter.drawText(ix + 5, iy - 2, name)


def _tile_image(
    source: str, z: Any, x: Any, y: Any, blob: bytes | bytearray
) -> QImage | None:
    try:
        key = (str(source), int(z), int(x), int(y))
    except (TypeError, ValueError):
        image = QImage.fromData(blob)
        return None if image.isNull() else image
    hit = _TILE_IMAGES.get(key)
    if hit is not None:
        return hit
    image = QImage.fromData(blob)
    if image.isNull():
        return None
    if len(_TILE_IMAGES) >= _TILE_IMAGE_CAP:
        _TILE_IMAGES.clear()
    _TILE_IMAGES[key] = image
    return image


def _paint_ground_tiles(
    painter: QPainter,
    panel: Any,
    system: SolarSystem,
    globe: Any,
    disc: tuple[float, float, float] | None,
    px_r: float,
    view: EarthView,
    *,
    source: str,
) -> bool:
    """Drape XYZ tiles with a real quad. Returns True if any tile drew."""
    from arelis.earth.tiles import tiles_for_view, zoom_for_disc, zoom_for_ground

    if disc is None:
        return False
    jd = earth_jd(system)
    if source == "gibs":
        zoom = zoom_for_ground(px_r, view.band)
        radius = 1 if zoom >= 6 else 2
        opacity = 0.92
    else:
        zoom = zoom_for_disc(px_r, view.band)
        radius = 1 if px_r < 520.0 or zoom >= 14 else 2
        opacity = 0.70
    drew = False
    for tile in tiles_for_view(
        view.lat, view.lon, zoom, radius=radius, source=source  # type: ignore[arg-type]
    ):
        blob = tile.get("png")
        corners = tile.get("corners")
        if not isinstance(blob, (bytes, bytearray)) or not isinstance(corners, list):
            continue
        image = _tile_image(source, tile.get("z"), tile.get("x"), tile.get("y"), blob)
        if image is None:
            continue
        screen: list[QPointF] = []
        for pair in corners:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                screen = []
                break
            ecef_c = lla_to_ecef(float(pair[0]), float(pair[1]), 0.0)
            world = ecef_to_ecliptic((globe.x, globe.y, globe.z), ecef_c, jd)
            proj = panel._proj(world)
            if proj is None or proj[2] <= 0:
                screen = []
                break
            if _occulted(proj[0], proj[1], proj[2], disc, globe.radius, panel):
                screen = []
                break
            screen.append(QPointF(proj[0], proj[1]))
        if len(screen) != 4:
            continue
        src = QPolygonF(
            [
                QPointF(0.0, 0.0),
                QPointF(float(image.width()), 0.0),
                QPointF(float(image.width()), float(image.height())),
                QPointF(0.0, float(image.height())),
            ]
        )
        dst = QPolygonF(screen)
        xform = QTransform()
        if not QTransform.quadToQuad(src, dst, xform):
            continue
        painter.save()
        painter.setTransform(xform, True)
        painter.setOpacity(opacity)
        painter.drawImage(QRectF(0.0, 0.0, float(image.width()), float(image.height())), image)
        painter.restore()
        painter.setOpacity(1.0)
        drew = True
    return drew


def _paint_buildings(
    painter: QPainter,
    panel: Any,
    system: SolarSystem,
    globe: Any,
    disc: tuple[float, float, float] | None,
    view: EarthView,
) -> None:
    """City-band footprints. Birds-eye only. No house labels."""
    from arelis.earth.buildings import footprints_for_view

    if disc is None:
        return
    rings = footprints_for_view(view.lat, view.lon, view.band)
    if not rings:
        return
    jd = earth_jd(system)
    origin = (globe.x, globe.y, globe.z)
    ink = QColor(color("dim"))
    ink.setAlpha(200)
    xyz = [[lla_to_ecef(lat, lon, 0.0) for lat, lon in ring] for ring in rings]
    _stroke_rings(painter, panel, origin, jd, disc, globe.radius, xyz, 1, ink, width=2)


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
