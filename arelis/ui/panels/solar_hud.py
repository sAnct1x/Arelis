"""HUD, inspect, tools, and Earth-zone chips for the solar plate.

Body / orbit paint stays in solar_paint.py. SolarPanel methods stay as
delegates so paint_overlay can call chrome without a circular import.
"""
from __future__ import annotations

import os
import threading

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPen

from arelis.physics.attitude import spin_caption, spin_jd
from arelis.physics.camera import speed_label
from arelis.physics.clocks import (
    TT_MINUS_UTC_S,
    jd_iso,
    rate_label,
)
from arelis.physics.collision import stop_radius_m
from arelis.physics.constants import AU_M, DAY_S, G_SI
from arelis.physics.evolution import GYR_MAX, GYR_MIN
from arelis.physics.maps import describe
from arelis.physics.runtime import get_system
from arelis.physics.scene import SolarSystem
from arelis.ui.earth_overlay import (
    earth_chip_items,
    layout_earth_chips,
)
from arelis.ui.panels.solar_const import (
    _HUD_GAP,
    _HUD_LANE,
    _HUD_MAX_W,
    _HUD_MIN_W,
    _KEYS_ROW,
    _LEGEND_BLOCK,
    _LEGEND_ROW,
    KEY_HINT,
    KEY_HINT_EARTH,
    KEY_LEGEND,
    SOLAR_OVERLAY,
    SOLAR_SPAWN,
    _fmt_m,
    _wash,
)
from arelis.ui.theme import FONT_PX, color


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

