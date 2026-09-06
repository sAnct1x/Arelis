"""Drawn sodium marks for Earth layers and solar body kinds.

One path language. Qt overlay, Cesium atlas, inspect card, and solar roster
all call this factory. Stroke is 1.25px, round caps, same hand as icons.py.
No icon packs, no theme icons, no downloaded glyph set.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)

from arelis.earth.entity import LAYER_IDS
from arelis.ui.theme import color

STROKE = 2.0
BANDS: tuple[str, ...] = ("space", "approach", "near", "city")
BAND_PX: dict[str, int] = {
    "space": 40,
    "approach": 28,
    "near": 24,
    "city": 24,
}
ATLAS_PX = 64

HEADING_KINDS = frozenset({"flights", "military", "drones", "vessels"})
SOLAR_KINDS: tuple[str, ...] = (
    "star",
    "planet",
    "moon",
    "asteroid",
    "probe",
    "lagrange",
)
OVERLAY_KINDS: tuple[str, ...] = ("stale", "dead-reckon")
ALL_KINDS: tuple[str, ...] = LAYER_IDS + SOLAR_KINDS + OVERLAY_KINDS

SOLAR_INK: dict[str, str] = {
    "star": "amber",
    "planet": "text",
    "moon": "text_dim",
    "asteroid": "hint",
    "probe": "accent2",
    "lagrange": "hint",
}

_HEADING_META = ("heading_deg", "track_deg", "cog_deg", "cog", "course")


def heading_of(entity: Any) -> float | None:
    """Clockwise degrees from north when a feed published a track."""
    meta = getattr(entity, "meta", None) or {}
    for key in _HEADING_META:
        raw = meta.get(key)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def ink_for_kind(kind: str, *, alpha: int = 220) -> QColor:
    role = SOLAR_INK.get(kind, "amber")
    ink = QColor(color(role))
    ink.setAlpha(alpha)
    return ink


def mark_size(band: str) -> int:
    return BAND_PX.get(band, BAND_PX["city"])


def _detail(band: str) -> int:
    return {"space": 2, "approach": 2, "near": 3, "city": 3}.get(band, 3)


def _pen(ink: QColor, *, dashed: bool = False, width: float | None = None) -> QPen:
    pen = QPen(ink)
    pen.setWidthF(STROKE if width is None else float(width))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    if dashed:
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([1.6, 1.8])
    return pen


def _stroke(
    painter: QPainter, ink: QColor, *, dashed: bool = False, width: float | None = None
) -> None:
    painter.setPen(_pen(ink, dashed=dashed, width=width))
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _fill(painter: QPainter, ink: QColor) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(ink)


def _line(
    painter: QPainter, x0: float, y0: float, x1: float, y1: float
) -> None:
    painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))


def _draw_flights(painter: QPainter, r: float, detail: int) -> None:
    """Top-down airliner: nose, swept wings, tailplane. Not a chevron."""
    del detail
    fuselage = QPolygonF(
        [
            QPointF(0.0, -r * 0.94),
            QPointF(r * 0.11, -r * 0.62),
            QPointF(r * 0.10, r * 0.46),
            QPointF(r * 0.06, r * 0.86),
            QPointF(-r * 0.06, r * 0.86),
            QPointF(-r * 0.10, r * 0.46),
            QPointF(-r * 0.11, -r * 0.62),
        ]
    )
    painter.drawPolygon(fuselage)
    wings = QPolygonF(
        [
            QPointF(-r * 0.96, r * 0.10),
            QPointF(-r * 0.14, -r * 0.16),
            QPointF(r * 0.14, -r * 0.16),
            QPointF(r * 0.96, r * 0.10),
            QPointF(r * 0.86, r * 0.26),
            QPointF(r * 0.12, r * 0.06),
            QPointF(-r * 0.12, r * 0.06),
            QPointF(-r * 0.86, r * 0.26),
        ]
    )
    painter.drawPolygon(wings)
    tail = QPolygonF(
        [
            QPointF(-r * 0.38, r * 0.58),
            QPointF(0.0, r * 0.46),
            QPointF(r * 0.38, r * 0.58),
            QPointF(r * 0.32, r * 0.72),
            QPointF(0.0, r * 0.62),
            QPointF(-r * 0.32, r * 0.72),
        ]
    )
    painter.drawPolygon(tail)


def _draw_military(painter: QPainter, r: float, detail: int) -> None:
    """Delta fighter, twin fins — not the airliner."""
    del detail
    delta = QPolygonF(
        [
            QPointF(0.0, -r * 0.94),
            QPointF(r * 0.90, r * 0.52),
            QPointF(r * 0.20, r * 0.22),
            QPointF(r * 0.30, r * 0.82),
            QPointF(0.0, r * 0.50),
            QPointF(-r * 0.30, r * 0.82),
            QPointF(-r * 0.20, r * 0.22),
            QPointF(-r * 0.90, r * 0.52),
        ]
    )
    painter.drawPolygon(delta)


def _draw_drones(painter: QPainter, r: float, detail: int) -> None:
    """Quadcopter: body plus four rotor arms."""
    del detail
    for sx, sy in ((-1.0, -1.0), (1.0, -1.0), (-1.0, 1.0), (1.0, 1.0)):
        _line(painter, 0.0, 0.0, sx * r * 0.58, sy * r * 0.58)
        painter.drawEllipse(QPointF(sx * r * 0.58, sy * r * 0.58), r * 0.22, r * 0.22)
    painter.drawRoundedRect(QRectF(-r * 0.22, -r * 0.22, r * 0.44, r * 0.44), 2.0, 2.0)


def _draw_vessels(painter: QPainter, r: float, detail: int) -> None:
    """Top-down ship: pointed bow, transom, cabin. Rotates with heading."""
    hull = QPolygonF(
        [
            QPointF(0.0, -r * 0.92),
            QPointF(r * 0.36, -r * 0.22),
            QPointF(r * 0.42, r * 0.58),
            QPointF(r * 0.22, r * 0.86),
            QPointF(-r * 0.22, r * 0.86),
            QPointF(-r * 0.42, r * 0.58),
            QPointF(-r * 0.36, -r * 0.22),
        ]
    )
    painter.drawPolygon(hull)
    painter.drawRect(QRectF(-r * 0.18, -r * 0.04, r * 0.36, r * 0.40))
    if detail >= 2:
        _line(painter, 0.0, r * 0.36, 0.0, -r * 0.16)
        if detail >= 3:
            _line(painter, 0.0, -r * 0.16, r * 0.22, 0.02)


def _draw_satellites(painter: QPainter, r: float, detail: int, ink: QColor) -> None:
    """Box bus, two solar wings, a small dish. The default sat."""
    body = QRectF(-r * 0.22, -r * 0.26, r * 0.44, r * 0.52)
    fill = QColor(ink)
    _fill(painter, fill)
    painter.drawRoundedRect(body, 1.6, 1.6)
    _stroke(painter, ink)
    painter.drawRect(QRectF(-r * 0.96, -r * 0.20, r * 0.68, r * 0.40))
    painter.drawRect(QRectF(r * 0.28, -r * 0.20, r * 0.68, r * 0.40))
    if detail >= 2:
        _line(painter, -r * 0.62, -r * 0.20, -r * 0.62, r * 0.20)
        _line(painter, r * 0.62, -r * 0.20, r * 0.62, r * 0.20)
        _line(painter, 0.0, -r * 0.26, 0.0, -r * 0.48)
        painter.drawArc(QRectF(-r * 0.18, -r * 0.66, r * 0.36, r * 0.28), 0, 180 * 16)


def _draw_iss(painter: QPainter, r: float, ink: QColor) -> None:
    """Truss and four solar wings — the station, not a ring."""
    del ink
    _line(painter, -r * 0.96, 0.0, r * 0.96, 0.0)
    painter.drawRect(QRectF(-r * 0.16, -r * 0.14, r * 0.32, r * 0.28))
    for sx in (-1.0, 1.0):
        x = sx * r * 0.36 if sx > 0 else -r * 0.90
        painter.drawRect(QRectF(x, -r * 0.46, r * 0.54, r * 0.28))
        painter.drawRect(QRectF(x, r * 0.16, r * 0.54, r * 0.28))


def _draw_cameras(painter: QPainter, r: float, ink: QColor, *, look: bool) -> None:
    """Camera body, lens, viewfinder. Filled lens when a look is open."""
    painter.drawRoundedRect(QRectF(-r * 0.64, -r * 0.20, r * 1.28, r * 0.74), 2.2, 2.2)
    painter.drawRect(QRectF(-r * 0.18, -r * 0.50, r * 0.36, r * 0.30))
    if look:
        fill = QColor(ink)
        _fill(painter, fill)
    painter.drawEllipse(QPointF(0.0, r * 0.16), r * 0.26, r * 0.26)
    _stroke(painter, ink)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPointF(r * 0.40, -r * 0.04), r * 0.08, r * 0.08)


def _draw_people(painter: QPainter, r: float, ink: QColor) -> None:
    """Head and shoulders. Not two nested rings."""
    fill = QColor(ink)
    _fill(painter, fill)
    painter.drawEllipse(QPointF(0.0, -r * 0.44), r * 0.26, r * 0.26)
    _stroke(painter, ink)
    shoulders = QPainterPath()
    shoulders.moveTo(-r * 0.64, r * 0.82)
    shoulders.quadTo(-r * 0.58, r * 0.08, 0.0, r * 0.04)
    shoulders.quadTo(r * 0.58, r * 0.08, r * 0.64, r * 0.82)
    painter.drawPath(shoulders)


def _draw_radar(painter: QPainter, r: float) -> None:
    """Dish on a stem — a sweep, not a diamond."""
    _line(painter, 0.0, r * 0.86, 0.0, r * 0.04)
    _line(painter, -r * 0.24, r * 0.86, r * 0.24, r * 0.86)
    painter.drawArc(QRectF(-r * 0.72, -r * 0.78, r * 1.44, r * 1.20), 20 * 16, 140 * 16)
    painter.drawArc(QRectF(-r * 0.46, -r * 0.52, r * 0.92, r * 0.80), 28 * 16, 124 * 16)
    _line(painter, 0.0, r * 0.04, r * 0.52, -r * 0.36)


def _draw_quakes(painter: QPainter, r: float, detail: int, mag: float | None) -> None:
    """Four-point burst sized by magnitude. Not a sun-ring."""
    m = 4.0 if mag is None else max(1.0, min(9.0, float(mag)))
    rad = r * (0.52 + 0.05 * m)
    star = QPolygonF(
        [
            QPointF(0.0, -rad),
            QPointF(rad * 0.20, -rad * 0.20),
            QPointF(rad, 0.0),
            QPointF(rad * 0.20, rad * 0.20),
            QPointF(0.0, rad),
            QPointF(-rad * 0.20, rad * 0.20),
            QPointF(-rad, 0.0),
            QPointF(-rad * 0.20, -rad * 0.20),
        ]
    )
    painter.drawPolygon(star)
    if detail >= 3:
        painter.drawEllipse(QPointF(0.0, 0.0), rad * 0.16, rad * 0.16)


def _draw_fires(painter: QPainter, r: float, ink: QColor) -> None:
    """Flame, readable down to 8px. Not a speck."""
    path = QPainterPath()
    path.moveTo(0.0, -r * 0.90)
    path.quadTo(-r * 0.72, -r * 0.16, -r * 0.50, r * 0.36)
    path.quadTo(-r * 0.16, r * 0.90, 0.0, r * 0.68)
    path.quadTo(r * 0.16, r * 0.90, r * 0.50, r * 0.36)
    path.quadTo(r * 0.72, -r * 0.16, 0.0, -r * 0.90)
    painter.drawPath(path)
    core = QColor(ink)
    _fill(painter, core)
    painter.drawEllipse(QPointF(0.0, r * 0.26), r * 0.16, r * 0.18)
    _stroke(painter, ink)


def _draw_weather(painter: QPainter, r: float, detail: int) -> None:
    """Cloud, plus rain ticks when there is room."""
    painter.drawEllipse(QPointF(-r * 0.28, r * 0.04), r * 0.36, r * 0.28)
    painter.drawEllipse(QPointF(r * 0.24, r * 0.08), r * 0.32, r * 0.26)
    painter.drawEllipse(QPointF(0.0, -r * 0.18), r * 0.40, r * 0.30)
    if detail >= 2:
        for x in (-0.30, 0.0, 0.30):
            _line(painter, r * x, r * 0.38, r * x - r * 0.08, r * 0.70)


def _draw_radio(painter: QPainter, r: float, detail: int) -> None:
    """Mast with radiating arcs."""
    _line(painter, 0.0, r * 0.88, 0.0, -r * 0.18)
    painter.drawEllipse(QPointF(0.0, -r * 0.28), r * 0.10, r * 0.10)
    painter.drawArc(QRectF(-r * 0.38, -r * 0.64, r * 0.76, r * 0.72), 40 * 16, 100 * 16)
    if detail >= 2:
        painter.drawArc(QRectF(-r * 0.60, -r * 0.86, r * 1.20, r * 1.16), 40 * 16, 100 * 16)


def _draw_traffic(painter: QPainter, r: float) -> None:
    """Car from above: body, glass, wheels."""
    painter.drawRoundedRect(QRectF(-r * 0.36, -r * 0.74, r * 0.72, r * 1.46), 3.0, 3.0)
    painter.drawRect(QRectF(-r * 0.24, -r * 0.40, r * 0.48, r * 0.24))
    painter.drawRect(QRectF(-r * 0.22, r * 0.10, r * 0.44, r * 0.20))
    for sx, sy in ((-0.46, -0.36), (0.46, -0.36), (-0.46, 0.38), (0.46, 0.38)):
        painter.drawEllipse(QPointF(r * sx, r * sy), r * 0.10, r * 0.16)


def _draw_sites(painter: QPainter, r: float) -> None:
    """Map pin. Not a plus / crosshair."""
    pin = QPainterPath()
    pin.moveTo(0.0, r * 0.90)
    pin.quadTo(-r * 0.70, r * 0.12, -r * 0.40, -r * 0.28)
    pin.arcTo(QRectF(-r * 0.40, -r * 0.88, r * 0.80, r * 0.80), 180, -180)
    pin.quadTo(r * 0.70, r * 0.12, 0.0, r * 0.90)
    painter.drawPath(pin)
    painter.drawEllipse(QPointF(0.0, -r * 0.46), r * 0.18, r * 0.18)


def _draw_stale(painter: QPainter, r: float) -> None:
    _line(painter, -r * 0.70, -r * 0.70, r * 0.70, r * 0.70)


def _draw_dead_reckon(painter: QPainter, r: float, ink: QColor) -> None:
    _stroke(painter, ink, dashed=True)
    painter.drawEllipse(QPointF(0.0, 0.0), r * 0.92, r * 0.92)
    _stroke(painter, ink)


def _draw_star(painter: QPainter, r: float) -> None:
    for deg in (90.0, 30.0, 150.0):
        rad = math.radians(deg)
        c, s = math.cos(rad), math.sin(rad)
        _line(painter, -r * 0.78 * c, -r * 0.78 * s, r * 0.78 * c, r * 0.78 * s)


def _draw_planet(painter: QPainter, r: float, detail: int) -> None:
    painter.drawEllipse(QPointF(0.0, 0.0), r * 0.70, r * 0.70)
    _line(painter, -r * 0.70, 0.0, r * 0.70, 0.0)
    if detail >= 3:
        painter.drawArc(
            QRectF(-r * 0.28, -r * 0.70, r * 0.56, r * 1.40),
            90 * 16,
            180 * 16,
        )


def _draw_moon(painter: QPainter, r: float) -> None:
    painter.drawArc(QRectF(-r * 0.70, -r * 0.70, r * 1.40, r * 1.40), 50 * 16, 260 * 16)
    painter.drawArc(QRectF(-r * 0.18, -r * 0.62, r * 1.16, r * 1.24), 70 * 16, 220 * 16)


def _draw_asteroid(painter: QPainter, r: float) -> None:
    rock = QPolygonF(
        [
            QPointF(0.0, -r * 0.82),
            QPointF(r * 0.72, -r * 0.28),
            QPointF(r * 0.42, r * 0.70),
            QPointF(-r * 0.52, r * 0.62),
            QPointF(-r * 0.78, -r * 0.18),
        ]
    )
    painter.drawPolygon(rock)


def _draw_probe(painter: QPainter, r: float) -> None:
    needle = QPolygonF(
        [
            QPointF(0.0, -r * 0.86),
            QPointF(r * 0.22, -r * 0.08),
            QPointF(0.0, r * 0.18),
            QPointF(-r * 0.22, -r * 0.08),
        ]
    )
    painter.drawPolygon(needle)
    _line(painter, 0.0, r * 0.18, 0.0, r * 0.82)
    _line(painter, -r * 0.36, r * 0.42, r * 0.36, r * 0.42)


def _draw_lagrange(painter: QPainter, r: float) -> None:
    top = QPolygonF(
        [
            QPointF(0.0, -r * 0.08),
            QPointF(-r * 0.52, -r * 0.82),
            QPointF(r * 0.52, -r * 0.82),
        ]
    )
    bot = QPolygonF(
        [
            QPointF(0.0, r * 0.08),
            QPointF(-r * 0.52, r * 0.82),
            QPointF(r * 0.52, r * 0.82),
        ]
    )
    painter.drawPolygon(top)
    painter.drawPolygon(bot)


_DRAWERS = {
    "flights": lambda p, r, d, **_: _draw_flights(p, r, d),
    "military": lambda p, r, d, **_: _draw_military(p, r, d),
    "drones": lambda p, r, d, **_: _draw_drones(p, r, d),
    "vessels": lambda p, r, d, **_: _draw_vessels(p, r, d),
    "satellites": lambda p, r, d, ink, **_: _draw_satellites(p, r, d, ink),
    "iss": lambda p, r, d, ink, **_: _draw_iss(p, r, ink),
    "cameras": lambda p, r, d, ink, look, **_: _draw_cameras(p, r, ink, look=look),
    "people": lambda p, r, d, ink, **_: _draw_people(p, r, ink),
    "radar": lambda p, r, d, **_: _draw_radar(p, r),
    "quakes": lambda p, r, d, mag, **_: _draw_quakes(p, r, d, mag),
    "fires": lambda p, r, d, ink, **_: _draw_fires(p, r, ink),
    "weather": lambda p, r, d, **_: _draw_weather(p, r, d),
    "radio": lambda p, r, d, **_: _draw_radio(p, r, d),
    "traffic": lambda p, r, d, **_: _draw_traffic(p, r),
    "sites": lambda p, r, d, **_: _draw_sites(p, r),
    "stale": lambda p, r, d, **_: _draw_stale(p, r),
    "dead-reckon": lambda p, r, d, ink, **_: _draw_dead_reckon(p, r, ink),
    "star": lambda p, r, d, **_: _draw_star(p, r),
    "planet": lambda p, r, d, **_: _draw_planet(p, r, d),
    "moon": lambda p, r, d, **_: _draw_moon(p, r),
    "asteroid": lambda p, r, d, **_: _draw_asteroid(p, r),
    "probe": lambda p, r, d, **_: _draw_probe(p, r),
    "lagrange": lambda p, r, d, **_: _draw_lagrange(p, r),
}


def paint_mark(
    painter: QPainter,
    cx: float,
    cy: float,
    kind: str,
    *,
    band: str = "city",
    heading_deg: float | None = None,
    freshness: str = "",
    hot: bool = False,
    look: bool = False,
    mag: float | None = None,
    ink: QColor | None = None,
    size: int | None = None,
) -> None:
    """Draw one mark at (cx, cy). Heading rotates air/sea so the nose is the track."""
    del hot
    if ink is None:
        ink = ink_for_kind(kind)
    px = float(size if size is not None else mark_size(band))
    r = px * 0.46
    detail = _detail(band)
    painter.save()
    painter.translate(QPointF(cx, cy))
    if kind in HEADING_KINDS and heading_deg is not None:
        painter.rotate(float(heading_deg))
    _stroke(painter, ink)
    drawer = _DRAWERS.get(kind)
    if drawer is not None:
        drawer(painter, r, detail, ink=ink, look=look, mag=mag)
    if kind not in OVERLAY_KINDS:
        if freshness == "stale":
            _draw_stale(painter, r)
        elif freshness == "dead-reckoned":
            _draw_dead_reckon(painter, r, ink)
    painter.restore()


def mark_image(
    kind: str,
    *,
    band: str = "city",
    heading_deg: float | None = None,
    freshness: str = "",
    look: bool = False,
    mag: float | None = None,
    ink: QColor | None = None,
    size: int | None = None,
) -> QImage:
    px = int(size if size is not None else ATLAS_PX)
    img = QImage(px, px, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    paint_mark(
        painter,
        px / 2.0,
        px / 2.0,
        kind,
        band=band,
        heading_deg=heading_deg,
        freshness=freshness,
        look=look,
        mag=mag,
        ink=ink,
        size=max(8, px - 4),
    )
    painter.end()
    return img


def mark_digest(kind: str, **kwargs: Any) -> str:
    img = mark_image(kind, **kwargs)
    ptr = img.constBits()
    return hashlib.sha256(bytes(ptr)).hexdigest()


def mark_data_uri(kind: str, **kwargs: Any) -> str:
    img = mark_image(kind, **kwargs)
    blob = QByteArray()
    buf = QBuffer(blob)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    b64 = bytes(blob.toBase64()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def atlas_data_uris() -> dict[str, str]:
    """Layer x band plus overlay and solar kinds. Cesium tints stay off; ink is baked."""
    from arelis.ui.earth_overlay import _ink

    out: dict[str, str] = {}
    for layer in LAYER_IDS:
        ink = _ink(layer, freshness="live")
        for band in BANDS:
            uri = mark_data_uri(layer, band=band, ink=ink)
            out[f"{layer}:{band}"] = uri
        out[layer] = out[f"{layer}:city"]
    for kind in SOLAR_KINDS:
        ink = ink_for_kind(kind)
        uri = mark_data_uri(kind, band="city", ink=ink)
        out[kind] = uri
        out[f"{kind}:city"] = uri
    stale = mark_data_uri("stale", ink=QColor(color("text_dim")))
    dead = mark_data_uri("dead-reckon", ink=QColor(color("text_dim")))
    out["stale"] = stale
    out["dead-reckon"] = dead
    return out
