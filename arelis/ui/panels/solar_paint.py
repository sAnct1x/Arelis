"""Software overlay, HUD, and tools chrome. SolarPanel methods stay as delegates."""

from __future__ import annotations

import math
import os
import threading
import time
from itertools import pairwise

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
)

from arelis.physics.attitude import (
    body_frame_ecliptic,
    earth_lonlat_grid,
    lonlat_from_frame,
    moon_lonlat_grid,
    saturn_ring_axes,
    spin_caption,
    spin_jd,
)
from arelis.physics.camera import (
    speed_label,
)
from arelis.physics.clocks import (
    TT_MINUS_UTC_S,
    jd_iso,
    rate_label,
)
from arelis.physics.collision import stop_radius_m
from arelis.physics.constants import (
    AU_M,
    BODY_BY_NAME,
    DAY_S,
    G_SI,
    SATURN_CASSINI_INNER_M,
    SATURN_CASSINI_OUTER_M,
    SATURN_RING_INNER_M,
    SATURN_RING_OUTER_M,
)
from arelis.physics.elements import (
    BEAD_LAP_S,
    ISO_G_FACTORS,
    bead_true_anomalies,
    hill_radius,
    osculating,
    position_at_true_anomaly,
    well_grid,
    well_inner_ring,
    well_theta_count,
)
from arelis.physics.evolution import GYR_MAX, GYR_MIN, sample, sun_rgb
from arelis.physics.maps import describe
from arelis.physics.runtime import get_system
from arelis.physics.scene import BodyView, SolarSystem
from arelis.ui.earth_overlay import (
    earth_chip_items,
    layout_earth_chips,
    paint_earth,
)
from arelis.ui.panels.solar_const import (
    _CLOSE_GLOBE_PX,
    _FILL,
    _HUD_GAP,
    _HUD_LANE,
    _HUD_MAX_W,
    _HUD_MIN_W,
    _KEYS_ROW,
    _LEGEND_BLOCK,
    _LEGEND_ROW,
    _TINT,
    KEY_HINT,
    KEY_HINT_EARTH,
    KEY_LEGEND,
    SOLAR_OVERLAY,
    SOLAR_SPAWN,
    _albedo,
    _Basis,
    _fmt_m,
    _globe,
    _is_sketch,
    _on_frame,
    _sphere_axes,
    _wash,
    _world_normals,
    globe_cap,
)
from arelis.ui.theme import FONT_PX, color


def _earth_zone_fill(body: BodyView) -> float:
    """Night-side land must still read once Earth is the subject."""
    if body.kind == "asteroid":
        return 0.05
    if body.name == "Earth":
        try:
            from arelis.earth.runtime import get_earth

            zone = get_earth()
            if zone is not None and zone.active:
                return 0.75
        except Exception:
            pass
    return _FILL


def paint_overlay(panel, painter: QPainter, *, software: bool, chrome_only: bool = False) -> None:
    t0 = time.perf_counter()
    system = get_system()
    if system is None:
        panel._fitted_lock = None
        painter.setPen(color("text_dim"))
        painter.drawText(
            panel.rect().adjusted(24, 48, -24, -120),
            Qt.AlignmentFlag.AlignCenter,
            panel._empty_caption(),
        )
        plate_w = panel._hud_plate_width()
        used = panel._paint_keys_chrome(
            painter, QRect(10, 8, plate_w, 280)
        )
        panel._hud_box = QRect(10, 8, plate_w, used)
        panel._hud_bottom = panel._hud_box.bottom()
        panel._paint_tools(painter)
        panel._paint_confirm(painter)
        return
    if id(system) != panel._view_id:
        panel._view_id = id(system)
        if system.ic_date:
            panel._ic_date = system.ic_date
        if chrome_only:
            pass
        elif software:
            panel.reset_view()
        elif not panel._reset_pending:
            panel._reset_pending = True
            QTimer.singleShot(0, panel._reset_after_paint)
    panel._begin_view(system)
    sun = system.nbody.find("Sun")
    dist_sun = 0.0
    if sun is not None:
        dist_sun = math.hypot(
            panel._eye[0] - sun.x, panel._eye[1] - sun.y, panel._eye[2] - sun.z
        )
    shots: list[tuple[float, BodyView, tuple[float, float, float] | None]] = []
    for body in system.views():
        if not software and body.tracer:
            continue
        proj = panel._proj((body.x, body.y, body.z))
        shots.append((-(proj[2] if proj else 0.0), body, proj))
    shots.sort(key=lambda row: row[0])
    panel._drawn_labels = []
    panel._cover = None
    if panel._inspect:
        for _depth, body, proj in shots:
            if body.name == panel._inspect and proj is not None:
                panel._cover = (
                    proj[0],
                    proj[1],
                    panel._true_px(body.radius, proj[2]),
                )
                break
    if software and not chrome_only:
        if sun is not None and dist_sun > 0.25 * AU_M:
            panel._paint_ecliptic(painter, sun)
        if system.show_trails:
            panel._paint_trails(painter, system)
        if system.show_lagrange:
            panel._paint_lagrange(painter, system)
        if system.show_osculating:
            panel._paint_heliocentric_orbits(painter, system)
    for _depth, body, proj in shots:
        if chrome_only:
            continue
        if body.tracer:
            if software:
                panel._paint_body(painter, system, body, sun, panel._basis, proj)
            continue
        if _is_sketch(body):
            continue
        if software:
            panel._paint_body(painter, system, body, sun, panel._basis, proj)
        elif proj is not None:
            sx, sy, depth = proj
            px_r = panel._screen_radius(body, depth)
            panel._label_body(painter, body, sx, sy, px_r)
    if not chrome_only and system.overlay.show_gravity:
        panel._paint_wells(painter, system, strokes=software)
        panel._paint_g(painter, system)
    if not chrome_only and system.overlay.show_magnetic:
        panel._paint_magnetopause(painter, system, strokes=software)
    if not chrome_only and system.overlay.show_wind:
        panel._paint_wind(painter, system)
    if not chrome_only and system.overlay.show_grid:
        panel._paint_grid(painter, system)
    if software and not chrome_only and sun is not None:
        sp = panel._proj((sun.x, sun.y, sun.z))
        if sp is not None:
            panel._sun_limb(
                painter, sp[0], sp[1], panel._true_px(sun.radius, sp[2])
            )
    panel._paint_free_markers(painter, system)
    if getattr(panel, "_earth_globe_live", lambda: False)():
        from arelis.ui.earth_overlay import sync_earth_view

        sync_earth_view(panel, system)
    else:
        paint_earth(painter, panel, system)
    panel._paint_hud(painter, system)
    panel._paint_earth_toggles(painter)
    panel._paint_earth_card(painter)
    panel._paint_roster(painter, system)
    panel._paint_inspect(painter, system)
    panel._paint_speed(painter)
    panel._paint_epoch(painter, system)
    panel._paint_tools(painter)
    panel._paint_confirm(painter)
    try:
        from arelis.earth.runtime import get_earth
        from arelis.physics.telemetry import sample as reality_sample

        zone = get_earth()
        band = ""
        n = 0
        live = False
        if zone is not None and zone.active:
            live = zone.live
            n = len(zone.visible())
            if zone.last_view is not None:
                band = zone.last_view.band
        reality_sample(
            "paint",
            ms=int((time.perf_counter() - t0) * 1000),
            software=software,
            body=str(getattr(system, "lock", "") or ""),
            earth=zone is not None and zone.active,
            band=band,
            live=live,
            n=n,
        )
    except Exception:
        pass


def light_cam(
    panel,
    body: BodyView,
    sun,
    basis: _Basis,
) -> tuple[float, float, float]:
    fx, fy, fz = basis
    if sun is None or body.name == "Sun":
        return (0.2, 0.3, 1.0)
    lx, ly, lz = sun.x - body.x, sun.y - body.y, sun.z - body.z
    return (
        lx * fx[0] + ly * fx[1] + lz * fx[2],
        lx * fy[0] + ly * fy[1] + lz * fy[2],
        -(lx * fz[0] + ly * fz[1] + lz * fz[2]),
    )


def paint_body(
    panel,
    painter: QPainter,
    system: SolarSystem,
    body: BodyView,
    sun,
    basis: _Basis,
    proj: tuple[float, float, float] | None = None,
) -> None:
    if proj is None:
        proj = panel._proj((body.x, body.y, body.z))
    if proj is None:
        return
    sx, sy, depth = proj
    px_r = panel._screen_radius(body, depth)
    if body.tracer:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(180, 180, 190, 80))
        painter.drawEllipse(QPoint(int(sx), int(sy)), 1, 1)
        return
    light = panel._light_cam(body, sun, basis)
    info = describe(body.name)
    alb = _albedo(info.path) if info.path is not None else None
    lon = lat = None
    cap = globe_cap(body.name, px_r)
    size = max(16, min(int(px_r * 2), cap))
    tint = _TINT.get(body.name, (200, 180, 160))
    if body.name == "Sun" and abs(system.future_gyr) > 1e-6:
        tint = sun_rgb(sample(system.future_gyr))
    vis = None
    shine_light = None
    shine = 0.0
    umbra_glow = False
    nx = ny = nz = nwx = nwy = nwz = None
    if px_r >= 4 and body.name != "Sun":
        from arelis.physics.light import earthshine_scale, occluders_for, sun_lit_fraction

        nx, ny, nz = _sphere_axes(size, cap)
        nwx, nwy, nwz = _world_normals(nx, ny, nz, basis)
        occ = occluders_for(
            body.name,
            (body.x, body.y, body.z),
            system.nbody.particles,
            sun,
            parent=body.parent,
        )
        if occ and sun is not None:
            vis = sun_lit_fraction(
                body.x + body.radius * nwx,
                body.y + body.radius * nwy,
                body.z + body.radius * nwz,
                (sun.x, sun.y, sun.z),
                occ,
            )
        if body.name == "Moon" and sun is not None:
            earth = system.nbody.find("Earth")
            if earth is not None:
                umbra_glow = True
                shine = earthshine_scale(
                    (body.x, body.y, body.z),
                    (earth.x, earth.y, earth.z),
                    (sun.x, sun.y, sun.z),
                )
                shine_light = panel._light_cam(body, earth, basis)
    if alb is not None and px_r >= 6:
        if nwx is None:
            nx, ny, nz = _sphere_axes(size, cap)
            nwx, nwy, nwz = _world_normals(nx, ny, nz, basis)
        jd = spin_jd(system.epoch_jd, system.t)
        if body.name == "Earth" and system.epoch_jd > 0.0:
            lon, lat = earth_lonlat_grid(nwx, nwy, nwz, jd)
        elif body.name == "Moon":
            earth = system.nbody.find("Earth")
            if earth is not None:
                lon, lat = moon_lonlat_grid(
                    nwx,
                    nwy,
                    nwz,
                    (body.x, body.y, body.z),
                    (earth.x, earth.y, earth.z),
                )
        else:
            earth = system.nbody.find("Earth")
            moon = system.nbody.find("Moon")
            frame = body_frame_ecliptic(
                body.name,
                jd,
                moon=(moon.x, moon.y, moon.z) if moon is not None else None,
                earth=(earth.x, earth.y, earth.z) if earth is not None else None,
            )
            if frame is not None:
                lon, lat = lonlat_from_frame(nwx, nwy, nwz, frame)
    if px_r >= 4:
        globe = _globe(
            size,
            light,
            albedo=alb if alb is not None and px_r >= 6 else None,
            tint=tint,
            lon=lon,
            lat=lat,
            fill=_earth_zone_fill(body),
            emissive=body.name == "Sun",
            granulate=body.name == "Sun" and px_r >= 32.0,
            vis=vis,
            shine_light=shine_light,
            shine=shine,
            umbra_glow=umbra_glow,
            max_edge=cap,
        )
        painter.drawImage(
            QRect(
                int(sx - px_r),
                int(sy - px_r),
                int(px_r * 2),
                int(px_r * 2),
            ),
            globe,
        )
        if body.name == "Earth" and px_r >= 12:
            panel._earth_limb(painter, sx, sy, px_r)
        if body.name == "Sun":
            if px_r >= 8 and system.overlay.show_magnetic:
                panel._paint_sun_loops(painter, system, body)
        if body.name == "Saturn" and px_r >= 8:
            panel._paint_saturn_rings(painter, body)
    else:
        from arelis.physics.light import occluders_for, sun_lit_at

        frac = 1.0
        if body.name != "Sun" and sun is not None:
            occ = occluders_for(
                body.name,
                (body.x, body.y, body.z),
                system.nbody.particles,
                sun,
                parent=body.parent,
            )
            if occ:
                frac = sun_lit_at(
                    (body.x, body.y, body.z),
                    (sun.x, sun.y, sun.z),
                    occ,
                )
        dim = 0.06 + 0.94 * frac
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(
            QColor(int(tint[0] * dim), int(tint[1] * dim), int(tint[2] * dim))
        )
        painter.drawEllipse(QPoint(int(sx), int(sy)), max(1, int(px_r)), max(1, int(px_r)))
    panel._label_body(painter, body, sx, sy, px_r)


def chrome_rects(panel) -> list[QRect]:
    """Panel boxes a label must dodge, rebuilt only when the chrome changes.

    Six candidate positions per body times every visible body used to
    re-sort the roster and re-derive the inspect tile for each probe.
    """
    system = get_system()
    key = (
        panel.width(),
        panel.height(),
        panel._hud_bottom,
        panel._inspect or "",
        panel._roster_scroll,
        panel._help,
        panel._tools_open,
        bool(panel._earth_chip_box.isEmpty()),
        bool(getattr(panel, "_earth_card_box", QRect()).isEmpty()),
        bool(getattr(panel, "_earth_find_box", QRect()).isEmpty()),
        bool(getattr(panel, "_earth_coach_box", QRect()).isEmpty()),
        bool(getattr(panel, "_earth_key_box", QRect()).isEmpty()),
        panel._earth_id or "",
        str(panel._confirm.get("kind") or "") if panel._confirm else "",
        id(system),
        0 if system is None else len(system.nbody.particles),
        bool(system is not None and system.show_graphs),
    )
    if key == panel._chrome_key and panel._chrome_cache is not None:
        return panel._chrome_cache
    boxes = [
        panel._hud_plate_rect(),
        panel._roster_rect(),
        panel._speed_rect(),
        panel._epoch_rect(),
    ]
    if not panel._keys_hit.isEmpty():
        boxes.append(panel._keys_hit)
    if panel._tools_open:
        boxes.append(panel._tools_rect())
    if not panel._earth_chip_box.isEmpty():
        boxes.append(QRect(panel._earth_chip_box))
    for name in ("_earth_coach_box", "_earth_find_box", "_earth_key_box"):
        extra = getattr(panel, name, QRect())
        if extra is not None and not extra.isEmpty():
            boxes.append(QRect(extra))
    card = getattr(panel, "_earth_card_box", QRect())
    if not card.isEmpty():
        boxes.append(QRect(card))
    for box in (panel._inspect_rect(), panel._confirm_rect()):
        if not box.isEmpty():
            boxes.append(box)
    panel._chrome_key = key
    panel._chrome_cache = boxes
    return boxes


def chrome_covers(panel, x: int, y: int) -> bool:
    return any(box.contains(x, y) for box in panel._chrome_rects())


def label_body(
    panel,
    painter: QPainter,
    body: BodyView,
    sx: float,
    sy: float,
    px_r: float,
) -> None:
    inspect = body.name == panel._inspect
    if inspect:
        return
    if panel._on_globe(sx, sy):
        return
    want = px_r >= 6 or body.kind in {"star", "planet", "asteroid"}
    if not want:
        return
    width = panel._label_w.get(body.name)
    if width is None:
        width = max(28, painter.fontMetrics().horizontalAdvance(body.name) + 4)
        panel._label_w[body.name] = width
    candidates = (
        (int(sx + max(px_r, 2) + 6), int(sy + 4)),
        (int(sx - width - 4), int(sy + 4)),
        (int(sx + 4), int(sy - max(px_r, 2) - 12)),
        (int(sx + 4), int(sy + max(px_r, 2) + 14)),
        (int(sx + max(px_r, 2) + 6), int(sy - 12)),
        (int(sx - width - 4), int(sy - 12)),
    )
    chosen: tuple[int, int] | None = None
    for x, y in candidates:
        if panel._chrome_covers(x, y):
            continue
        if any(
            abs(ox - x) < 48 and abs(oy - y) < 13
            for _name, ox, oy, _w in panel._drawn_labels
        ):
            continue
        chosen = (x, y)
        break
    if chosen is None:
        return
    x, y = chosen
    panel._drawn_labels.append((body.name, x, y, width))
    painter.setPen(color("text_dim"))
    painter.drawText(x, y, body.name)


def on_globe(panel, x: float, y: float) -> bool:
    if panel._cover is None:
        return False
    cx, cy, cr = panel._cover
    return math.hypot(x - cx, y - cy) < cr + 6.0


def close_globe(panel) -> bool:
    return panel._cover is not None and panel._cover[2] >= _CLOSE_GLOBE_PX


def look_field_m(panel, system: SolarSystem) -> float:
    look = panel.cam.distance
    if panel._inspect:
        body = system.nbody.find(panel._inspect)
        if body is not None:
            look = math.hypot(
                panel.cam.x - body.x,
                panel.cam.y - body.y,
                panel.cam.z - body.z,
            )
    return look * math.tan(0.35)


def earth_limb(panel, painter: QPainter, sx: float, sy: float, px_r: float) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    halo = QPen(QColor(110, 170, 255, 48))
    halo.setWidth(max(1, int(px_r * 0.028)))
    painter.setPen(halo)
    painter.drawEllipse(
        QPoint(int(sx), int(sy)),
        int(px_r + 2),
        int(px_r + 2),
    )


def sun_limb(panel, painter: QPainter, sx: float, sy: float, px_r: float) -> None:
    """Software flare. Same pixel model as the GPU path."""
    from arelis.physics.star_look import star_flare

    look = star_flare(px_r, panel.height())
    reach = look.spike_px
    old = painter.compositionMode()
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    painter.setPen(Qt.PenStyle.NoPen)
    c = QPoint(int(sx), int(sy))
    painter.setBrush(QColor(255, 200, 80, int(36 + 40 * look.unresolved)))
    painter.drawEllipse(c, int(look.bloom_px), int(look.bloom_px))
    axes = (
        (0.0, 1.0, 1.0),
        (1.0, 0.0, 0.85),
        (0.707, 0.707, 0.40),
        (0.707, -0.707, 0.40),
    )
    for dx, dy, gain in axes:
        length = reach * gain
        painter.setPen(
            QPen(QColor(255, 220, 120, int(90 * look.spike_gain * gain)), 1)
        )
        painter.drawLine(
            QPoint(int(sx - dx * length), int(sy - dy * length)),
            QPoint(int(sx + dx * length), int(sy + dy * length)),
        )
    painter.setCompositionMode(old)


def paint_sun_loops(
    panel, painter: QPainter, system: SolarSystem, body: BodyView
) -> None:
    from arelis.physics.corona import loops, off_limb_segments

    disc = panel._proj((body.x, body.y, body.z))
    if disc is None or disc[2] < 1.0:
        return
    from arelis.physics.corona import LOOP_MIN_PX

    if panel._true_px(body.radius, disc[2]) < LOOP_MIN_PX:
        return
    jd = spin_jd(system.epoch_jd, system.t)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    sun_eye = np.array(
        (body.x - panel.cam.x, body.y - panel.cam.y, body.z - panel.cam.z),
        dtype=np.float64,
    )
    for loop in loops(body.radius, jd, time.perf_counter()):
        segs = off_limb_segments(loop, body.radius, sun_eye=sun_eye)
        for i in range(0, segs.shape[0] - 1, 2):
            pts: list[QPoint] = []
            for x, y, z in segs[i : i + 2]:
                hit = panel._proj((body.x + x, body.y + y, body.z + z))
                if hit is None:
                    pts = []
                    break
                pts.append(QPoint(int(hit[0]), int(hit[1])))
            if len(pts) == 2:
                panel._stroke_loop(painter, pts, loop.flare)


def stroke_loop(panel, painter: QPainter, pts: list[QPoint], flare: float) -> None:
    if flare > 0.22:
        painter.setPen(QPen(QColor(255, 190, 70, 200), 2))
    else:
        painter.setPen(QPen(QColor(255, 90, 16, 110), 1))
    for a, b in pairwise(pts):
        painter.drawLine(a, b)


def paint_saturn_rings(panel, painter: QPainter, body: BodyView) -> None:
    """IAU pole + C–A radii. Sketch, not ring particles."""
    xx, yx, zx = saturn_ring_axes()
    del zx
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(220, 200, 160, 110), 1))
    disc = panel._proj((body.x, body.y, body.z))
    hide_r = (
        panel._true_px(body.radius, disc[2]) if disc is not None else 0.0
    )
    for radius in (
        SATURN_RING_INNER_M,
        SATURN_CASSINI_INNER_M,
        SATURN_CASSINI_OUTER_M,
        SATURN_RING_OUTER_M,
    ):
        pts = []
        for i in range(64):
            ang = 2.0 * math.pi * i / 64.0
            c, s = math.cos(ang), math.sin(ang)
            proj = panel._proj(
                (
                    body.x + (xx[0] * c + yx[0] * s) * radius,
                    body.y + (xx[1] * c + yx[1] * s) * radius,
                    body.z + (xx[2] * c + yx[2] * s) * radius,
                )
            )
            if proj is None:
                continue
            if disc is not None and math.hypot(
                proj[0] - disc[0], proj[1] - disc[1]
            ) < hide_r:
                continue
            pts.append(QPoint(int(proj[0]), int(proj[1])))
        if len(pts) > 2:
            for a, b in pairwise(pts):
                painter.drawLine(a, b)


def paint_heliocentric_orbits(panel, painter: QPainter, system: SolarSystem) -> None:
    """Osculating ellipses. Not trails, not a radius cheat."""
    inspect = panel._inspect
    close = panel._close_globe()
    for body in system.views():
        if body.tracer or body.name == "Sun":
            continue
        if body.kind == "moon" and body.name != inspect and body.parent != inspect:
            continue
        if body.kind not in {"planet", "asteroid", "moon"}:
            continue
        if close and body.parent != inspect:
            continue
        r, v, mu, _about, origin = system.about(body)
        el = osculating(r, v, mu)
        if el is None or el.e >= 0.95:
            continue
        alpha = 90 if body.name == inspect else 42 if body.kind == "planet" else 28
        dash = QPen(QColor(255, 255, 255, alpha))
        dash.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(dash)
        pts = []
        steps = 72 if body.kind == "asteroid" else 96
        for i in range(steps):
            nu = 2.0 * math.pi * i / steps
            px, py, pz = position_at_true_anomaly(el, nu)
            proj = panel._proj((origin[0] + px, origin[1] + py, origin[2] + pz))
            if proj is None or panel._on_globe(proj[0], proj[1]):
                pts.append(None)
                continue
            pts.append(QPoint(int(proj[0]), int(proj[1])))
        if len([p for p in pts if p is not None]) > 2:
            for a, b in zip(pts, pts[1:] + pts[:1], strict=False):
                if a is None or b is None:
                    continue
                painter.drawLine(a, b)
        phase = (time.perf_counter() / BEAD_LAP_S) * 2.0 * math.pi
        for k, nu_b in enumerate(
            bead_true_anomalies(el.true_anomaly, phase=phase)
        ):
            bx, by, bz = position_at_true_anomaly(el, nu_b)
            hit = panel._proj((origin[0] + bx, origin[1] + by, origin[2] + bz))
            if hit is None:
                continue
            lead = 1.0 if k == 0 else 0.42
            glow = 3 + int(3 * lead)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(200, 230, 255, int(120 + 110 * lead)))
            painter.drawEllipse(QPoint(int(hit[0]), int(hit[1])), glow, glow)
        painter.setBrush(Qt.BrushStyle.NoBrush)


def paint_trails(panel, painter: QPainter, system: SolarSystem) -> None:
    painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
    for name, trail in system.trails.items():
        del name
        pts = []
        for x, y, z in trail:
            proj = panel._proj((x, y, z))
            if proj:
                pts.append(QPoint(int(proj[0]), int(proj[1])))
        for a, b in pairwise(pts):
            painter.drawLine(a, b)


def paint_lagrange(panel, painter: QPainter, system: SolarSystem) -> None:
    from arelis.ui.earth_marks import ink_for_kind, paint_mark

    ink = ink_for_kind("lagrange", alpha=190)
    painter.setPen(color("text_dim"))
    for pts in (system.lagrange_sun_earth(), system.lagrange_sun_jupiter()):
        for label, xyz in pts.items():
            proj = panel._proj(xyz)
            if proj is None:
                continue
            x, y, _d = proj
            paint_mark(painter, float(x), float(y), "lagrange", band="city", ink=ink)
            painter.setPen(color("text_dim"))
            painter.drawText(int(x + 10), int(y - 2), label)


def paint_ecliptic(panel, painter: QPainter, sun) -> None:
    dash = QPen(QColor(255, 255, 255, 28))
    dash.setStyle(Qt.PenStyle.DotLine)
    painter.setPen(dash)
    pts = []
    for i in range(96):
        ang = 2.0 * math.pi * i / 96.0
        x = sun.x + AU_M * math.cos(ang)
        y = sun.y + AU_M * math.sin(ang)
        proj = panel._proj((x, y, sun.z))
        if proj:
            pts.append(QPoint(int(proj[0]), int(proj[1])))
    for a, b in zip(pts, pts[1:] + pts[:1], strict=False):
        painter.drawLine(a, b)


def facing(panel, cx: float, cy: float, cz: float, x: float, y: float, z: float) -> bool:
    return (x - cx) * (panel._eye[0] - x) + (y - cy) * (panel._eye[1] - y) + (
        z - cz
    ) * (panel._eye[2] - z) > 0.0


def stroke_world(
    panel,
    painter: QPainter,
    pts: list[tuple[float, float, float]],
    *,
    closed: bool = False,
    host: tuple[float, float, float] | None = None,
) -> None:
    last = None
    seq = pts + ([pts[0]] if closed and pts else [])
    for p in seq:
        if host is not None and not panel._facing(host[0], host[1], host[2], *p):
            last = None
            continue
        proj = panel._proj(p)
        if proj is None:
            last = None
            continue
        cur = QPoint(int(proj[0]), int(proj[1]))
        if last is not None:
            painter.drawLine(last, cur)
        last = cur


def ring_xy(
    panel,
    painter: QPainter,
    body: BodyView,
    radius: float,
    n: int = 72,
) -> None:
    pts = [
        (
            body.x + radius * math.cos(2.0 * math.pi * i / n),
            body.y + radius * math.sin(2.0 * math.pi * i / n),
            body.z,
        )
        for i in range(n)
    ]
    panel._stroke_world(painter, pts, closed=True)


def paint_sphere_cage(
    panel,
    painter: QPainter,
    body: BodyView,
    radius: float,
    *,
    meridians: int = 4,
) -> None:
    """Projected meridians + equator of a sphere. Software stand-in for a shell."""
    panel._ring_xy(painter, body, radius)
    n = 36
    for k in range(max(int(meridians), 2)):
        lon = k * math.pi / max(int(meridians), 2)
        cl, sl = math.cos(lon), math.sin(lon)
        pts = [
            (
                body.x + radius * math.sin(math.pi * i / n) * cl,
                body.y + radius * math.sin(math.pi * i / n) * sl,
                body.z + radius * math.cos(math.pi * i / n),
            )
            for i in range(n + 1)
        ]
        panel._stroke_world(painter, pts)


def paint_magnetopause(
    panel, painter: QPainter, system: SolarSystem, *, strokes: bool = True
) -> None:
    from arelis.physics.magnetosphere import (
        dipole_L_polylines,
        earth_standoff_m,
        shue_meridians,
        sunward_basis,
    )
    from arelis.physics.parker import dynamic_pressure_npa

    earth = system.nbody.find("Earth")
    sun = system.nbody.find("Sun")
    if earth is None:
        return
    if panel._inspect and panel._inspect != "Earth":
        return
    if sun is not None:
        sl = math.hypot(sun.x - earth.x, sun.y - earth.y, sun.z - earth.z) or AU_M
        p_npa = dynamic_pressure_npa(sl)
        ux, uy, uz = sunward_basis(
            (earth.x, earth.y, earth.z), (sun.x, sun.y, sun.z)
        )
    else:
        p_npa = dynamic_pressure_npa(AU_M)
        ux, uy, uz = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    r0_m, r0_re, alpha = earth_standoff_m(p_npa, earth.radius)
    host = (earth.x, earth.y, earth.z)
    if strokes:
        painter.setPen(QPen(QColor(120, 180, 255, 130), 1))
        for line in shue_meridians(r0_m, alpha, ux, uy, uz):
            world = [(host[0] + p[0], host[1] + p[1], host[2] + p[2]) for p in line]
            panel._stroke_world(painter, world)
        painter.setPen(QPen(QColor(150, 200, 255, 80), 1))
        for loop in dipole_L_polylines(earth.radius, ux, uy, uz, n_lon=8):
            world = [
                (host[0] + p[0], host[1] + p[1], host[2] + p[2]) for p in loop
            ]
            panel._stroke_world(painter, world)
    nose = (host[0] + r0_m * ux[0], host[1] + r0_m * ux[1], host[2] + r0_m * ux[2])
    proj = panel._proj(nose)
    if proj is not None and panel._inspect != "Earth":
        painter.setPen(QColor(160, 200, 255, 190))
        painter.drawText(
            int(proj[0]) + 8,
            int(proj[1]) - 4,
            f"Shue r0={r0_re:.1f} Re  P={p_npa:.2f} nPa + dipole — not IGRF",
        )


def paint_wind(panel, painter: QPainter, system: SolarSystem) -> None:
    from arelis.physics.attitude import spin_jd
    from arelis.physics.parker import (
        CITE,
        HELIOPAUSE_AU,
        R_SOURCE_RSUN,
        heliopause_ring,
        spiral_points,
    )

    sun = system.nbody.find("Sun")
    if sun is None:
        return
    jd = spin_jd(system.epoch_jd, system.t)
    r_sun = BODY_BY_NAME["Sun"].radius
    r0 = R_SOURCE_RSUN * r_sun
    r1 = 5.0 * AU_M
    painter.setPen(QPen(QColor(255, 170, 70, 70), 1))
    for k in range(8):
        phi0 = k * math.pi / 4.0
        pts = spiral_points(phi0, r0, r1, jd)
        world = [(sun.x + p[0], sun.y + p[1], sun.z + p[2]) for p in pts]
        panel._stroke_world(painter, world)
    hp = heliopause_ring(HELIOPAUSE_AU * AU_M, jd)
    painter.setPen(QPen(QColor(180, 140, 90, 50), 1, Qt.PenStyle.DashLine))
    world_hp = [(sun.x + p[0], sun.y + p[1], sun.z + p[2]) for p in hp]
    panel._stroke_world(painter, world_hp, closed=True)
    hit = panel._proj((sun.x + hp[0, 0], sun.y + hp[0, 1], sun.z + hp[0, 2]))
    if hit is not None:
        painter.setPen(QColor(200, 160, 90, 160))
        painter.drawText(int(hit[0]) + 6, int(hit[1]) - 2, "heliopause ~120 AU (Voyager)")
    disc = panel._proj((sun.x, sun.y, sun.z))
    if disc is not None and panel._inspect != "Sun" and panel._true_px(r_sun, disc[2]) >= 8.0:
        painter.setPen(QColor(255, 180, 80, 170))
        painter.drawText(int(disc[0]) + 10, int(disc[1]) + 14, CITE.split(". ")[0] + ".")


def paint_g(panel, painter: QPainter, system: SolarSystem) -> None:
    name = panel._inspect or system.lock
    origin = system.nbody.find(name)
    if origin is None:
        return
    gx, gy, gz, g = system.gravity_at(origin.x, origin.y, origin.z)
    if g < 1e-20:
        return
    scale = max(8.0e6, origin.radius * 3.0)
    tip = (
        origin.x + gx / g * scale,
        origin.y + gy / g * scale,
        origin.z + gz / g * scale,
    )
    a = panel._proj((origin.x, origin.y, origin.z))
    b = panel._proj(tip)
    if a is None or b is None:
        return
    painter.setPen(QPen(QColor(255, 200, 80, 200), 2))
    painter.drawLine(int(a[0]), int(a[1]), int(b[0]), int(b[1]))
    painter.setPen(color("text"))
    painter.drawText(int(b[0]) + 6, int(b[1]), f"|g|={g:.3e} m/s² at centre")


def paint_wells(
    panel, painter: QPainter, system: SolarSystem, *, strokes: bool = True
) -> None:
    inspect = system.nbody.find(panel._inspect) if panel._inspect else None
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if strokes:
        for body in system.views():
            if _is_sketch(body):
                continue
            wanted = body.kind in {"star", "planet"} or (
                inspect is not None and body.name == inspect.name
            )
            if not wanted:
                continue
            disc = panel._proj((body.x, body.y, body.z))
            depth = disc[2] if disc is not None else 1.0e30
            for k, alpha in zip(ISO_G_FACTORS, (90, 55, 32), strict=True):
                if panel._true_px(k * body.radius, depth) > 80.0:
                    continue
                painter.setPen(QPen(QColor(255, 196, 90, alpha), 1))
                panel._paint_sphere_cage(painter, body, k * body.radius)
            r, v, mu, _about, _origin = system.about(body)
            el = osculating(r, v, mu)
            if el is not None and body.mass > 0.0 and mu > 0.0:
                hill = hill_radius(float(el.a), body.mass, mu / G_SI)
                if hill > 8.0 * body.radius and panel._true_px(hill, depth) <= 72.0:
                    painter.setPen(QPen(QColor(255, 160, 70, 70), 1, Qt.PenStyle.DotLine))
                    panel._paint_sphere_cage(painter, body, hill, meridians=6)
                    if inspect is not None and body.name == inspect.name:
                        tip = panel._proj((body.x + hill, body.y, body.z))
                        if tip is not None:
                            painter.setPen(QColor(255, 180, 90, 180))
                            painter.drawText(int(tip[0]) + 6, int(tip[1]), "Hill")
            if inspect is not None and body.name == inspect.name:
                panel._paint_well_slice(painter, body, mu)


def paint_well_slice(panel, painter: QPainter, body: BodyView, mu: float) -> None:
    n = 16
    n_th = well_theta_count(n)
    inner = well_inner_ring(n)
    pts = well_grid(mu, body.radius, n=n)
    painter.setPen(QPen(QColor(255, 180, 80, 70), 1))
    for ir in range(inner, n + 1):
        ring = [
            (
                body.x + pts[ir * n_th + it][0],
                body.y + pts[ir * n_th + it][1],
                body.z + pts[ir * n_th + it][2],
            )
            for it in range(n_th)
        ]
        panel._stroke_world(painter, ring, closed=True)
    for it in range(0, n_th, 2):
        spoke = [
            (
                body.x + pts[ir * n_th + it][0],
                body.y + pts[ir * n_th + it][1],
                body.z + pts[ir * n_th + it][2],
            )
            for ir in range(inner, n + 1)
        ]
        panel._stroke_world(painter, spoke)


def paint_grid(panel, painter: QPainter, system: SolarSystem) -> None:
    if not panel._inspect:
        return
    body = system.nbody.find(panel._inspect)
    if body is None or body.name == "Sun":
        return
    disc = panel._proj((body.x, body.y, body.z))
    if disc is None:
        return
    if panel._true_px(body.radius, disc[2]) < 18.0:
        return
    r = body.radius * 1.004
    host = (body.x, body.y, body.z)
    earth = system.nbody.find("Earth")
    moon = system.nbody.find("Moon")
    frame = body_frame_ecliptic(
        body.name,
        spin_jd(system.epoch_jd, system.t),
        moon=(moon.x, moon.y, moon.z) if moon is not None else None,
        earth=(earth.x, earth.y, earth.z) if earth is not None else None,
    )
    if frame is None:
        xx, yx, zx = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    else:
        xx, yx, zx = frame
    painter.setPen(QPen(QColor(210, 220, 230, 90), 1))
    for k in range(6):
        lon = k * math.pi / 3.0
        cl, sl = math.cos(lon), math.sin(lon)
        meridian = [
            _on_frame(host, r, lat, cl, sl, xx, yx, zx)
            for lat in (math.radians(-80.0 + 160.0 * i / 24.0) for i in range(25))
        ]
        panel._stroke_world(painter, meridian, host=host)
    for lat_deg in (-60.0, -30.0, 0.0, 30.0, 60.0):
        lat = math.radians(lat_deg)
        parallel = [
            _on_frame(
                host,
                r,
                lat,
                math.cos(lon),
                math.sin(lon),
                xx,
                yx,
                zx,
            )
            for lon in (2.0 * math.pi * i / 36.0 for i in range(36))
        ]
        panel._stroke_world(painter, parallel, closed=True, host=host)


def maps_alert(panel) -> str:
    note = (panel._maps_note or "").strip()
    if not note:
        return ""
    low = note.lower()
    if (
        "kepler" in low
        or "placeholder" in low
        or "horizons ic" in low
        or "cached" in low
    ):
        return ""
    if "counterfactual" in low:
        return ""
    if "horizons" in low or "vector" in low:
        return ""
    if "fetching nasa albedo" in low:
        return note
    if "map" in low or "albedo" in low:
        return note
    return ""


def inspect_column_width(panel) -> int:
    if not panel._inspect:
        return 0
    want = min(520, max(460, panel.width() // 3))
    room = panel.width() - 28 - _HUD_LANE
    if room < 240:
        return max(200, panel.width() - _HUD_LANE - 28)
    return min(want, max(240, room))


def hud_plate_width(panel) -> int:
    right = panel.width() - 10
    if panel._inspect:
        col = panel._inspect_column_width()
        right = min(right, panel.width() - col - 16 - _HUD_GAP)
    return max(_HUD_MIN_W, min(_HUD_MAX_W, right - 10))


def hud_plate_rect(panel) -> QRect:
    if not panel._hud_box.isEmpty():
        return QRect(panel._hud_box)
    return QRect(10, 8, panel._hud_plate_width(), max(8, panel._hud_bottom - 8))


def legend_columns(panel, inner_w: int) -> int:
    return 4 if inner_w >= 560 else 2


def hud_status_lines(panel, system: SolarSystem) -> list[str]:
    hud = system.hud_for_lock()
    look = panel._look_field_m(system)
    clock = "clock paused" if system.paused else "running"
    rate = float(hud.get("rate") or system.rate)
    if system.wall_lock and not system.paused and system.epoch_jd > 1e6:
        pace = "locked to now"
    elif system.paused and abs(rate - 1.0) < 1e-9:
        pace = "Space to run"
    elif system.paused:
        pace = rate_label(rate) + " when running"
    else:
        pace = rate_label(rate)
    bits = [
        clock,
        pace,
        f"field {_fmt_m(look)}",
    ]
    flags = []
    if system.overlay.show_gravity:
        flags.append("g")
    if system.overlay.show_magnetic:
        flags.append("B")
    if system.overlay.show_wind:
        flags.append("wind")
    if system.overlay.show_grid:
        flags.append("grid")
    if flags:
        bits.append(" ".join(flags))
    lines = ["   ".join(bits)]
    when = jd_iso(spin_jd(system.epoch_jd, system.t) - TT_MINUS_UTC_S / DAY_S)
    if when:
        tag = "  locked" if system.wall_lock and not system.paused else ""
        lines.append(when + tag)
    ic = system.ic_caption()
    if ic:
        lines.append(ic)
    alert = panel._maps_alert()
    if alert:
        lines.append(alert)
    if not panel._space_live() and panel._gl is not None:
        lines.append("OpenGL failed — software globes")
    from arelis.earth.runtime import get_earth

    zone = get_earth()
    if zone is not None and zone.active:
        stamp = ""
        if when:
            stamp = when + (
                "  locked" if system.wall_lock and not system.paused else ""
            )
        return [row for row in (lines[0], stamp, zone.status_line()) if row]
    lines.append("Reality")
    return lines


def wrapped_h(panel, fm: QFontMetrics, text: str, width: int) -> int:
    wrap = int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap)
    return fm.boundingRect(QRect(0, 0, max(width, 40), 8000), wrap, text).height()


def key_strip_chips(
    panel, fm: QFontMetrics, left: int, top: int, width: int
) -> tuple[list[tuple[QRect, str, bool]], int]:
    """Layout for the collapsed hint row. One Keys chip; the rest is type."""
    inner_left = left + 10
    inner_right = left + width - 10
    y = top + 4
    keys_w = fm.horizontalAdvance("Keys") + 16
    toggle = QRect(inner_right - keys_w, y, keys_w, _KEYS_ROW)
    hint = QRect(
        inner_left, y, max(40, toggle.left() - inner_left - 8), _KEYS_ROW
    )
    from arelis.earth.runtime import get_earth

    zone = get_earth()
    hint_text = KEY_HINT_EARTH if zone is not None and zone.active else KEY_HINT
    return [(hint, hint_text, False), (toggle, "Keys", panel._help)], y + _KEYS_ROW + 4


def legend_items(
    panel, box_left: int, legend_top: int, inner_w: int
) -> tuple[list[tuple[int, int, str, tuple[tuple[str, str], ...], int]], int]:
    cols = panel._legend_columns(inner_w)
    col_w = max(130, inner_w // max(cols, 1))
    items: list[tuple[int, int, str, tuple[tuple[str, str], ...], int]] = []
    bottom = legend_top
    legend = list(KEY_LEGEND)
    from arelis.earth.runtime import get_earth
    from arelis.ui.earth_chrome import MARK_HINTS

    zone = get_earth()
    if zone is not None and zone.active:
        legend.append(("Earth marks", MARK_HINTS))
    for gi, (title, rows) in enumerate(legend):
        cx = box_left + 10 + (gi % cols) * col_w
        cy = legend_top + (gi // cols) * _LEGEND_BLOCK
        items.append((cx, cy, title, rows, col_w))
        bottom = max(bottom, cy + 32 + len(rows) * _LEGEND_ROW)
    return items, bottom


def keys_chrome_height(panel, fm: QFontMetrics, width: int) -> int:
    _chips, y = panel._key_strip_chips(fm, 0, 0, width)
    if not panel._help:
        return y
    inner_w = width - 20
    _items, bottom = panel._legend_items(0, y, inner_w)
    y = bottom + 8
    return y + panel._wrapped_h(fm, panel._keys_footer(), inner_w) + 8


def keys_footer(panel) -> str:
    from arelis.earth.runtime import get_earth

    zone = get_earth()
    if zone is not None and zone.active:
        return (
            "Slash finds a city. Live is published feeds. "
            "Sparse is a hole, not a miss. No F."
        )
    return "Spoken flags match H and ⋯. No F. Travel flies the eye, not a burn."


def paint_plate(panel, painter: QPainter, box: QRect, *, radius: int = 8) -> None:
    painter.setPen(QPen(color("edge"), 1))
    painter.setBrush(_wash("glass_fill", 255))
    painter.drawRoundedRect(box, radius, radius)


def paint_chip(
    panel,
    painter: QPainter,
    box: QRect,
    label: str,
    *,
    on: bool = False,
) -> None:
    painter.setPen(QPen(color("edge_hot") if on else color("edge"), 1))
    painter.setBrush(_wash("accent", 130 if on else 42))
    painter.drawRoundedRect(box, 4, 4)
    painter.setPen(color("text"))
    painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)


def paint_keys_chrome(panel, painter: QPainter, box: QRect) -> int:
    """Hint line plus one Keys control. Click Keys (or H) for the legend."""
    fm = painter.fontMetrics()
    chips, y = panel._key_strip_chips(fm, box.left(), box.top(), box.width())
    hint_rect, hint, _off = chips[0]
    toggle, keys_label, on = chips[1]
    painter.setPen(color("text_dim"))
    painter.drawText(
        hint_rect,
        int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
        hint,
    )
    panel._paint_chip(painter, toggle, keys_label, on=on)
    panel._keys_toggle = QRect(toggle)
    panel._keys_hit = QRect(box.left(), box.top(), box.width(), y - box.top())
    if not panel._help:
        return y - box.top()
    inner_w = box.width() - 20
    items, bottom = panel._legend_items(box.left(), y, inner_w)
    for cx, cy, title, rows, col_w in items:
        painter.setPen(color("accent"))
        painter.drawText(cx, cy + 14, title)
        yy = cy + 32
        tight = col_w < 170
        for key, hint in rows:
            if tight:
                painter.setPen(color("text"))
                painter.drawText(cx, yy, f"{key}  {hint}")
            else:
                painter.setPen(color("text"))
                painter.drawText(cx, yy, key)
                painter.setPen(color("text_dim"))
                painter.drawText(cx + 78, yy, hint)
            yy += _LEGEND_ROW
    y = bottom + 8
    wrap = int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap)
    footer = panel._keys_footer()
    foot_h = max(24, panel._wrapped_h(fm, footer, inner_w) + 4)
    foot = QRect(box.left() + 10, y, inner_w, foot_h)
    painter.setPen(color("text_dim"))
    painter.drawText(foot, wrap, footer)
    y = y + foot_h + 8
    panel._keys_hit = QRect(box.left(), box.top(), box.width(), y - box.top())
    return y - box.top()


def paint_hud(panel, painter: QPainter, system: SolarSystem) -> None:
    wrap = int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap)
    plate_w = panel._hud_plate_width()
    inner = plate_w - 24
    fm = painter.fontMetrics()
    lines = panel._hud_status_lines(system)
    y = 12
    status_rows: list[tuple[int, int, str]] = []
    for line in lines:
        h = panel._wrapped_h(fm, line, inner)
        status_rows.append((y, h, line))
        y += h + 4
    keys_top = y
    keys_h = panel._keys_chrome_height(fm, plate_w)
    plate = QRect(10, 8, plate_w, keys_top + keys_h)
    panel._paint_plate(painter, plate, radius=6)
    for i, (y0, h, line) in enumerate(status_rows):
        painter.setPen(color("text") if i == 0 else color("text_dim"))
        painter.drawText(QRect(20, y0, inner, h + 4), wrap, line)
    used = panel._paint_keys_chrome(
        painter, QRect(10, keys_top, plate_w, keys_h + 8)
    )
    bottom = max(plate.bottom(), keys_top + used + 8)
    panel._hud_box = QRect(plate.left(), plate.top(), plate.width(), bottom - plate.top())
    panel._hud_bottom = panel._hud_box.bottom()
    if system.show_graphs and system.energy_hist:
        panel._spark(painter, system)


def earth_chip_layout(panel) -> tuple[list[tuple[str, QRect]], QRect]:
    from arelis.earth.runtime import get_earth

    zone = get_earth()
    if zone is None or not zone.active:
        return [], QRect()
    roster = panel._roster_rect()
    inspect = panel._inspect_rect()
    left = 10
    if not roster.isEmpty():
        left = roster.right() + 8
    right = panel.width() - 10
    if not inspect.isEmpty():
        right = min(right, inspect.left() - 8)
    width = max(160, right - left)
    return layout_earth_chips(
        panel.fontMetrics(), left, panel._hud_bottom + 8, width
    )


def earth_chip_at(panel, px: float, py: float) -> str | None:
    hits = panel._earth_chip_hits or panel._earth_chip_layout()[0]
    for kind, rect in hits:
        if rect.contains(int(px), int(py)):
            return kind
    return None


def toggle_earth_chip(panel, kind: str) -> None:
    from arelis.earth.runtime import get_earth

    zone = get_earth()
    if zone is None or not zone.active:
        return
    if kind == "band":
        return
    if kind == "live":
        zone.live = not zone.live
        try:
            from arelis.physics.telemetry import emit

            emit("earth_live", on=zone.live)
        except Exception:
            pass
        if zone.live:
            panel._start_earth_live()
        panel.update()
        return
    if kind == "grid":
        zone.grid = not bool(getattr(zone, "grid", False))
        panel.update()
        return
    if kind == "tiles":
        zone.tiles = not zone.tiles
        try:
            from arelis.physics.telemetry import emit

            emit("earth_tiles", on=zone.tiles)
        except Exception:
            pass
        panel.update()
        return
    if kind == "buildings":
        zone.buildings = not zone.buildings
        try:
            from arelis.physics.telemetry import emit

            emit("earth_buildings", on=zone.buildings)
        except Exception:
            pass
        panel.update()
        return
    if zone.set_layer(kind) is None:
        return
    panel.update()


def start_earth_live(panel) -> None:
    from arelis.earth.runtime import get_earth

    zone = get_earth()
    if panel._earth_live_busy or (zone is not None and zone._live_busy):
        return
    if os.environ.get("PYTEST_CURRENT_TEST"):
        if zone is not None and zone.active and zone.live:
            zone._merge_live()
        panel._earth_live_busy = False
        return
    panel._earth_live_busy = True
    if zone is not None:
        zone._live_busy = True

    def work() -> None:
        try:
            live = get_earth()
            if live is not None and live.active and live.live:
                live._merge_live()
        finally:
            done = get_earth()
            if done is not None:
                done._live_busy = False
            panel._earth_live_done = True

    threading.Thread(target=work, daemon=True).start()


def paint_earth_toggles(panel, painter: QPainter) -> None:
    from arelis.earth.runtime import get_earth

    zone = get_earth()
    if zone is None or not zone.active:
        panel._earth_chip_hits = []
        panel._earth_chip_box = QRect()
        return
    hits, box = panel._earth_chip_layout()
    panel._earth_chip_hits = hits
    panel._earth_chip_box = QRect(box)
    if box.isEmpty():
        panel._earth_coach_box = QRect()
        return
    band = zone.last_view.band if zone.last_view is not None else ""
    labels = dict(earth_chip_items(band))
    panel._paint_plate(painter, box, radius=6)
    from arelis.ui.earth_chrome import paint_band_type, paint_live_chip

    for kind, rect in hits:
        if kind == "band":
            paint_band_type(painter, rect, band)
            continue
        if kind == "live":
            paint_live_chip(panel, painter, rect, on=bool(zone.live))
            continue
        on = (
            bool(getattr(zone, "grid", False))
            if kind == "grid"
            else zone.tiles
            if kind == "tiles"
            else zone.buildings
            if kind == "buildings"
            else bool(zone.layers.get(kind, False))
        )
        panel._paint_chip(painter, rect, labels.get(kind, kind), on=on)
    y = box.bottom() + 6
    left = box.left()
    width = box.width()
    from arelis.ui.earth_chrome import paint_coach, paint_key_chips
    from arelis.ui.earth_find import paint_find

    coach = paint_coach(painter, left, y, width, zone)
    panel._earth_coach_box = QRect(coach)
    if not coach.isEmpty():
        y = coach.bottom() + 6
    find_box = paint_find(panel, painter, left, y, width)
    if not find_box.isEmpty():
        y = find_box.bottom() + 4
    key_box = paint_key_chips(panel, painter, left, y, width)
    if not key_box.isEmpty():
        y = key_box.bottom() + 4
    paint_earth_grid(panel, painter, zone)
    paint_earth_loading(panel, painter, zone)


def paint_earth_grid(panel, painter: QPainter, zone) -> None:
    if not getattr(zone, "grid", False) or zone.last_view is None:
        return
    view = zone.last_view
    text = f"{view.lat:.4f}°  {view.lon:.4f}°  {view.alt_m / 1000.0:.0f} km"
    fm = painter.fontMetrics()
    box = panel._earth_chip_box
    if box.isEmpty():
        return
    y = box.bottom() + 4
    extra = getattr(panel, "_earth_key_box", QRect())
    if extra is not None and not extra.isEmpty():
        y = extra.bottom() + 4
    find = getattr(panel, "_earth_find_box", QRect())
    if find is not None and not find.isEmpty():
        y = max(y, find.bottom() + 4)
    painter.setPen(color("text_dim"))
    painter.drawText(box.left() + 4, y + fm.ascent(), text)


def paint_earth_loading(panel, painter: QPainter, zone) -> None:
    host = getattr(panel, "_globe_host", None)
    if host is None or host.ready or host.failed:
        if host is not None and host.failed and zone.active:
            painter.setPen(color("warn"))
            box = panel._earth_chip_box
            if not box.isEmpty():
                y = box.bottom() + 36
                for name in ("_earth_key_box", "_earth_find_box"):
                    extra = getattr(panel, name, QRect())
                    if extra is not None and not extra.isEmpty():
                        y = max(y, extra.bottom() + 8)
                painter.drawText(box.left() + 4, y, "fancy map failed — NASA ball")
        return
    box = panel._earth_chip_box
    if box.isEmpty():
        return
    y = box.bottom() + 36
    for name in ("_earth_key_box", "_earth_find_box", "_earth_coach_box"):
        extra = getattr(panel, name, QRect())
        if extra is not None and not extra.isEmpty():
            y = max(y, extra.bottom() + 8)
    painter.setPen(color("text"))
    painter.drawText(box.left() + 4, y, "falling in")
    painter.setPen(color("text_dim"))
    painter.drawText(
        box.left() + 4,
        y + 16,
        "engine · tiles · contacts",
    )


def paint_earth_card(panel, painter: QPainter) -> None:
    """Inspect plate for an Earth-zone contact. Same sodium chrome as HUD."""
    from arelis.earth.runtime import get_earth
    from arelis.ui.earth_overlay import inspect_caption

    zone = get_earth()
    place = getattr(panel, "_place", None)
    if zone is None or not zone.active:
        panel._earth_card_box = QRect()
        return
    if panel._earth_id:
        hit = zone.get(panel._earth_id)
        if hit is None:
            panel._earth_card_box = QRect()
            return
        text = inspect_caption(hit)
    elif isinstance(place, dict) and place.get("name"):
        kind = str(place.get("kind") or "place")
        text = (
            f"{place.get('name')}\n"
            f"{kind}  {float(place.get('lat') or 0):.2f}°, "
            f"{float(place.get('lon') or 0):.2f}°\n"
            "click another pin · wheel closer"
        )
    else:
        panel._earth_card_box = QRect()
        return
    status = str(getattr(panel, "_look_status", "") or "")
    if status:
        text = text + "\n" + status
    wrap = int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap)
    plate_w = panel._hud_plate_width()
    inner = plate_w - 24
    fm = painter.fontMetrics()
    text_h = panel._wrapped_h(fm, text, inner) + 16
    frame = getattr(panel, "_look_frame", None)
    frame_h = 0
    frame_w = inner
    if frame is not None and hasattr(frame, "isNull") and not frame.isNull():
        src_w = max(1, int(frame.width()))
        src_h = max(1, int(frame.height()))
        frame_w = inner
        frame_h = max(72, min(220, int(frame_w * src_h / src_w)))
    h = text_h + (frame_h + 8 if frame_h else 0)
    top = panel._hud_bottom + 8
    if not panel._earth_chip_box.isEmpty():
        top = panel._earth_chip_box.bottom() + 8
    for name in ("_earth_find_box", "_earth_key_box", "_earth_coach_box"):
        extra = getattr(panel, name, QRect())
        if extra is not None and not extra.isEmpty():
            top = max(top, extra.bottom() + 8)
    if top + h > panel.height() - 24:
        extra = top + h - (panel.height() - 24)
        if frame_h:
            frame_h = max(0, frame_h - extra)
            h = text_h + (frame_h + 8 if frame_h else 0)
        if top + h > panel.height() - 24:
            panel._earth_card_box = QRect()
            return
    box = QRect(10, top, plate_w, h)
    panel._earth_card_box = QRect(box)
    panel._paint_plate(painter, box, radius=6)
    y = box.top() + 6
    if frame_h and frame is not None:
        target = QRect(box.left() + 12, y, frame_w, frame_h)
        painter.drawImage(target, frame)
        y += frame_h + 4
    text_left = 10
    if panel._earth_id:
        from arelis.earth.look import has_look
        from arelis.ui.earth_marks import heading_of, paint_mark
        from arelis.ui.earth_overlay import _ink

        hit = zone.get(panel._earth_id)
        if hit is not None:
            mag = hit.meta.get("mag")
            paint_mark(
                painter,
                box.left() + 20,
                y + 12,
                hit.layer,
                band="city",
                heading_deg=heading_of(hit),
                freshness=hit.freshness,
                look=has_look(hit.id),
                mag=float(mag) if isinstance(mag, (int, float)) else None,
                ink=_ink(hit.layer, freshness=hit.freshness),
            )
            text_left = 32
    painter.setPen(color("text"))
    painter.drawText(QRect(box.left() + text_left, y, inner - (text_left - 10), text_h), wrap, text)


def spark(panel, painter: QPainter, system: SolarSystem) -> None:
    box = QRect(panel.width() - 220, 18, 200, 56)
    panel._paint_plate(painter, box, radius=4)
    vals = [
        abs(e - system.energy0) / max(abs(system.energy0), 1e-30)
        for _t, e in system.energy_hist
    ]
    if not vals:
        return
    lo, hi = min(vals), max(vals)
    span = max(hi - lo, 1e-16)
    painter.setPen(QPen(color("accent"), 1))
    prev = None
    n = len(vals)
    for i, v in enumerate(vals):
        x = box.left() + int(i / max(n - 1, 1) * (box.width() - 2))
        y = box.bottom() - int((v - lo) / span * (box.height() - 4))
        pt = QPoint(x, y)
        if prev:
            painter.drawLine(prev, pt)
        prev = pt
    painter.setPen(color("text_dim"))
    painter.drawText(box.adjusted(4, 2, 0, 0), "|ΔE/E0|")


def paint_free_markers(panel, painter: QPainter, system: SolarSystem) -> None:
    from arelis.ui.earth_marks import ink_for_kind, paint_mark

    for body in system.views():
        if body.kind not in {"probe", "lagrange"}:
            continue
        proj = panel._proj((body.x, body.y, body.z))
        if proj is None:
            continue
        sx, sy, _d = proj
        paint_mark(
            painter,
            float(sx),
            float(sy),
            body.kind,
            band="city",
            ink=ink_for_kind(body.kind),
        )
        painter.setPen(color("text_dim"))
        note = (
            "massless"
            if body.kind == "probe"
            else "CR3BP L-point, not N-body eq."
        )
        painter.drawText(int(sx) + 10, int(sy) - 4, f"{body.name} ({note})")


def dots_rect(panel) -> QRect:
    return QRect(panel.width() - 36, panel.height() - 36, 24, 16)


def _short_horizons_note(note: str) -> str:
    text = (note or "").strip()
    if any(code in text for code in ("503", "429", "502", "504")) or "busy" in text.lower():
        return "JPL Horizons is busy."
    if "HTTP 400" in text:
        return "Horizons refused a VECTOR request."
    if len(text) > 180:
        return text[:177] + "…"
    return text


def empty_caption(panel) -> str:
    if panel._load_pending:
        return panel._load_progress or "Fetching JPL Horizons VECTORS…"
    note = (panel._maps_note or "").strip()
    if note:
        return "No solar system loaded.\n" + _short_horizons_note(note)
    return (
        "No solar system loaded.\n"
        "Fetching JPL Horizons VECTORS once.\n"
        "WASD fly · Space pause · click inspect · H keys · ⋯ overlays"
    )


def speed_rect(panel) -> QRect:
    return QRect(22, panel.height() - 88, min(420, max(120, panel.width() - 80)), 16)


def u_from_x(panel, box: QRect, px: float) -> float:
    return min(1.0, max(0.0, (float(px) - box.left()) / max(box.width(), 1)))


def paint_speed(panel, painter: QPainter) -> None:
    box = panel._speed_rect()
    panel._paint_plate(painter, box, radius=3)
    fill_w = int(panel.cam.speed_u() * box.width())
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_wash("accent", 160))
    painter.drawRect(box.left() + 1, box.top() + 1, max(2, fill_w - 2), box.height() - 2)
    painter.setPen(color("text_dim"))
    painter.drawText(
        box.x(),
        box.y() - 4,
        f"Camera  {speed_label(panel.cam.speed)}   Shift+wheel",
    )


def inspect_rect(panel) -> QRect:
    if not panel._inspect:
        return QRect()
    system = get_system()
    lines = panel._inspect_lines(system) if system is not None else []
    w = panel._inspect_column_width()
    inner = w - 28
    body_h = panel._inspect_body_height(lines, inner)
    top = 18
    if system is not None and system.show_graphs:
        top = 154
    h = min(max(body_h + 64, 220), max(220, panel.height() - top - 72))
    return QRect(panel.width() - w - 16, top, w, h)


def inspect_font(panel, *, title: bool = False) -> QFont:
    font = QFont(panel.font())
    font.setPixelSize(FONT_PX + 6 if title else FONT_PX + 1)
    font.setBold(title)
    return font


def inspect_body_height(panel, lines: list[str], width: int) -> int:
    title_fm = QFontMetrics(panel._inspect_font(title=True))
    body_fm = QFontMetrics(panel._inspect_font())
    h = title_fm.height() + 10
    wrap = int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap)
    box = QRect(0, 0, max(width, 40), 8000)
    for i, line in enumerate(lines):
        if i == 0:
            continue
        h += body_fm.boundingRect(box, wrap, line).height() + 8
    return h


def inspect_close_rect(panel) -> QRect:
    box = panel._inspect_rect()
    if box.isEmpty():
        return QRect()
    return QRect(box.right() - 24, box.top() + 6, 18, 18)


def inspect_travel_rect(panel) -> QRect:
    box = panel._inspect_rect()
    if box.isEmpty():
        return QRect()
    return QRect(box.left() + 12, box.bottom() - 38, box.width() - 24, 26)


def inspect_lines(panel, system: SolarSystem | None) -> list[str]:
    """Memoised per simulated second. Every rect query used to rebuild a HUD."""
    if system is None or not panel._inspect:
        return []
    zone_on = False
    zone_note = ""
    try:
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is not None:
            zone_on = bool(zone.active)
            zone_note = str(zone.note or "")
    except Exception:
        zone_on = False
    key = (
        id(system),
        panel._inspect,
        len(system.nbody.particles),
        int(system.t),
        system.ic_caption(),
        system.overlay.show_magnetic,
        system.overlay.show_wind,
        system.overlay.show_grid,
        zone_on,
        zone_note,
    )
    if key == panel._inspect_key and panel._inspect_cache is not None:
        return panel._inspect_cache
    lines = panel._build_inspect_lines(system)
    panel._inspect_key = key
    panel._inspect_cache = lines
    return lines


def build_inspect_lines(panel, system: SolarSystem) -> list[str]:
    hud = system.hud_for_name(panel._inspect)
    kind = str(hud.get("kind") or "")
    name = str(hud.get("name") or panel._inspect)
    lines = [name]
    parent = hud.get("parent")
    who = kind if kind else "body"
    if parent:
        lines.append(f"{who} of {parent}")
    else:
        lines.append(who)
    radius = float(hud.get("radius_m") or 0)
    gm = float(hud.get("gm") or 0)
    bits = [f"R {_fmt_m(radius)}"]
    if gm > 0.0:
        mass = gm / G_SI
        bits.append(f"M {mass:.3g} kg")
        bits.append(f"GM {gm:.4g} m³/s²")
        if radius > 0.0:
            bits.append(f"g {gm / (radius * radius):.3g} m/s²")
    lines.append(" · ".join(bits) + "  ·  IAU sphere")
    if hud.get("a_au") is not None:
        lines.append(
            f"a {float(hud['a_au']):.4g} AU   e {float(hud.get('e') or 0):.4f}   "
            f"i {float(hud.get('i_deg') or 0):.2f}°   "
            f"P {float(hud.get('period_day') or 0):.3g} d"
        )
        lines.append(
            f"Hill {_fmt_m(float(hud.get('hill_m') or 0))}   "
            f"SOI {_fmt_m(float(hud.get('soi_m') or 0))}   "
            "numbers, not capture walls"
        )
    ic = system.ic_caption()
    if (
        hud.get("e") is not None
        and float(hud.get("e") or 0) < 1e-4
        and "not Horizons" in ic
    ):
        lines.append(
                "e≈0 is the placeholder catalog, not a Horizons eccentricity."
        )
    hid = hud.get("horizons_id")
    if hid:
        lines.append(f"Horizons COMMAND={hid}")
    info = describe(name)
    if name == "Sun":
        from arelis.physics.corona import CITE

        lines.append(CITE)
    elif kind == "asteroid":
        if info.path is None:
            lines.append(
                "IAU mean sphere, not a potato. No crater DEM. "
                f"{info.source}"
            )
        else:
            gsd = f"{info.km_per_px:g} km/px" if info.km_per_px else "?"
            lines.append(
                f"IAU mean sphere, not a potato. Albedo {info.source} "
                f"(~{gsd}), large-scale only."
            )
    elif info.path is None:
        lines.append(f"albedo: none — {info.source}. Limb-lit sphere, no fake detail.")
        lines.append(spin_caption(name))
    else:
        gsd = f"{info.km_per_px:g} km/px" if info.km_per_px else "?"
        extra = " " + spin_caption(name)
        src = info.source.lower()
        if any(word in src for word in ("mosaic", "voyager", "cassini")):
            extra += " Coverage gaps stay tint — not invented fill."
        lines.append(f"albedo: {info.source}  (~{gsd}).{extra}")
    if system.overlay.show_magnetic and name == "Sun":
        lines.append("Dipole loops are a centred-dipole sketch. Not MHD.")
    elif system.overlay.show_magnetic and name != "Earth":
        lines.append(
            "Magnetic overlay is Earth Shue 1998 only. Inspect Earth to see it."
        )
    if system.overlay.show_wind:
        from arelis.physics.parker import CITE as WIND_CITE

        lines.append(WIND_CITE)
    if name == "Saturn":
        lines.append(
            "Rings: IAU WGCCRE 2015 pole, C–A + Cassini (NASA/JPL km). "
            "Sketch, not particles."
        )
    r_stop, cite = stop_radius_m(name)
    lines.append(f"approach stop {_fmt_m(r_stop)}. {cite}")
    integ = str(hud.get("integrator") or "")
    if integ:
        lines.append(integ)
    lines.append(
        "Travel to flies the eye: accel, cruise, slow. Camera warp, not a burn. No landing."
    )
    if name == "Earth":
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is not None and zone.active:
            from arelis.earth.globe_stack import choose_stack

            stack = choose_stack()
            host = getattr(panel, "_globe_host", None)
            label = "native" if host is not None and host.failed else stack.label()
            compact = [
                lines[0],
                f"stack {label}",
            ]
            return [line for line in compact if line]
    return [line for line in lines if line]


def paint_inspect(panel, painter: QPainter, system: SolarSystem) -> None:
    if not panel._inspect:
        return
    lines = panel._inspect_lines(system)
    box = panel._inspect_rect()
    old_font = painter.font()
    panel._paint_plate(painter, box, radius=8)
    close = panel._inspect_close_rect()
    painter.setPen(color("text_dim"))
    painter.drawText(close, Qt.AlignmentFlag.AlignCenter, "x")
    y = box.top() + 16
    wrap = int(
        Qt.AlignmentFlag.AlignLeft
        | Qt.AlignmentFlag.AlignTop
        | Qt.TextFlag.TextWordWrap
    )
    if lines:
        from arelis.ui.earth_marks import ink_for_kind, paint_mark

        body = system.nbody.find(panel._inspect)
        kind = getattr(body, "kind", None) if body is not None else None
        title_left = 16
        if kind in {"star", "planet", "moon", "asteroid", "probe", "lagrange"}:
            paint_mark(
                painter,
                box.left() + 24,
                y + 12,
                kind,
                band="city",
                ink=ink_for_kind(kind),
            )
            title_left = 36
        painter.setFont(panel._inspect_font(title=True))
        painter.setPen(color("text"))
        title_box = QRect(box.left() + title_left, y, box.width() - title_left - 28, 48)
        painter.drawText(title_box, wrap, lines[0])
        y = (
            painter.fontMetrics()
            .boundingRect(title_box, wrap, lines[0])
            .bottom()
            + 10
        )
    painter.setFont(panel._inspect_font())
    limit = box.bottom() - 52
    inner_w = box.width() - 32
    for i, line in enumerate(lines):
        if i == 0:
            continue
        if y > limit:
            break
        painter.setPen(color("text") if i == 1 else color("text_dim"))
        text_box = QRect(box.left() + 16, y, inner_w, max(16, limit - y))
        painter.drawText(text_box, wrap, line)
        y = (
            painter.fontMetrics()
            .boundingRect(text_box, wrap, line)
            .bottom()
            + 8
        )
    travel = panel._inspect_travel_rect()
    travel_label = "Travel to  ·  Enter"
    if panel._inspect == "Earth":
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        if zone is not None and zone.active:
            travel_label = "Leave Earth"
    panel._paint_chip(painter, travel, travel_label, on=True)
    painter.setFont(old_font)


def epoch_rect(panel) -> QRect:
    return QRect(22, panel.height() - 48, min(420, max(120, panel.width() - 80)), 16)


def set_epoch_from_x(panel, system: SolarSystem, px: float) -> None:
    box = panel._epoch_rect()
    u = max(0.0, min(1.0, (float(px) - box.left()) / max(box.width(), 1)))
    system.set_future_gyr(GYR_MIN + u * (GYR_MAX - GYR_MIN))


def paint_epoch(panel, painter: QPainter, system: SolarSystem) -> None:
    box = panel._epoch_rect()
    panel._paint_plate(painter, box, radius=3)
    span = GYR_MAX - GYR_MIN
    u = (system.future_gyr - GYR_MIN) / span if span else 0.0
    fill_w = int(max(0.0, min(1.0, u)) * box.width())
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_wash("accent", 160))
    painter.drawRect(box.left() + 1, box.top() + 1, max(2, fill_w - 2), box.height() - 2)
    painter.setPen(color("text_dim"))
    sign = "+" if system.future_gyr > 0 else ""
    painter.drawText(
        box.x(),
        box.y() - 4,
        f"Sun {sign}{system.future_gyr:.2f} Gyr   cited track, not IAS15",
    )


def tools_rect(panel) -> QRect:
    dots = panel._dots_rect()
    n = len(SOLAR_OVERLAY) + len(SOLAR_SPAWN)
    width, row_h, head = 328, 36, 8
    height = head + n * row_h + 10
    y = dots.top() - height - 6
    if y < 8:
        height = max(120, dots.top() - 14)
        y = 8
    return QRect(dots.right() - width, y, width, height)


def chip_rects(panel) -> list[tuple[str, QRect]]:
    panel = panel._tools_rect().adjusted(8, 8, -8, -8)
    items = list(SOLAR_OVERLAY) + list(SOLAR_SPAWN)
    n = max(len(items), 1)
    h = max(28, panel.height() // n)
    rows: list[tuple[str, QRect]] = []
    for i, (kind, _label, _hint) in enumerate(items):
        rows.append(
            (kind, QRect(panel.left(), panel.top() + i * h, panel.width(), h - 3))
        )
    return rows


def spawn_hit(panel, px: float, py: float) -> str | None:
    for kind, rect in panel._chip_rects():
        if rect.contains(int(px), int(py)):
            return kind
    return None


def overlay_on(panel, kind: str) -> bool:
    system = get_system()
    if system is None:
        return False
    if kind == "gravity":
        return system.overlay.show_gravity
    if kind == "magnetic":
        return system.overlay.show_magnetic
    if kind == "wind":
        return system.overlay.show_wind
    if kind == "grid":
        return system.overlay.show_grid
    return False


def toggle_overlay(panel, kind: str) -> bool:
    """Flip a sketch overlay. True keeps the ⋯ tray open."""
    overlay = {item[0] for item in SOLAR_OVERLAY}
    if kind not in overlay:
        return False
    system = get_system()
    if system is None:
        return True
    if kind == "gravity":
        system.overlay.show_gravity = not system.overlay.show_gravity
    elif kind == "magnetic":
        system.overlay.show_magnetic = not system.overlay.show_magnetic
    elif kind == "wind":
        system.overlay.show_wind = not system.overlay.show_wind
    elif kind == "grid":
        system.overlay.show_grid = not system.overlay.show_grid
    try:
        from arelis.physics.telemetry import emit

        emit(
            "overlay",
            kind=kind,
            gravity=system.overlay.show_gravity,
            magnetic=system.overlay.show_magnetic,
            wind=system.overlay.show_wind,
            grid=system.overlay.show_grid,
        )
    except Exception:
        pass
    return True


def spawn(panel, kind: str) -> None:
    if kind == "toy":
        panel.toy_requested.emit()
        return
    system = get_system()
    if system is None:
        return
    host = panel._inspect
    if kind == "probe" and host and host != "Sun":
        hit = system.nbody.find(host)
        if hit is not None and hit.massive:
            system.lock = host
    try:
        if kind == "probe":
            system.spawn_probe()
        elif kind == "tracer":
            system.spawn_tracer()
        elif kind == "l4":
            system.spawn_lagrange("L4")
        elif kind == "impulse":
            panel._open_impulse_confirm(panel._inspect or "")
        elif kind == "planet":
            panel._open_planet_confirm()
    except RuntimeError:
        return


def open_impulse_confirm(panel, name: str) -> None:
    system = get_system()
    body = system.nbody.find(name) if system is not None and name else None
    if body is None or not body.massive:
        panel._confirm = {"kind": "need_inspect"}
        return
    panel._confirm = {"kind": "impulse", "name": body.name, "dv_mps": 100.0}


def open_planet_confirm(panel) -> None:
    system = get_system()
    if system is None or system.nbody.find("Sun") is None:
        panel._confirm = {"kind": "need_inspect"}
        return
    panel._confirm = {"kind": "planet", "a_au": 2.5}


def confirm_rect(panel) -> QRect:
    if not panel._confirm:
        return QRect()
    kind = str(panel._confirm.get("kind") or "")
    h = 140 if kind == "need_inspect" else 220
    w = 440
    return QRect((panel.width() - w) // 2, (panel.height() - h) // 2 - 16, w, h)


def confirm_chip_rects(panel) -> dict[str, QRect]:
    box = panel._confirm_rect()
    if box.isEmpty():
        return {}
    y = box.bottom() - 34
    kind = str(panel._confirm.get("kind") or "") if panel._confirm else ""
    chips: dict[str, QRect] = {}
    if kind == "impulse":
        x = box.left() + 16
        for label in ("dv10", "dv100", "dv1000"):
            chips[label] = QRect(x, box.top() + 118, 88, 24)
            x += 96
    if kind == "planet":
        chips["a_prev"] = QRect(box.left() + 16, box.top() + 118, 28, 24)
        chips["a_next"] = QRect(box.left() + 52, box.top() + 118, 28, 24)
    if kind != "need_inspect":
        chips["apply"] = QRect(box.left() + 16, y, 120, 24)
        chips["cancel"] = QRect(box.left() + 144, y, 120, 24)
    else:
        chips["cancel"] = QRect(box.left() + 16, y, 120, 24)
    return chips


def confirm_hit(panel, px: float, py: float) -> str | None:
    box = panel._confirm_rect()
    if box.isEmpty() or not box.contains(int(px), int(py)):
        return None
    for name, rect in panel._confirm_chip_rects().items():
        if rect.contains(int(px), int(py)):
            return name
    return "bg"


def confirm_click(panel, hit: str) -> None:
    if panel._confirm is None or hit == "bg":
        return
    if hit == "cancel":
        panel._confirm = None
        panel.update()
        return
    if hit == "dv10":
        panel._confirm["dv_mps"] = 10.0
    elif hit == "dv100":
        panel._confirm["dv_mps"] = 100.0
    elif hit == "dv1000":
        panel._confirm["dv_mps"] = 1000.0
    elif hit == "a_prev":
        a = float(panel._confirm.get("a_au") or 2.5)
        panel._confirm["a_au"] = max(0.5, round(a - 0.5, 4))
    elif hit == "a_next":
        a = float(panel._confirm.get("a_au") or 2.5)
        panel._confirm["a_au"] = min(40.0, round(a + 0.5, 4))
    elif hit == "apply":
        panel._confirm_apply()
        return
    panel.update()


def confirm_apply(panel) -> None:
    system = get_system()
    ask = panel._confirm
    panel._confirm = None
    if system is None or ask is None:
        panel.update()
        return
    kind = str(ask.get("kind") or "")
    try:
        if kind == "impulse":
            name = str(ask.get("name") or "")
            mag = float(ask.get("dv_mps") or 0.0)
            if not system.prograde_impulse(name, mag):
                panel._maps_note = f"Could not impulse {name}."
        elif kind == "planet":
            a_au = float(ask.get("a_au") or 2.5)
            label = system.add_planet(a_au * AU_M, "extra")
            panel._inspect = label
    except RuntimeError as exc:
        panel._maps_note = str(exc)
    panel.update()


def paint_confirm(panel, painter: QPainter) -> None:
    ask = panel._confirm
    if ask is None:
        return
    box = panel._confirm_rect()
    panel._paint_plate(painter, box, radius=8)
    kind = str(ask.get("kind") or "")
    painter.setPen(color("text"))
    y = box.top() + 28
    lines: list[str] = []
    if kind == "need_inspect":
        lines = [
            "Inspect a massive body first.",
            "Click a name in the list, then impulse.",
        ]
    elif kind == "impulse":
        name = str(ask.get("name") or "")
        mag = float(ask.get("dv_mps") or 0.0)
        lines = [
            f"Impulse {name}  +{mag:g} m/s prograde",
            "Along inertial v. Massive bodies only.",
            "COUNTERFACTUAL. Energy and L books reset.",
            "This is a new universe, not Horizons.",
        ]
    elif kind == "planet":
        a_au = float(ask.get("a_au") or 2.5)
        lines = [
            f"Add Earth-mass circular planet at {a_au:g} AU",
            "Coplanar with the ecliptic sketch. Not a real body.",
            "COUNTERFACTUAL. Energy and L books reset.",
        ]
    for line in lines:
        painter.drawText(box.left() + 16, y, line)
        y += 18
    chips = panel._confirm_chip_rects()
    labels = {
        "dv10": "10 m/s",
        "dv100": "100 m/s",
        "dv1000": "1 km/s",
        "a_prev": "<",
        "a_next": ">",
        "apply": "Apply",
        "cancel": "Cancel",
    }
    selected = float(ask.get("dv_mps") or 0.0) if kind == "impulse" else None
    for name, rect in chips.items():
        on = (name == "dv10" and selected == 10.0) or (
            name == "dv100" and selected == 100.0
        ) or (name == "dv1000" and selected == 1000.0)
        painter.setPen(QPen(color("edge_hot") if on else color("edge"), 1))
        painter.setBrush(_wash("accent", 110 if on else 40))
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(color("text"))
        painter.drawText(
            rect, Qt.AlignmentFlag.AlignCenter, labels.get(name, name)
        )


def paint_tools(panel, painter: QPainter) -> None:
    dots = panel._dots_rect()
    ink = color("text_dim")
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(ink)
    cy = dots.center().y()
    gap = 6
    x0 = dots.center().x() - gap
    for i in range(3):
        painter.drawEllipse(QPoint(x0 + i * gap, cy), 2, 2)
    if not panel._tools_open:
        return
    panel = panel._tools_rect()
    painter.setBrush(_wash("glass_fill", 236))
    painter.setPen(QPen(color("edge"), 1))
    painter.drawRoundedRect(panel, 6, 6)
    captions = {
        kind: (label, hint)
        for kind, label, hint in (*SOLAR_OVERLAY, *SOLAR_SPAWN)
    }
    overlay = {kind for kind, _label, _hint in SOLAR_OVERLAY}
    for kind, rect in panel._chip_rects():
        on = kind in overlay and panel._overlay_on(kind)
        painter.setPen(QPen(color("edge_hot") if on else color("edge"), 1))
        painter.setBrush(_wash("accent", 110 if on else 36))
        painter.drawRoundedRect(rect, 4, 4)
        label, hint = captions.get(kind, (kind, ""))
        if on:
            label = f"{label}  on"
        painter.setPen(color("text"))
        painter.drawText(
            rect.adjusted(10, 2, -8, -16),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            label,
        )
        painter.setPen(color("text_dim"))
        painter.drawText(
            rect.adjusted(10, 18, -8, -2),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            hint,
        )

