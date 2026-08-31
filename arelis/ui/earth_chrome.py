"""Earth HUD extras: band type, coach, picture-key chips, paste field."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QPainter, QPen

from arelis.earth.copy import band_phrase, coach_line, live_chip_label
from arelis.earth.key_paste import missing_picture_keys, save_earth_key
from arelis.ui.theme import color

_CHIP_H = 22
_GAP = 4
_PAD = 8


MARK_HINTS: tuple[tuple[str, str], ...] = (
    ("chevron", "plane"),
    ("hull", "ship"),
    ("box + panels", "satellite"),
    ("ring", "ISS"),
    ("square", "camera"),
    ("ember", "fire"),
    ("triangle", "weather"),
    ("open circle", "quake"),
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
