"""Find field on the Earth plate. Type a city, country, contact, or home."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFontMetrics, QPainter, QPen

from arelis.earth.goto import GotoHit, suggest
from arelis.ui.theme import color

_FIELD_H = 22
_ROW_H = 20
_PAD = 8
PLACEHOLDER = "Find a city, country, or contact"
HINT = "/ find"


def ensure_find(panel: Any) -> None:
    if getattr(panel, "_earth_find_on", None) is None:
        panel._earth_find_on = False
    if getattr(panel, "_earth_find_q", None) is None:
        panel._earth_find_q = ""
    if getattr(panel, "_earth_find_ix", None) is None:
        panel._earth_find_ix = 0
    if getattr(panel, "_earth_find_hits", None) is None:
        panel._earth_find_hits = []
    if getattr(panel, "_earth_find_box", None) is None:
        panel._earth_find_box = QRect()
    if getattr(panel, "_earth_find_field", None) is None:
        panel._earth_find_field = QRect()
    if getattr(panel, "_earth_find_hit_rects", None) is None:
        panel._earth_find_hit_rects = []


def open_find(panel: Any) -> None:
    ensure_find(panel)
    panel._earth_find_on = True
    panel._earth_find_ix = 0
    refresh(panel)
    panel.update()


def close_find(panel: Any) -> None:
    ensure_find(panel)
    panel._earth_find_on = False
    panel._earth_find_q = ""
    panel._earth_find_hits = []
    panel._earth_find_ix = 0
    panel.update()


def refresh(panel: Any) -> None:
    from arelis.earth.runtime import get_earth

    ensure_find(panel)
    zone = get_earth()
    panel._earth_find_hits = suggest(panel._earth_find_q, zone)
    n = len(panel._earth_find_hits)
    if n:
        panel._earth_find_ix = max(0, min(int(panel._earth_find_ix), n - 1))
    else:
        panel._earth_find_ix = 0


def layout_find(
    fm: QFontMetrics, left: int, top: int, width: int, *, open_: bool, hits: list[GotoHit]
) -> tuple[QRect, QRect, list[tuple[int, QRect]]]:
    field = QRect(left + _PAD, top + 4, max(80, width - 2 * _PAD), _FIELD_H)
    rows: list[tuple[int, QRect]] = []
    y = field.bottom() + 4
    if open_:
        for i, _hit in enumerate(hits[:8]):
            rows.append((i, QRect(field.left(), y, field.width(), _ROW_H)))
            y += _ROW_H
    bottom = y + 4
    box = QRect(left, top, width, max(_FIELD_H + 8, bottom - top))
    return box, field, rows


def paint_find(panel: Any, painter: QPainter, left: int, top: int, width: int) -> QRect:
    from arelis.earth.runtime import get_earth

    ensure_find(panel)
    zone = get_earth()
    if zone is None or not zone.active:
        panel._earth_find_box = QRect()
        panel._earth_find_field = QRect()
        panel._earth_find_hit_rects = []
        return QRect()
    refresh(panel) if panel._earth_find_on else None
    hits = list(panel._earth_find_hits) if panel._earth_find_on else []
    box, field, rows = layout_find(
        painter.fontMetrics(), left, top, width, open_=panel._earth_find_on, hits=hits
    )
    panel._earth_find_box = QRect(box)
    panel._earth_find_field = QRect(field)
    panel._earth_find_hit_rects = rows
    painter.setPen(QPen(color("edge_hot") if panel._earth_find_on else color("edge"), 1))
    painter.setBrush(color("glass_fill"))
    painter.drawRoundedRect(field, 4, 4)
    text = panel._earth_find_q if panel._earth_find_on and panel._earth_find_q else ""
    if not text:
        painter.setPen(color("text_dim"))
        text = PLACEHOLDER if panel._earth_find_on else f"{HINT}  ·  {PLACEHOLDER}"
    else:
        painter.setPen(color("text"))
    painter.drawText(field.adjusted(8, 0, -8, 0), int(Qt.AlignmentFlag.AlignVCenter), text)
    if panel._earth_find_on:
        for i, rect in rows:
            hit = hits[i]
            on = i == panel._earth_find_ix
            painter.setPen(color("text") if on else color("text_dim"))
            label = f"{hit.name}  {hit.kind}"
            painter.drawText(rect.adjusted(8, 0, -8, 0), int(Qt.AlignmentFlag.AlignVCenter), label)
    return box


def hit_find(panel: Any, px: float, py: float) -> str | int | None:
    ensure_find(panel)
    if panel._earth_find_field.contains(int(px), int(py)):
        return "field"
    for i, rect in panel._earth_find_hit_rects:
        if rect.contains(int(px), int(py)):
            return i
    return None


def type_find(panel: Any, text: str) -> None:
    ensure_find(panel)
    panel._earth_find_on = True
    panel._earth_find_q = (panel._earth_find_q + text)[:80]
    refresh(panel)
    panel.update()


def backspace_find(panel: Any) -> None:
    ensure_find(panel)
    panel._earth_find_q = panel._earth_find_q[:-1]
    refresh(panel)
    panel.update()


def move_find(panel: Any, delta: int) -> None:
    ensure_find(panel)
    n = len(panel._earth_find_hits)
    if not n:
        return
    panel._earth_find_ix = (int(panel._earth_find_ix) + delta) % n
    panel.update()


def chosen(panel: Any, index: int | None = None) -> GotoHit | None:
    ensure_find(panel)
    hits = list(panel._earth_find_hits)
    if not hits:
        return None
    i = int(panel._earth_find_ix if index is None else index)
    if i < 0 or i >= len(hits):
        return None
    return hits[i]


def apply_goto(panel: Any, index: int | None = None) -> bool:
    hit = chosen(panel, index)
    close_find(panel)
    if hit is None:
        return False
    if hit.entity_id:
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        ent = zone.get(hit.entity_id) if zone is not None else None
        if ent is not None:
            panel._select_earth_entity(ent, ride=ent.layer == "cameras")
            return True
    panel._select_earth_place(hit.as_place())
    return True
