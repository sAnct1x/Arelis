"""Filament desk verbs: aperture host, glow, tile flick, palm scroll.

The C920 maps onto the live 1/2/3 HWND union. Each hand paints on the
top HWND under its midpoint so a floating tile cannot hide the cursor.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QAbstractSlider,
    QApplication,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QWidget,
)

from arelis.spatial.hands_log import emit as hands_emit
from arelis.spatial.hands_log import sample as hands_sample
from arelis.spatial.scene import image_to_world
from arelis.ui.hand_cursor import clear_on, paint_on

RIM = 28
FLICK_PX_S = 380.0
FLICK_DT = 0.42
SCROLL_PAGE = 3.6


def span_pixel(nx: float, ny: float, width: int, height: int) -> tuple[int, int]:
    """0–1 of the live HWND union → pixel. The HWND *is* the 1/2/3 span."""
    w, h = max(1, int(width)), max(1, int(height))
    x = min(1.0, max(0.0, float(nx)))
    y = min(1.0, max(0.0, float(ny)))
    return int(x * (w - 1)), int(y * (h - 1))


def on_span_edge(nx: float, ny: float, *, margin: float = 0.03) -> bool:
    return (
        float(nx) < margin
        or float(nx) > 1.0 - margin
        or float(ny) < margin
        or float(ny) > 1.0 - margin
    )


def scroll_steps(dy_norm: float, page: int) -> int:
    """Image-space dy → scrollbar steps. Hand up (dy < 0) scrolls the list up."""
    if abs(dy_norm) < 1e-4:
        return 0
    raw = dy_norm * max(8, int(page)) * SCROLL_PAGE
    if raw > 0:
        return max(1, int(raw))
    return min(-1, int(raw))


def is_tile_chrome(tile: QWidget, global_pt: QPoint, *, rim: int = RIM) -> bool:
    """Rim / title / empty glass. Not a list, input, or conversation viewport."""
    local = tile.mapFromGlobal(global_pt)
    rect = tile.rect()
    if not rect.contains(local):
        return False
    child = tile.childAt(local)
    cur = child
    while cur is not None and cur is not tile:
        if isinstance(
            cur,
            (
                QAbstractScrollArea,
                QAbstractItemView,
                QLineEdit,
                QTextEdit,
                QPlainTextEdit,
            ),
        ):
            return False
        obj = str(cur.objectName() or "")
        if obj in ("FilamentChatBody", "ChatLog", "HistoryList", "WorkspaceTree"):
            return False
        cur = cur.parentWidget()
    if child is None:
        return True
    return (
        local.x() < rim
        or local.y() < rim
        or local.x() > rect.width() - rim
        or local.y() > rect.height() - rim
    )


def clamp_rect_to_desks(rect: QRect, desks: list[QRect]) -> QRect:
    """Keep the plate touching a live desk. A flick may cross, then park."""
    if not desks or not rect.isValid():
        return QRect(rect)
    if any(desk.intersects(rect) for desk in desks):
        return QRect(rect)
    cx, cy = rect.center().x(), rect.center().y()
    desk = min(
        desks,
        key=lambda d: math.hypot(d.center().x() - cx, d.center().y() - cy),
    )
    x = min(max(rect.x(), desk.left()), max(desk.left(), desk.right() - rect.width() + 1))
    y = min(max(rect.y(), desk.top()), max(desk.top(), desk.bottom() - rect.height() + 1))
    return QRect(int(x), int(y), rect.width(), rect.height())


def flick_rect(
    geo: QRect,
    vx: float,
    vy: float,
    *,
    dt: float = FLICK_DT,
    desks: list[QRect] | None = None,
) -> QRect:
    dest = QRect(geo)
    dest.translate(int(vx * dt), int(vy * dt))
    if desks:
        dest = clamp_rect_to_desks(dest, desks)
    return dest


def apply_desk(window, apertures: list, reach: float) -> None:
    """Cursor, glow, tile hold / flick, palm scroll. Filament only."""
    from arelis.ui.theme import active_theme

    if active_theme() != "filament":
        _clear_all(window)
        return
    if not apertures:
        paint_cursors(window, [])
        glow_hits(window, [])
        st = getattr(window, "_hands_desk", None)
        if st is not None:
            for who in list(st.get("holds") or {}):
                _release_tile(window, who)
            st["armed"] = {}
            st["scroll_y"] = {}
        return
    paint_cursors(window, apertures)
    glow_hits(window, apertures)
    apply_verbs(window, apertures, reach)
    mid = apertures[0]
    mx = (mid[0][0] + mid[1][0]) * 0.5
    my = (mid[0][1] + mid[1][1]) * 0.5
    if on_span_edge(mx, my):
        hands_sample(
            "span_edge",
            x=round(mx, 4),
            y=round(my, 4),
            span=int(getattr(window, "_filament_span", 1) or 1),
        )


def paint_cursors(window, apertures: list) -> None:
    prev = list(getattr(window, "_hand_cursor_hosts", ()) or ())
    if not apertures:
        for host in prev:
            clear_on(host)
        clear_on(window)
        world = getattr(window, "world_window", None)
        if world is not None:
            clear_on(world)
        window._hand_cursor_hosts = []
        return
    groups: dict[int, tuple[QWidget, list]] = {}
    for thumb, index, closed in apertures:
        mx = (float(thumb[0]) + float(index[0])) * 0.5
        my = (float(thumb[1]) + float(index[1])) * 0.5
        px, py = span_pixel(mx, my, window.width(), window.height())
        global_pt = window.mapToGlobal(QPoint(px, py))
        host = hwnd_under(window, global_pt)
        row = groups.setdefault(id(host), (host, []))
        row[1].append(
            (
                _remap_xy(thumb, window, host),
                _remap_xy(index, window, host),
                bool(closed),
            )
        )
    used: list[QWidget] = []
    for host, items in groups.values():
        paint_on(host, items)
        used.append(host)
    for host in prev:
        if host not in used:
            clear_on(host)
    window._hand_cursor_hosts = used


def glow_hits(window, apertures: list) -> None:
    field = getattr(window, "_filament", None)
    st = _state(window)
    hot: set[str] = set()
    now_tiles: list[QWidget] = []
    for thumb, index, _closed in apertures:
        mx = (float(thumb[0]) + float(index[0])) * 0.5
        my = (float(thumb[1]) + float(index[1])) * 0.5
        px, py = span_pixel(mx, my, window.width(), window.height())
        local = QPoint(px, py)
        if field is not None and hasattr(field, "hit_float"):
            name = field.hit_float(local, window.rect())
            if name:
                hot.add(name)
        found = tile_under(window, window.mapToGlobal(local))
        if found is not None:
            widget, name = found
            hot.add(name)
            now_tiles.append(widget)
    if field is not None and hasattr(field, "set_hot"):
        field.set_hot(hot)
    for widget in st["hot_tiles"]:
        if widget not in now_tiles:
            _set_tile_hot(widget, False)
    for widget in now_tiles:
        _set_tile_hot(widget, True)
    st["hot_tiles"] = now_tiles


def apply_verbs(window, apertures: list, reach: float) -> None:
    tracks = tuple(getattr(window.spatial, "last_tracks", ()) or ())
    st = _state(window)
    live: set[str] = set()
    w, h = max(1, window.width()), max(1, window.height())
    by_who: dict[str, object] = {}
    for track in tracks:
        who = str(getattr(track, "who", "") or "")
        if who:
            by_who[who] = track
    for track in tracks:
        who = str(getattr(track, "who", "") or "")
        hand = getattr(track, "hand", None)
        if not who or hand is None:
            continue
        live.add(who)
        st_name = str(getattr(track, "state", "") or "idle")
        dragging = bool(getattr(track, "dragging", False))
        frozen = getattr(track, "frozen_xy", None)
        if st_name == "pinch" and not dragging and frozen is not None:
            nx, ny = image_to_world(*frozen, reach=reach)
        else:
            pointer = hand.pointer_xy()
            nx, ny = image_to_world(*pointer, reach=reach)
        px, py = span_pixel(nx, ny, w, h)
        global_pt = window.mapToGlobal(QPoint(px, py))
        if st_name == "pinch" and not dragging:
            found = tile_under(window, global_pt)
            if found is not None and is_tile_chrome(found[0], global_pt):
                st["armed"][who] = found
            else:
                st["armed"].pop(who, None)
            continue
        if st_name == "pinch" and dragging:
            _drag_tile(window, who, global_pt)
            continue
        if st_name in ("idle", "lost") or st_name == "open":
            _palm_scroll(window, who, global_pt, ny)
        else:
            st["scroll_y"].pop(who, None)
    for who in list(st["holds"]):
        if who not in live or not _still_dragging(by_who.get(who)):
            _release_tile(window, who)
    for who in list(st["armed"]):
        if who not in live:
            st["armed"].pop(who, None)
    for who in list(st["scroll_y"]):
        if who not in live:
            st["scroll_y"].pop(who, None)


def deliver_click(window, click: object, reach: float) -> None:
    """Pinch tap on the frozen hit. Not a chat turn."""
    from arelis.ui.theme import active_theme

    fx = float(getattr(click, "x", 0.5))
    fy = float(getattr(click, "y", 0.5))
    nx, ny = image_to_world(fx, fy, reach=reach)
    px, py = span_pixel(nx, ny, window.width(), window.height())
    local = QPoint(px, py)
    global_pt = window.mapToGlobal(local)
    hit_name = "miss"
    if active_theme() == "filament":
        field = getattr(window, "_filament", None)
        if field is not None and hasattr(field, "hit_float"):
            name = field.hit_float(local, window.rect())
            if name:
                hit_name = name
                floats = getattr(window, "_filament_floats", None)
                if floats is not None:
                    floats.opened.emit(name)
                hands_emit("click_hit", hit=name, x=round(nx, 4), y=round(ny, 4))
                return
    app = QApplication.instance()
    widget = app.widgetAt(global_pt) if app is not None else None
    if widget is not None:
        obj = str(widget.objectName() or widget.__class__.__name__)
        hit_name = obj
        click_fn = getattr(widget, "click", None)
        if callable(click_fn) and widget.isEnabled() and widget.isVisible():
            click_fn()
            hands_emit("click_hit", hit=obj, x=round(nx, 4), y=round(ny, 4))
            return
    hands_emit("click_miss", hit=hit_name, x=round(nx, 4), y=round(ny, 4))


def hwnd_under(window, global_pt: QPoint) -> QWidget:
    """Top filament plate under the point. Reality paints its own apertures."""
    found = tile_under(window, global_pt)
    if found is not None and found[1] != "reality":
        return found[0]
    return window


def tile_under(window, global_pt: QPoint) -> tuple[QWidget, str] | None:
    hit: tuple[QWidget, str] | None = None
    for widget, name in filament_tiles(window):
        if widget.frameGeometry().contains(global_pt):
            hit = (widget, name)
    return hit


def filament_tiles(window) -> list[tuple[QWidget, str]]:
    rows = (
        (getattr(window, "history_dock", None), "history"),
        (getattr(window, "think_dock", None), "thinking"),
        (getattr(window, "work_dock", None), "files"),
        (getattr(window, "calendar_window", None), "days"),
        (getattr(window, "camera_dock", None), "camera"),
        (getattr(window, "notify_inbox", None), "notify"),
        (getattr(window, "contacts_inbox", None), "contacts"),
        (getattr(window, "world_window", None), "reality"),
        (getattr(window, "_filament_chat_tile", None), "chat"),
    )
    out: list[tuple[QWidget, str]] = []
    for widget, name in rows:
        if widget is not None and not widget.isHidden():
            out.append((widget, name))
    return out


def live_desks(window) -> list[QRect]:
    from arelis.ui.filament_field import filament_chosen_desks

    home = getattr(window, "_filament_home", None)
    span = int(getattr(window, "_filament_span", 1) or 1)
    try:
        _union, _pinned, desks = filament_chosen_desks(window, span, home)
    except Exception:
        return [QRect(window.frameGeometry())]
    return [QRect(d) for d in desks] or [QRect(window.frameGeometry())]


@dataclass
class _Hold:
    who: str
    name: str
    widget: QWidget
    last_g: QPoint
    last_t: float
    vx: float = 0.0
    vy: float = 0.0
    samples: list[tuple[float, QPoint]] = field(default_factory=list)


def _state(window) -> dict:
    st = getattr(window, "_hands_desk", None)
    if st is None:
        st = {
            "holds": {},
            "hot_tiles": [],
            "scroll_y": {},
            "armed": {},
        }
        window._hands_desk = st
    return st


def _still_dragging(track: object | None) -> bool:
    if track is None:
        return False
    return bool(getattr(track, "dragging", False)) and str(
        getattr(track, "state", "") or ""
    ) == "pinch"


def _drag_tile(window, who: str, global_pt: QPoint) -> None:
    st = _state(window)
    hold = st["holds"].get(who)
    if hold is None:
        armed = st["armed"].get(who)
        if armed is None:
            found = tile_under(window, global_pt)
            if found is None or not is_tile_chrome(found[0], global_pt):
                return
            armed = found
        widget, name = armed
        if getattr(widget, "_filament_growing", False):
            return
        hold = _Hold(
            who=who,
            name=name,
            widget=widget,
            last_g=QPoint(global_pt),
            last_t=time.perf_counter(),
        )
        st["holds"][who] = hold
        hands_emit("grab", who=who, hit=name, kind="tile")
    now = time.perf_counter()
    dt = max(1e-3, now - hold.last_t)
    dx = global_pt.x() - hold.last_g.x()
    dy = global_pt.y() - hold.last_g.y()
    hold.vx = dx / dt
    hold.vy = dy / dt
    hold.samples.append((now, QPoint(global_pt)))
    if len(hold.samples) > 6:
        hold.samples = hold.samples[-6:]
    geo = hold.widget.frameGeometry()
    hold.widget.move(geo.x() + dx, geo.y() + dy)
    hold.last_g = QPoint(global_pt)
    hold.last_t = now
    place = getattr(window, "_place_filament_floats", None)
    if callable(place):
        place(reshape=False)


def _release_tile(window, who: str) -> None:
    st = _state(window)
    hold = st["holds"].pop(who, None)
    st["armed"].pop(who, None)
    if hold is None:
        return
    speed = math.hypot(hold.vx, hold.vy)
    geo = hold.widget.frameGeometry()
    desks = live_desks(window)
    if speed >= FLICK_PX_S:
        dest = flick_rect(geo, hold.vx, hold.vy, desks=desks)
        _animate_tile(hold.widget, dest)
        hands_emit(
            "flick",
            who=who,
            hit=hold.name,
            speed=round(speed, 1),
            x=dest.x(),
            y=dest.y(),
        )
    else:
        dest = clamp_rect_to_desks(geo, desks)
        if dest != geo:
            hold.widget.setGeometry(dest)
        hands_emit("drop", who=who, hit=hold.name, speed=round(speed, 1))
    from arelis.ui.filament_tile import remember_tile_origin

    store = getattr(window, "_filament_tile_pos", None)
    if isinstance(store, dict):
        remember_tile_origin(hold.widget, hold.name, store)
    place = getattr(window, "_place_filament_floats", None)
    if callable(place):
        place(reshape=False)


def _animate_tile(widget: QWidget, dest: QRect) -> None:
    prior = getattr(widget, "_hand_flick", None)
    if prior is not None:
        prior.stop()
    anim = QPropertyAnimation(widget, b"geometry", widget)
    anim.setDuration(int(FLICK_DT * 1000))
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.setStartValue(QRect(widget.geometry()))
    anim.setEndValue(dest)
    widget._hand_flick = anim  # type: ignore[attr-defined]
    anim.start()


def _palm_scroll(window, who: str, global_pt: QPoint, ny: float) -> None:
    st = _state(window)
    prev = st["scroll_y"].get(who)
    st["scroll_y"][who] = ny
    if prev is None:
        return
    dy = ny - prev
    app = QApplication.instance()
    widget = app.widgetAt(global_pt) if app is not None else None
    bar = _vertical_bar(widget)
    if bar is None or not bar.isEnabled():
        return
    step = scroll_steps(dy, bar.pageStep() or 24)
    if step == 0:
        return
    bar.setValue(bar.value() + step)
    hands_sample("scroll", who=who, dy=round(dy, 4), step=step)


def _vertical_bar(widget: QWidget | None):
    cur = widget
    while cur is not None:
        if isinstance(cur, QAbstractScrollArea):
            return cur.verticalScrollBar()
        if (
            isinstance(cur, QAbstractSlider)
            and cur.orientation() == Qt.Orientation.Vertical
        ):
            return cur
        cur = cur.parentWidget()
    return None


def _remap_xy(
    xy: tuple[float, float], src: QWidget, dest: QWidget
) -> tuple[float, float]:
    px, py = span_pixel(xy[0], xy[1], src.width(), src.height())
    global_pt = src.mapToGlobal(QPoint(px, py))
    local = dest.mapFromGlobal(global_pt)
    dw, dh = max(1, dest.width()), max(1, dest.height())
    return (local.x() / dw, local.y() / dh)


def _set_tile_hot(widget: QWidget, on: bool) -> None:
    want = "true" if on else "false"
    if widget.property("handHot") == want:
        return
    widget.setProperty("handHot", want)
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)


def _clear_all(window) -> None:
    prev = list(getattr(window, "_hand_cursor_hosts", ()) or ())
    for host in prev:
        clear_on(host)
    clear_on(window)
    world = getattr(window, "world_window", None)
    if world is not None:
        clear_on(world)
    window._hand_cursor_hosts = []
    field = getattr(window, "_filament", None)
    if field is not None and hasattr(field, "set_hot"):
        field.set_hot(set())
    st = getattr(window, "_hands_desk", None)
    if st is not None:
        for widget in st.get("hot_tiles") or []:
            _set_tile_hot(widget, False)
        st["hot_tiles"] = []
        st["holds"] = {}
        st["armed"] = {}
        st["scroll_y"] = {}
