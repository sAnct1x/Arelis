"""Find field on the Earth plate. Type a city, address, contact, or home."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFontMetrics, QKeyEvent, QPainter, QPen

from arelis.earth.goto import GotoHit, suggest
from arelis.ui.theme import color

_FIELD_H = 28
_FIELD_MAX_W = 380
_ROW_H = 22
_PAD = 10
_MAX_Q = 120
PLACEHOLDER = "Find a city, address, or contact"
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


def _hose_find(panel: Any, on: bool) -> None:
    host = getattr(panel, "_globe_host", None)
    push = getattr(host, "push_find", None)
    if callable(push):
        try:
            push(bool(on))
        except Exception:
            pass


def _hold_keys(panel: Any, on: bool) -> None:
    """Cesium keeps HWND focus. Grab the keyboard while Find is open."""
    _hose_find(panel, on)
    hud = getattr(panel, "_earth_hud", None)
    target = hud if hud is not None else panel
    try:
        if on:
            target.grabKeyboard()
            target.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            target.releaseKeyboard()
    except Exception:
        pass


def typed_text(event: QKeyEvent) -> str:
    """Chromium often delivers a key with an empty text() over the hose."""
    raw = event.text() or ""
    if raw and raw.isprintable() and raw != "\x00":
        return raw
    key = int(event.key())
    if int(Qt.Key.Key_A) <= key <= int(Qt.Key.Key_Z):
        letter = chr(ord("A") + (key - int(Qt.Key.Key_A)))
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        return letter if shift else letter.lower()
    if int(Qt.Key.Key_0) <= key <= int(Qt.Key.Key_9):
        return chr(ord("0") + (key - int(Qt.Key.Key_0)))
    extras = {
        int(Qt.Key.Key_Space): " ",
        int(Qt.Key.Key_Comma): ",",
        int(Qt.Key.Key_Period): ".",
        int(Qt.Key.Key_Minus): "-",
        int(Qt.Key.Key_Apostrophe): "'",
        int(Qt.Key.Key_NumberSign): "#",
        int(Qt.Key.Key_Slash): "/",
    }
    return extras.get(key, "")


def open_find(panel: Any) -> None:
    ensure_find(panel)
    panel._earth_find_on = True
    panel._earth_find_ix = 0
    refresh(panel)
    _hold_keys(panel, True)
    panel.update()


def close_find(panel: Any) -> None:
    ensure_find(panel)
    panel._earth_find_on = False
    panel._earth_find_q = ""
    panel._earth_find_hits = []
    panel._earth_find_ix = 0
    _hold_keys(panel, False)
    panel.update()


def refresh(panel: Any, *, geocode: bool = False) -> None:
    from arelis.earth.geocode import looks_like_address, search_address
    from arelis.earth.runtime import get_earth

    ensure_find(panel)
    zone = get_earth()
    q = panel._earth_find_q
    hits = suggest(q, zone) if q.strip() else []
    if geocode and looks_like_address(q):
        extra = search_address(q)
        seen = {(h.kind, h.name.casefold()) for h in hits}
        merged = []
        for hit in extra:
            key = (hit.kind, hit.name.casefold())
            if key in seen:
                continue
            seen.add(key)
            merged.append(hit)
        hits = merged + hits
    panel._earth_find_hits = hits
    n = len(panel._earth_find_hits)
    if n:
        panel._earth_find_ix = max(0, min(int(panel._earth_find_ix), n - 1))
    else:
        panel._earth_find_ix = 0


def _arm_geocode(panel: Any) -> None:
    from arelis.earth.geocode import looks_like_address

    if not looks_like_address(panel._earth_find_q):
        return
    try:
        from PySide6.QtCore import QTimer
    except Exception:
        return
    timer = getattr(panel, "_earth_geocode_timer", None)
    if timer is None:
        timer = QTimer(panel)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: _run_geocode(panel))
        panel._earth_geocode_timer = timer
    timer.start(420)


def _run_geocode(panel: Any) -> None:
    if not getattr(panel, "_earth_find_on", False):
        return
    refresh(panel, geocode=True)
    panel.update()


def layout_find(
    fm: QFontMetrics, left: int, top: int, width: int, *, open_: bool, hits: list[GotoHit]
) -> tuple[QRect, QRect, list[tuple[int, QRect]]]:
    field = QRect(left + _PAD, top + 6, min(_FIELD_MAX_W, max(80, width - 2 * _PAD)), _FIELD_H)
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
    if panel._earth_find_on and not panel._earth_find_hits:
        refresh(panel)
    hits = list(panel._earth_find_hits) if panel._earth_find_on else []
    box, field, rows = layout_find(
        painter.fontMetrics(), left, top, width, open_=panel._earth_find_on, hits=hits
    )
    panel._earth_find_box = QRect(box)
    panel._earth_find_field = QRect(field)
    panel._earth_find_hit_rects = rows
    painter.setPen(QPen(color("edge_hot") if panel._earth_find_on else color("edge"), 1))
    painter.setBrush(color("well") if panel._earth_find_on else color("sunk"))
    painter.drawRoundedRect(field, 4, 4)
    query = panel._earth_find_q if panel._earth_find_on and panel._earth_find_q else ""
    if not query:
        painter.setPen(color("text_dim"))
        text = PLACEHOLDER if panel._earth_find_on else f"{HINT}  ·  {PLACEHOLDER}"
    else:
        painter.setPen(color("text"))
        text = query
    painter.drawText(
        field.adjusted(10, 0, -10, 0),
        int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
        text,
    )
    if panel._earth_find_on and query:
        caret_x = field.left() + 10 + painter.fontMetrics().horizontalAdvance(query)
        caret = QRect(caret_x, field.top() + 6, 2, field.height() - 12)
        painter.fillRect(caret, color("accent"))
    if panel._earth_find_on:
        for i, rect in rows:
            hit = hits[i]
            on = i == panel._earth_find_ix
            painter.setPen(color("text") if on else color("text_dim"))
            label = f"{hit.name}  {hit.kind}"
            painter.drawText(
                rect.adjusted(10, 0, -10, 0),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                label,
            )
    return box


def hit_find(panel: Any, px: float, py: float) -> str | int | None:
    ensure_find(panel)
    if panel._earth_find_field.contains(int(px), int(py)):
        return "field"
    for i, rect in panel._earth_find_hit_rects:
        if rect.contains(int(px), int(py)):
            return i
    return None


def _touch_find(panel: Any) -> None:
    panel.update()
    hud = getattr(panel, "_earth_hud", None)
    if hud is not None:
        hud.update()


def type_find(panel: Any, text: str) -> None:
    ensure_find(panel)
    panel._earth_find_on = True
    panel._earth_find_q = (panel._earth_find_q + text)[:_MAX_Q]
    _hold_keys(panel, True)
    refresh(panel)
    _arm_geocode(panel)
    _touch_find(panel)


def backspace_find(panel: Any) -> None:
    ensure_find(panel)
    panel._earth_find_q = panel._earth_find_q[:-1]
    refresh(panel)
    _arm_geocode(panel)
    _touch_find(panel)


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
    q = str(getattr(panel, "_earth_find_q", "") or "").strip()
    if hit is None and q:
        from arelis.earth.goto import resolve_place
        from arelis.earth.runtime import get_earth

        hit = resolve_place(q, get_earth())
    if hit is None and q:
        from arelis.earth.geocode import search_address

        extra = search_address(q, force=True)
        hit = extra[0] if extra else None
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
