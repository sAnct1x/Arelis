"""Earth HUD extras: band type, coach, picture-key chips, paste field."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from arelis.earth.copy import band_phrase, coach_line, live_chip_label
from arelis.earth.entity import LAYER_IDS
from arelis.earth.key_paste import missing_picture_keys, save_earth_key
from arelis.ui.theme import color

CHIP_ICON_PAD = 18
CHIP_ICON_KINDS = frozenset(LAYER_IDS)


def chip_icon_pad(kind: str) -> int:
    """Layer chips leave a seat for the mark. Band / Live / Grid stay text."""
    return CHIP_ICON_PAD if kind in CHIP_ICON_KINDS else 0


def paint_layer_chip(
    painter: QPainter,
    rect: QRect,
    kind: str,
    label: str,
    *,
    on: bool,
    ink: QColor,
) -> None:
    """Sodium chip with the same mark that sits on the globe."""
    painter.setPen(QPen(color("edge_hot") if on else color("edge"), 1))
    painter.setBrush(_wash("accent", 150) if on else _wash("glass_fill", 36))
    painter.drawRoundedRect(rect, 4, 4)
    from arelis.ui.earth_marks import paint_mark

    paint_mark(
        painter,
        float(rect.left() + 11),
        float(rect.center().y()) + 0.5,
        kind,
        band="city",
        size=14,
        ink=ink,
    )
    painter.setPen(color("text"))
    painter.drawText(
        rect.adjusted(20, 0, -4, 0),
        int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
        label,
    )


_CHIP_H = 22
_GAP = 4
_PAD = 8


MARK_HINTS: tuple[tuple[str, str], ...] = (
    ("plane", "flights"),
    ("fighter", "military"),
    ("quadcopter", "drone"),
    ("ship", "vessel"),
    ("sat + panels", "satellite"),
    ("truss + wings", "ISS"),
    ("camera", "camera"),
    ("person", "people"),
    ("dish", "radar"),
    ("burst", "quake"),
    ("flame", "fire"),
    ("cloud", "weather"),
    ("antenna", "radio"),
    ("car", "traffic"),
    ("pin", "site"),
    ("slash", "stale"),
    ("dashed ring", "coasting"),
)


def paint_band_type(painter: QPainter, rect: QRect, band: str) -> None:
    """Read-only distance. Not a chip — must not look toggleable."""
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(color("text_dim"))
    painter.drawText(
        rect,
        int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
        band_phrase(band),
    )


def paint_live_chip(panel: Any, painter: QPainter, rect: QRect, *, on: bool) -> None:
    busy = bool(getattr(panel, "_earth_live_busy", False))
    label = live_chip_label(on=on, busy=busy)
    painter.setPen(QPen(color("edge_hot") if on else color("warn"), 1))
    painter.setBrush(_wash("accent", 160) if on else Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect, 4, 4)
    painter.setPen(color("text"))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)


def _wash(name: str, alpha: int):
    tint = color(name)
    tint.setAlpha(max(0, min(255, int(alpha))))
    return tint


def paint_coach(painter: QPainter, left: int, top: int, width: int, zone: Any) -> QRect:
    text = coach_line(zone)
    if not text:
        return QRect()
    fm = painter.fontMetrics()
    wrap = int(Qt.TextFlag.TextWordWrap)
    h = fm.boundingRect(QRect(0, 0, max(40, width - 8), 80), wrap, text).height()
    box = QRect(left, top, width, h + 4)
    painter.setPen(color("text"))
    left_wrap = int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap)
    painter.drawText(box.adjusted(4, 0, -4, 0), left_wrap, text)
    return box


def layout_key_chips(
    fm, left: int, top: int, width: int
) -> list[tuple[str, QRect, str]]:
    missing = missing_picture_keys()
    if not missing:
        return []
    x = left + _PAD
    y = top
    right = left + width - _PAD
    hits: list[tuple[str, QRect, str]] = []
    for field, chip, prompt in missing:
        w = fm.horizontalAdvance(chip) + 16
        if x > left + _PAD and x + w > right:
            x = left + _PAD
            y += _CHIP_H + _GAP
        hits.append((field, QRect(x, y, w, _CHIP_H), prompt))
        x += w + _GAP
    return hits


def paint_key_chips(panel: Any, painter: QPainter, left: int, top: int, width: int) -> QRect:
    hits = layout_key_chips(painter.fontMetrics(), left, top, width)
    panel._earth_key_hits = [(field, rect) for field, rect, _prompt in hits]
    if not hits:
        panel._earth_key_box = QRect()
        return QRect()
    bottom = max(rect.bottom() for _f, rect, _p in hits) + 4
    box = QRect(left, top, width, bottom - top)
    panel._earth_key_box = QRect(box)
    paste = str(getattr(panel, "_earth_paste_field", "") or "")
    labels = {field: chip for field, chip, _prompt in missing_picture_keys()}
    for field, rect, _prompt in hits:
        on = field == paste
        painter.setPen(QPen(color("edge_hot") if on else color("edge"), 1))
        painter.setBrush(_wash("accent", 90 if on else 28))
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(color("text"))
        painter.drawText(
            rect,
            Qt.AlignmentFlag.AlignCenter,
            "Paste key" if on else labels.get(field, field),
        )
    if paste:
        prompt = next((p for f, _c, p in missing_picture_keys() if f == paste), "Paste key")
        buf = str(getattr(panel, "_earth_paste_buf", "") or "")
        shown = "•" * min(len(buf), 24) if buf else prompt
        y = box.bottom() + 2
        painter.setPen(color("text_dim"))
        painter.drawText(left + 4, y + painter.fontMetrics().ascent(), shown + "  Enter keeps it")
        box = QRect(left, top, width, y + 18 - top)
        panel._earth_key_box = QRect(box)
    return box


def key_chip_at(panel: Any, px: float, py: float) -> str | None:
    for field, rect in getattr(panel, "_earth_key_hits", []) or []:
        if rect.contains(int(px), int(py)):
            return field
    return None


def begin_paste(panel: Any, field: str) -> None:
    panel._earth_paste_field = field
    panel._earth_paste_buf = ""
    panel.update()


def type_paste(panel: Any, text: str) -> None:
    if not getattr(panel, "_earth_paste_field", ""):
        return
    panel._earth_paste_buf = (str(getattr(panel, "_earth_paste_buf", "") or "") + text)[:200]
    panel.update()


def backspace_paste(panel: Any) -> None:
    buf = str(getattr(panel, "_earth_paste_buf", "") or "")
    panel._earth_paste_buf = buf[:-1]
    panel.update()


def commit_paste(panel: Any) -> bool:
    field = str(getattr(panel, "_earth_paste_field", "") or "")
    buf = str(getattr(panel, "_earth_paste_buf", "") or "")
    panel._earth_paste_field = ""
    panel._earth_paste_buf = ""
    if not field:
        panel.update()
        return False
    ok = save_earth_key(field, buf)
    panel.update()
    return ok


def cancel_paste(panel: Any) -> None:
    panel._earth_paste_field = ""
    panel._earth_paste_buf = ""
    panel.update()


def _cam_alt_m(panel: Any) -> float | None:
    """Geodetic height of the dest / mirror cam. None if the eye is missing."""
    pose = getattr(panel, "_earth_cam", None)
    eye = getattr(pose, "eye", None)
    if not isinstance(eye, tuple) or len(eye) < 3:
        return None
    try:
        from arelis.earth.frames import ecef_to_geodetic

        alt = float(ecef_to_geodetic(*eye)[2])
    except Exception:
        return None
    return alt if alt > 0.0 else None


def _positive_m(value: Any) -> float | None:
    try:
        meters = float(value)
    except (TypeError, ValueError):
        return None
    return meters if meters > 0.0 else None


def nav_range_m(panel: Any) -> float | None:
    """Look-ray to the ellipsoid, else camera height. None until we have one.

    Find sets ``_earth_cam`` to the dest immediately so chips can follow.
    The Cesium look-ray can stay at Travel standoff (~46 000 km) until the
    fly emits. A ray that is still space while the dest cam is in the
    city is stale — use the dest height until Cesium speaks.
    """
    nadir = _positive_m(getattr(panel, "_earth_nadir_m", None))
    agl = _positive_m(getattr(panel, "_earth_agl_m", None))
    cam = _cam_alt_m(panel)
    if cam is not None:
        stale = max(cam * 4.0, cam + 80_000.0)
        if nadir is not None and nadir > stale:
            nadir = None
        if agl is not None and agl > stale:
            agl = None
    if nadir is not None:
        return nadir
    if agl is not None:
        return agl
    return cam


def paint_nav(panel: Any, painter: QPainter) -> None:
    """Compass + distance meter. Bottom-right, over Cesium, not the solar field."""
    from arelis.earth.runtime import get_earth
    from arelis.earth.scale import (
        format_distance,
        format_surface,
        scale_bar,
        scale_from_mpp,
        show_map_scale,
    )

    zone = get_earth()
    if zone is None or not zone.active:
        panel._earth_compass_box = QRect()
        panel._earth_scale_box = QRect()
        panel._earth_range_box = QRect()
        return
    size = 64
    margin = 24
    compass = QRect(
        panel.width() - margin - size,
        panel.height() - margin - size,
        size,
        size,
    )
    heading = 0.0
    hpr = getattr(panel, "_globe_hpr", None)
    if hpr:
        try:
            heading = float(hpr[0])
        except (TypeError, ValueError, IndexError):
            heading = 0.0
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(color("edge"), 1))
    painter.setBrush(_wash("glass_fill", 210))
    painter.drawEllipse(compass)
    painter.translate(compass.center())
    painter.rotate(-heading)
    painter.setPen(QPen(color("accent"), 2))
    painter.drawLine(0, 10, 0, -(size // 2) + 8)
    painter.setPen(color("text"))
    painter.drawText(
        QRect(-12, -(size // 2) + 2, 24, 14),
        int(Qt.AlignmentFlag.AlignCenter),
        "N",
    )
    painter.restore()
    panel._earth_compass_box = QRect(compass)

    surface = nav_range_m(panel)
    if surface is None:
        panel._earth_scale_box = QRect()
        panel._earth_range_box = QRect()
        return
    alt = getattr(panel, "_earth_agl_m", None)
    try:
        alt = float(alt) if alt is not None else surface
    except (TypeError, ValueError):
        alt = surface
    mpp = getattr(panel, "_earth_mpp", None)
    try:
        mpp_f = float(mpp) if mpp is not None else None
    except (TypeError, ValueError):
        mpp_f = None
    if mpp_f is not None and mpp_f <= 0.0:
        mpp_f = None
    want_bar = show_map_scale(alt_m=alt, mpp=mpp_f)
    bar_px = 0
    label = ""
    if want_bar:
        if mpp_f is not None:
            _nice, bar_px, label = scale_from_mpp(mpp_f)
        else:
            _nice, bar_px, label = scale_bar(alt, float(max(panel.width(), 1)))
    font = painter.font()
    font.setPixelSize(15)
    painter.setFont(font)
    fm = painter.fontMetrics()
    lines = [format_surface(surface)]
    pin = getattr(panel, "_earth_pin", None)
    if isinstance(pin, dict) and pin.get("slant_m") is not None:
        try:
            lines.append(f"{format_distance(float(pin['slant_m']))} to pin")
        except (TypeError, ValueError):
            pass
    row_w = max((fm.horizontalAdvance(line) for line in lines), default=80)
    bar_w = max(bar_px + 20, row_w + 20, fm.horizontalAdvance(label) + 20)
    line_h = fm.height() + 2
    plate_h = 12 + line_h * len(lines) + (22 if want_bar else 0)
    plate = QRect(
        panel.width() - margin - bar_w,
        compass.top() - plate_h - 10,
        bar_w,
        plate_h,
    )
    painter.setPen(QPen(color("edge"), 1))
    painter.setBrush(_wash("glass_fill", 230))
    painter.drawRoundedRect(plate, 6, 6)
    y = plate.top() + 6
    painter.setPen(color("text"))
    for i, line in enumerate(lines):
        painter.setPen(color("text") if i == 0 else color("text_dim"))
        painter.drawText(
            QRect(plate.left() + 8, y, plate.width() - 16, line_h),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            line,
        )
        y += line_h
    if want_bar:
        painter.setPen(QPen(color("text"), 2))
        left = plate.left() + 10
        by = plate.bottom() - 10
        painter.drawLine(left, by, left + bar_px, by)
        painter.drawLine(left, by - 4, left, by + 4)
        painter.drawLine(left + bar_px, by - 4, left + bar_px, by + 4)
        painter.setPen(color("text_dim"))
        painter.drawText(
            QRect(left + bar_px + 8, plate.bottom() - 20, plate.width() - bar_px - 20, 16),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            label,
        )
    panel._earth_scale_box = QRect(plate)
    panel._earth_range_box = QRect(plate)


def hit_nav(panel: Any, px: float, py: float) -> str | None:
    box = getattr(panel, "_earth_compass_box", QRect())
    if box is not None and not box.isEmpty() and box.contains(int(px), int(py)):
        return "north"
    return None
