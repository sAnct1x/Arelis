"""Right-side Reality tiles. Same HUD glass — not a second window.

Radio and cameras stay as marks. Their names live in this list. A camera
click peeks a publisher still; View enlarges the live look; More is public
facts only — no stream URL, no open-port IP.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from arelis.ui.theme import color

_DOCK_W = 320
_ROW_H = 22
_LIST_CAP = 16
_PEEK_H = 140
_LIVE_H = 360


def _dock(panel) -> dict[str, Any]:
    raw = getattr(panel, "_earth_dock", None)
    return raw if isinstance(raw, dict) else {}


def close_earth_dock(panel) -> None:
    panel._earth_dock = None
    panel._earth_dock_box = QRect()
    panel._earth_dock_hits = []
    closer = getattr(panel, "_close_earth_look", None)
    if callable(closer):
        closer()
    panel.update()


def open_radio_dock(panel, *, tune_id: str = "") -> None:
    if not tune_id:
        closer = getattr(panel, "_close_earth_look", None)
        if callable(closer):
            closer()
    panel._earth_dock = {"kind": "radio", "mode": "list", "entity_id": tune_id}
    if tune_id:
        _tune(panel, tune_id)
    panel.update()


def open_camera_dock(panel, entity_id: str, *, mode: str = "peek") -> None:
    panel._earth_dock = {
        "kind": "camera",
        "mode": mode if mode in {"list", "peek", "live", "more"} else "peek",
        "entity_id": entity_id,
    }
    panel.update()


def open_camera_list(panel) -> None:
    panel._earth_dock = {"kind": "camera", "mode": "list", "entity_id": ""}
    panel.update()


def expand_earth_look(panel) -> None:
    dock = _dock(panel)
    if dock.get("kind") == "camera":
        dock["mode"] = "live"
        panel._earth_dock = dock
        panel.update()


def radio_rows(zone) -> list[Any]:
    if zone is None:
        return []
    rows = [ent for ent in zone.visible() if ent.layer == "radio"]
    rows.sort(key=lambda e: (e.label or e.id).casefold())
    return rows[:_LIST_CAP]


def camera_rows(zone) -> list[Any]:
    if zone is None:
        return []
    rows = [ent for ent in zone.visible() if ent.layer == "cameras"]
    rows.sort(key=lambda e: (e.label or e.id).casefold())
    return rows[:_LIST_CAP]


def camera_facts(ent) -> str:
    """Public facts only. Stream URLs and raw IPs stay out."""
    meta = getattr(ent, "meta", None) or {}
    lat = meta.get("lat")
    lon = meta.get("lon")
    lines = [str(ent.label or ent.id), "camera"]
    src = str(getattr(ent, "source", "") or "").strip()
    if src:
        lines.append(src)
    where = []
    for key in ("city", "country", "operator", "owner", "agency"):
        val = str(meta.get(key) or "").strip()
        if val and val not in where:
            where.append(val)
    if where:
        lines.append(" · ".join(where))
    try:
        lines.append(f"{float(lat):.4f}°, {float(lon):.4f}°")
    except (TypeError, ValueError):
        pass
    fresh = str(getattr(ent, "freshness", "") or "").strip()
    if fresh:
        lines.append(fresh)
    note = ""
    cov = getattr(ent, "coverage", None)
    if cov is not None:
        note = str(getattr(cov, "note", "") or "").strip()
    if note:
        lines.append(note)
    return "\n".join(lines)


def radio_facts(ent) -> str:
    meta = getattr(ent, "meta", None) or {}
    lines = [str(ent.label or ent.id), "radio"]
    src = str(getattr(ent, "source", "") or "").strip()
    if src:
        lines.append(src)
    country = str(meta.get("country") or "").strip()
    if country:
        lines.append(country)
    home = str(meta.get("homepage") or "").strip()
    if home.startswith("https://") or home.startswith("http://"):
        lines.append(home[:80])
    try:
        lines.append(f"{float(meta.get('lat')):.3f}°, {float(meta.get('lon')):.3f}°")
    except (TypeError, ValueError):
        pass
    return "\n".join(lines)


def _tune(panel, entity_id: str) -> None:
    from arelis.earth.runtime import get_earth

    zone = get_earth()
    hit = zone.get(entity_id) if zone is not None else None
    if hit is None:
        return
    opener = getattr(panel, "_open_earth_look", None)
    if callable(opener):
        opener(hit)


def hit_earth_dock(panel, px: float, py: float) -> str | None:
    for action, rect in getattr(panel, "_earth_dock_hits", []) or []:
        if rect.contains(int(px), int(py)):
            return action
    return None


def handle_earth_dock(panel, action: str) -> bool:
    if not action:
        return False
    dock = _dock(panel)
    if action == "close":
        close_earth_dock(panel)
        return True
    if action == "view":
        dock["mode"] = "live"
        panel._earth_dock = dock
        panel.update()
        return True
    if action == "more":
        dock["mode"] = "more"
        panel._earth_dock = dock
        panel.update()
        return True
    if action == "peek":
        dock["mode"] = "peek"
        panel._earth_dock = dock
        panel.update()
        return True
    if action.startswith("tune:"):
        eid = action[5:]
        dock["kind"] = "radio"
        dock["mode"] = "list"
        dock["entity_id"] = eid
        panel._earth_dock = dock
        _tune(panel, eid)
        panel.update()
        return True
    if action.startswith("cam:"):
        eid = action[4:]
        open_camera_dock(panel, eid, mode="peek")
        from arelis.earth.runtime import get_earth

        zone = get_earth()
        hit = zone.get(eid) if zone is not None else None
        if hit is not None:
            opener = getattr(panel, "_open_earth_look", None)
            if callable(opener):
                opener(hit)
        return True
    return False


def paint_earth_dock(panel, painter: QPainter) -> None:
    panel._earth_dock_hits = []
    dock = _dock(panel)
    if not dock:
        panel._earth_dock_box = QRect()
        return
    from arelis.earth.runtime import get_earth

    zone = get_earth()
    if zone is None or not zone.active:
        panel._earth_dock_box = QRect()
        return
    kind = str(dock.get("kind") or "")
    mode = str(dock.get("mode") or "list")
    eid = str(dock.get("entity_id") or "")
    if kind == "radio":
        _paint_radio(panel, painter, zone, mode, eid)
        return
    if kind == "camera":
        _paint_camera(panel, painter, zone, mode, eid)
        return
    panel._earth_dock_box = QRect()


def _frame_well_h(panel, mode: str) -> int:
    """Reserve the still before the JPEG lands. Mask must match this."""
    if mode == "list":
        return 0
    want = _LIVE_H if mode == "live" else _PEEK_H
    return min(want, max(160, int(panel.height()) - 200))


def _draw_look_still(painter: QPainter, target: QRect, frame: QImage) -> None:
    """Fit the whole still in the well. Do not stamp a DPR sliver."""
    painter.fillRect(target, QColor(12, 10, 8))
    if frame is None or frame.isNull() or target.width() < 8 or target.height() < 8:
        return
    img = QImage(frame)
    img.setDevicePixelRatio(1.0)
    scaled = img.scaled(
        target.size(),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = target.x() + max(0, (target.width() - scaled.width()) // 2)
    y = target.y() + max(0, (target.height() - scaled.height()) // 2)
    painter.drawImage(x, y, scaled)


def _dock_box(panel, h: int) -> QRect:
    top = 48
    chip = getattr(panel, "_earth_chip_box", QRect())
    if chip is not None and not chip.isEmpty():
        top = max(top, chip.bottom() + 8)
    h = min(h, max(120, panel.height() - top - 16))
    left = max(8, panel.width() - _DOCK_W - 12)
    return QRect(left, top, _DOCK_W, h)


def _chip(panel, painter: QPainter, rect: QRect, label: str, action: str, *, on: bool) -> None:
    panel._paint_chip(painter, rect, label, on=on)
    panel._earth_dock_hits.append((action, QRect(rect)))


def _paint_radio(panel, painter: QPainter, zone, mode: str, eid: str) -> None:
    rows = radio_rows(zone)
    title_h = 28
    facts = ""
    hit = zone.get(eid) if eid else None
    if mode == "more" and hit is not None:
        facts = radio_facts(hit)
    fm = painter.fontMetrics()
    facts_h = panel._wrapped_h(fm, facts, _DOCK_W - 24) + 8 if facts else 0
    h = title_h + 28 + len(rows) * _ROW_H + facts_h + 12
    box = _dock_box(panel, h)
    panel._earth_dock_box = QRect(box)
    panel._paint_plate(painter, box, radius=6)
    painter.setPen(color("text"))
    painter.drawText(box.left() + 12, box.top() + 18, "Radio")
    painter.setPen(color("text_dim"))
    painter.drawText(
        box.left() + 70,
        box.top() + 18,
        f"{len(rows)} in view" if rows else "none in this view",
    )
    close = QRect(box.right() - 72, box.top() + 6, 60, 20)
    _chip(panel, painter, close, "close", "close", on=False)
    y = box.top() + title_h
    wrap = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    for ent in rows:
        row = QRect(box.left() + 8, y, box.width() - 16, _ROW_H)
        on = ent.id == eid
        if on:
            painter.fillRect(row, color("glass_fill"))
        painter.setPen(color("text") if on else color("text_dim"))
        painter.drawText(row.adjusted(6, 0, -4, 0), wrap, ent.label or ent.id)
        panel._earth_dock_hits.append((f"tune:{ent.id}", QRect(row)))
        y += _ROW_H
    if facts:
        painter.setPen(color("text"))
        painter.drawText(
            QRect(box.left() + 12, y + 4, box.width() - 24, facts_h),
            int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap),
            facts,
        )
    if hit is not None:
        _chip(
            panel,
            painter,
            QRect(box.left() + 12, box.bottom() - 26, 72, 20),
            "more",
            "more",
            on=mode == "more",
        )


def _paint_camera(panel, painter: QPainter, zone, mode: str, eid: str) -> None:
    if mode == "list":
        rows = camera_rows(zone)
        h = 56 + len(rows) * _ROW_H
        box = _dock_box(panel, h)
        panel._earth_dock_box = QRect(box)
        panel._paint_plate(painter, box, radius=6)
        painter.setPen(color("text"))
        painter.drawText(box.left() + 12, box.top() + 18, "Cameras")
        close = QRect(box.right() - 72, box.top() + 6, 60, 20)
        _chip(panel, painter, close, "close", "close", on=False)
        y = box.top() + 32
        wrap = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for ent in rows:
            row = QRect(box.left() + 8, y, box.width() - 16, _ROW_H)
            painter.setPen(color("text"))
            painter.drawText(row.adjusted(6, 0, -4, 0), wrap, ent.label or ent.id)
            panel._earth_dock_hits.append((f"cam:{ent.id}", QRect(row)))
            y += _ROW_H
        return
    hit = zone.get(eid) if eid else None
    frame = getattr(panel, "_look_frame", None)
    has_frame = frame is not None and hasattr(frame, "isNull") and not frame.isNull()
    frame_h = _frame_well_h(panel, mode)
    if has_frame and frame_h:
        img_w = max(1, frame.width())
        img_h = max(1, frame.height())
        fit = int((_DOCK_W - 20) * img_h / img_w)
        frame_h = max(80, min(frame_h, fit))
    facts = camera_facts(hit) if hit is not None and mode == "more" else ""
    fm = painter.fontMetrics()
    facts_h = panel._wrapped_h(fm, facts, _DOCK_W - 24) + 8 if facts else 0
    title = (hit.label if hit is not None else "Camera")[:42]
    h = 56 + frame_h + facts_h + 36
    box = _dock_box(panel, h)
    panel._earth_dock_box = QRect(box)
    panel._paint_plate(painter, box, radius=6)
    painter.setPen(color("text"))
    painter.drawText(box.left() + 12, box.top() + 18, title)
    close = QRect(box.right() - 72, box.top() + 6, 60, 20)
    _chip(panel, painter, close, "close", "close", on=False)
    y = box.top() + 30
    if frame_h:
        target = QRect(box.left() + 10, y, box.width() - 20, frame_h)
        if has_frame:
            _draw_look_still(painter, target, frame)
        else:
            painter.fillRect(target, QColor(12, 10, 8))
            painter.setPen(color("text_dim"))
            status = str(getattr(panel, "_look_status", "") or "publisher still…")
            painter.drawText(target, int(Qt.AlignmentFlag.AlignCenter), status)
        y += frame_h + 6
    if facts:
        painter.setPen(color("text"))
        painter.drawText(
            QRect(box.left() + 12, y, box.width() - 24, facts_h),
            int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap),
            facts,
        )
        y += facts_h
    x = box.left() + 12
    _chip(panel, painter, QRect(x, box.bottom() - 26, 64, 20), "view", "view", on=mode == "live")
    more = QRect(x + 72, box.bottom() - 26, 64, 20)
    _chip(panel, painter, more, "more", "more", on=mode == "more")
    if mode != "peek":
        _chip(panel, painter, QRect(x + 144, box.bottom() - 26, 64, 20), "peek", "peek", on=False)
