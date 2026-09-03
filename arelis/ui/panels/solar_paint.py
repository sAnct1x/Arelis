"""Software overlay: bodies, orbits, wells, and free markers.

HUD, inspect, tools, and Earth chips live in solar_hud.py. SolarPanel
methods stay as delegates. Tests pin paint_free_markers / paint_lagrange
in this file.
"""

from __future__ import annotations

import math
import time
from itertools import pairwise

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPen,
)

from arelis.physics.attitude import (
    body_frame_ecliptic,
    earth_lonlat_grid,
    lonlat_from_frame,
    moon_lonlat_grid,
    saturn_ring_axes,
    spin_jd,
)
from arelis.physics.constants import (
    AU_M,
    BODY_BY_NAME,
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
from arelis.physics.evolution import sample, sun_rgb
from arelis.physics.maps import describe
from arelis.physics.runtime import get_system
from arelis.physics.scene import BodyView, SolarSystem
from arelis.ui.earth_overlay import (
    paint_earth,
)
from arelis.ui.panels.solar_const import (
    _CLOSE_GLOBE_PX,
    _FILL,
    _TINT,
    _albedo,
    _Basis,
    _globe,
    _is_sketch,
    _on_frame,
    _sphere_axes,
    _world_normals,
    globe_cap,
)
from arelis.ui.theme import color


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
