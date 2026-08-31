"""Filament room field — coil, current, dust. Same light as the mockup.

Weather is idle (coil) at first rest, awake (unwrapped) once in use,
then listen / think / speak. The void is charcoal so the particles can
add. Punching a hole in the desk killed that light.

Invariants the next sitting will break if they "clean up":
- One opaque HWND. Never WA_TranslucentBackground on the desk.
- 1 / 2 / 3 are desk counts from the OS primary, not Windows monitor ids.
  2 is primary + right. Never steal the left desk to fake a pair.
- Remask / chrome reshape on span and resize only. Not every atmosphere tick.
- dirty_rect must cover the idle ellipse apex, not just the unwrapped wave.
- CPU / RAM only. The GPU is Reality (Cesium, solar GL).
- Confirm on this face is voice. Sodium stays card.
"""

from __future__ import annotations

import math
import random
from typing import Literal

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
    QRegion,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

Weather = Literal["idle", "awake", "listen", "think", "speak"]

_VOID = QColor(7, 8, 11)
_ICE = (176, 200, 216)
_GOLD = (212, 168, 96)
_CORE = (255, 236, 210)

_WEATHER = {
    "idle": {"form": 0.00, "speed": 0.08, "pulse": 0.00, "warm": 0.00, "words": 0.00},
    "awake": {"form": 1.00, "speed": 0.10, "pulse": 0.03, "warm": 0.08, "words": 0.00},
    "listen": {"form": 0.55, "speed": 0.11, "pulse": 0.05, "warm": 0.04, "words": 0.00},
    "think": {"form": 1.00, "speed": 0.13, "pulse": 0.08, "warm": 0.28, "words": 0.00},
    "speak": {"form": 1.00, "speed": 0.17, "pulse": 0.04, "warm": 0.06, "words": 1.00},
}

# t walks the current left→right. On a 3-span the bands are desks:
# left history/notify/contacts, home chat/thinking/camera,
# right days/files/rooms. Reality is not on the current — it sits
# alone at the bottom-right of the primary. Rooms is the list;
# Reality is the physics plate. pad is radial px outside the light.
FLOATS = (
    ("history", 0.10, 58),
    ("notify", 0.18, 58),
    ("contacts", 0.26, 58),
    ("chat", 0.42, 62),
    ("thinking", 0.50, 58),
    ("camera", 0.58, 58),
    ("days", 0.74, 58),
    ("files", 0.84, 58),
    ("rooms", 0.94, 58),
    ("reality", 0.00, 0),
)
FREE_FLOATS = frozenset({"reality"})

# Mini-world at the home corner. Rings are distinct radii so they read
# as orbits, not one smudged ellipse. Inset is the glass from the outer
# ring to the home edge — same on the right and the bottom.
_REALITY_RX = 34.0
_REALITY_RY = 17.0
_REALITY_RINGS = (
    0.55,
    0.88,
    1.22,
    1.58,
)
_REALITY_MARGIN = 76.0
_REALITY_HIT = 52.0

_STRANDS = 4
_DUST = 1100


def _mix(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _ease(current: float, target: float, dt: float, sec: float) -> float:
    k = 1.0 - math.exp(-dt / max(0.05, sec))
    return current + (target - current) * k


def _tone(t: float, warmth: float) -> tuple[int, int, int]:
    u = min(1.0, max(0.0, t + warmth * 0.25))
    return (
        int(_mix(_ICE[0], _GOLD[0], u)),
        int(_mix(_ICE[1], _GOLD[1], u)),
        int(_mix(_ICE[2], _GOLD[2], u)),
    )


def _lit(rgb: tuple[int, int, int], alpha: float) -> QColor:
    return QColor(rgb[0], rgb[1], rgb[2], max(0, min(255, int(alpha * 255))))


_ORB_CACHE: dict[tuple[int, ...], QPixmap] = {}


def _orb_key(
    radius: float,
    rgb: tuple[int, int, int],
    core: float,
    pin: float,
) -> tuple[int, ...]:
    return (
        max(2, round(float(radius))),
        rgb[0] // 16,
        rgb[1] // 16,
        rgb[2] // 16,
        max(0, round(float(core))),
        1 if pin > 0.2 else 0,
    )


def clear_orb_stamps() -> None:
    _ORB_CACHE.clear()


def _paint_orb_direct(
    painter: QPainter,
    p: QPointF,
    radius: float,
    rgb: tuple[int, int, int],
    glow: float,
    *,
    core: float = 0.0,
    pin: float = 0.0,
) -> None:
    """Radial bake. Used once per stamp, not per grain."""
    if radius > 0.6:
        halo = QRadialGradient(p, radius)
        peak = min(0.55, max(0.0, glow) * 0.38)
        halo.setColorAt(0.0, _lit(rgb, peak))
        halo.setColorAt(0.28, _lit(rgb, peak * 0.55))
        halo.setColorAt(0.62, _lit(rgb, peak * 0.16))
        halo.setColorAt(1.0, _lit(rgb, 0.0))
        painter.setBrush(QBrush(halo))
        painter.drawEllipse(p, radius, radius)
    if core > 0.35:
        body = QRadialGradient(p, core)
        body.setColorAt(0.0, _lit(_CORE, min(1.0, glow)))
        body.setColorAt(0.40, _lit(rgb, min(0.72, glow * 0.62)))
        body.setColorAt(1.0, _lit(rgb, 0.0))
        painter.setBrush(QBrush(body))
        painter.drawEllipse(p, core, core)
    if pin > 0.2:
        painter.setBrush(_lit(_CORE, min(1.0, 0.85 + glow * 0.15)))
        painter.drawEllipse(p, pin, pin)


def _orb_stamp(
    radius: float,
    rgb: tuple[int, int, int],
    *,
    core: float = 0.0,
    pin: float = 0.0,
) -> QPixmap:
    """Bake one glow into RAM. Same look, no per-frame gradient build."""
    key = _orb_key(radius, rgb, core, pin)
    hit = _ORB_CACHE.get(key)
    if hit is not None:
        return hit
    r = float(key[0])
    side = max(4, math.ceil(r * 2 + 4))
    img = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    qp = QPainter(img)
    qp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    qp.setPen(Qt.PenStyle.NoPen)
    _paint_orb_direct(
        qp,
        QPointF(side * 0.5, side * 0.5),
        r,
        rgb,
        1.0,
        core=float(key[4]),
        pin=0.85 if key[5] else 0.0,
    )
    qp.end()
    pix = QPixmap.fromImage(img)
    _ORB_CACHE[key] = pix
    return pix


def warm_orb_stamps() -> None:
    """First-paint hitch is worse than a few dozen stamps up front."""
    if _ORB_CACHE:
        return
    if QApplication.instance() is None:
        return
    for rgb in (_ICE, _GOLD, _CORE):
        for radius, core, pin in (
            (4.0, 1.2, 0.45),
            (8.0, 2.4, 0.85),
            (12.0, 3.6, 0.9),
            (16.0, 4.8, 1.6),
            (22.0, 8.2, 1.6),
            (28.0, 8.2, 1.6),
        ):
            _orb_stamp(radius, rgb, core=core, pin=pin)


def _paint_soft_orb(
    painter: QPainter,
    p: QPointF,
    radius: float,
    rgb: tuple[int, int, int],
    glow: float,
    *,
    core: float = 0.0,
    pin: float = 0.0,
    lean: bool = False,
) -> None:
    """Light that dies at the rim. Flat ellipses read as plastic disks."""
    if lean:
        # Radial fills on a 3-span are the frame killer. Keep a pin.
        body = max(core, min(radius * 0.22, 2.4), 0.9)
        painter.setBrush(_lit(rgb, min(0.55, max(0.0, glow) * 0.42)))
        painter.drawEllipse(p, body, body)
        if pin > 0.2:
            painter.setBrush(_lit(_CORE, min(1.0, 0.85 + glow * 0.15)))
            painter.drawEllipse(p, pin, pin)
        return
    stamp = _orb_stamp(radius, rgb, core=core, pin=pin)
    if stamp.isNull():
        _paint_orb_direct(painter, p, radius, rgb, glow, core=core, pin=pin)
        return
    painter.setOpacity(min(1.0, max(0.0, glow)))
    half = stamp.width() * 0.5
    painter.drawPixmap(QPointF(p.x() - half, p.y() - half), stamp)
    painter.setOpacity(1.0)


def clamp_filament_span(value: object) -> int:
    try:
        return max(1, min(3, int(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1


def filament_row_desks(
    window: QWidget, home: QRect | None = None
) -> tuple[list[QRect], QRect]:
    """Monitors on the same horizontal band as home, left to right.

    Windows display numbers are ignored. The row is physical x-order, so a
    left-hand "monitor 3" still sits at index 0.
    """
    app = QApplication.instance()
    fallback = QRect(window.geometry()) if window is not None else QRect(0, 0, 1280, 800)
    if app is None or window is None:
        base = QRect(home) if home is not None else QRect(fallback)
        return [base], base
    pinned = QRect(home) if home is not None else None
    if pinned is None:
        screen = app.primaryScreen() or window.screen()
        pinned = (
            QRect(screen.availableGeometry()) if screen is not None else QRect(fallback)
        )
    row: list[QRect] = []
    band = max(80, pinned.height() // 4)
    for screen in app.screens():
        geo = QRect(screen.availableGeometry())
        if abs(geo.center().y() - pinned.center().y()) <= band:
            row.append(geo)
    if not row:
        row = [pinned]
    row.sort(key=lambda geo: geo.x())
    return row, pinned


def _home_desk_index(row: list[QRect], home: QRect) -> int:
    """Nearest desk by center-x. Exact x/width fails when the taskbar insets."""
    if not row:
        return 0
    hx = home.center().x()
    best = 0
    best_d = 10**9
    for i, geo in enumerate(row):
        d = abs(geo.center().x() - hx)
        if d < best_d:
            best, best_d = i, d
    return best


def choose_span_desks(row: list[QRect], home: QRect, want: int) -> list[QRect]:
    """How many desks, from the primary: 1, primary+right, then the whole row.

    Shrinks the same way. Never steals the left desk to fake a 2-span.
    """
    if not row:
        return [QRect(home)]
    want = clamp_filament_span(want)
    idx = _home_desk_index(row, home)
    home_desk = QRect(row[idx])
    if want <= 1:
        return [home_desk]
    right = QRect(row[idx + 1]) if idx + 1 < len(row) else None
    if want == 2:
        return [home_desk, right] if right is not None else [home_desk]
    left = QRect(row[idx - 1]) if idx > 0 else None
    desks = [home_desk]
    if left is not None:
        desks.insert(0, left)
    if right is not None:
        desks.append(right)
    return desks


def _union_desks(desks: list[QRect], home: QRect | None = None) -> QRect:
    """True union of the chosen desks.

    Y is not snapped to home. Windows can register a side desk higher
    (this machine: left at -74). Pinning y to the primary left a gap on
    that desk. Chrome uses home_band_from_union so the bar still sits
    on the primary, not in the extra strip.
    """
    if not desks:
        return QRect(home) if home is not None else QRect()
    union = QRect(desks[0])
    for geo in desks[1:]:
        union = union.united(geo)
    return union


def filament_row_geometry(window: QWidget) -> tuple[QRect, QRect, int]:
    """Horizontal desk row: union, home monitor, how many desks (1–3)."""
    row, home = filament_row_desks(window)
    return _union_desks(row, home), home, min(3, len(row))


def home_band_from_union(union: QRect, home: QRect) -> QRect:
    """Primary desk in HWND-local coords, assuming the HWND is `union`.

    mapFromGlobal follows Qt's cached origin. After a 2→3 grow-left that
    cache can sit at x=0 while the HWND is at -2560, which pins chrome on
    the left desk. Subtracting the union does not.

    y is not always 0: a left desk can sit higher (this machine: -74), so
    the HWND top is above the primary. A bar at local y=0 lives in that
    gap and is on no monitor.
    """
    if not union.isValid() or not home.isValid():
        return QRect()
    return QRect(
        int(home.x() - union.x()),
        int(home.y() - union.y()),
        int(home.width()),
        int(home.height()),
    )


def chrome_band_on_glass(union: QRect, home: QRect, glass: QRect) -> QRect:
    """Slim bar rect, always inside `glass`. Never off the widget."""
    intended = home_band_from_union(union, home)
    if glass.width() < 32 or glass.height() < 32:
        return QRect(0, 0, max(1, glass.width()), 32)
    hit = intended.intersected(glass) if intended.isValid() else QRect()
    if hit.width() >= 280:
        y = max(0, min(int(hit.y()), max(0, glass.height() - 32)))
        return QRect(int(hit.x()), y, int(hit.width()), 32)
    y = 0
    if intended.isValid() and 0 <= intended.y() <= glass.height() - 32:
        y = int(intended.y())
    return QRect(0, y, max(320, glass.width()), 32)


def home_band_in_window(window: QWidget, home: QRect) -> QRect:
    """Where the primary desk overlaps this HWND. Empty if we missed home."""
    if window is None or not home.isValid():
        return QRect(window.rect()) if window is not None else QRect()
    local = QRect(window.mapFromGlobal(home.topLeft()), home.size())
    hit = local.intersected(window.rect())
    if hit.width() < 280:
        return QRect()
    return hit


def filament_span_geometry(
    window: QWidget, want: int, home: QRect | None = None
) -> tuple[QRect, QRect, int]:
    """Geometry for a 1 / 2 / 3 desk span, shrinking or growing from home."""
    row, pinned = filament_row_desks(window, home)
    desks = choose_span_desks(row, pinned, want)
    return _union_desks(desks, pinned), pinned, len(desks)


def filament_chosen_desks(
    window: QWidget, want: int, home: QRect | None = None
) -> tuple[QRect, QRect, list[QRect]]:
    row, pinned = filament_row_desks(window, home)
    desks = choose_span_desks(row, pinned, want)
    return _union_desks(desks, pinned), pinned, desks


def filament_work_region(union: QRect, desks: list[QRect]) -> QRegion:
    """Visible glass = each desk's Windows work area, in HWND-local coords.

    The HWND has to be the bounding box (one rectangle). The region is the
    actual rcWork tiles, so a 74px Windows offset cannot cover a taskbar.
    """
    region = QRegion()
    if not union.isValid():
        return region
    for desk in desks:
        local = QRect(
            int(desk.x() - union.x()),
            int(desk.y() - union.y()),
            int(desk.width()),
            int(desk.height()),
        )
        if local.isValid():
            region = region.united(QRegion(local))
    return region


def attach_on_rect(rect: QRect, from_pt: QPointF) -> QPointF:
    """Closest point on the plate, so the strand meets the glass."""
    if rect.width() <= 0 or rect.height() <= 0:
        return QPointF(from_pt)
    x = min(max(from_pt.x(), float(rect.left())), float(rect.right()))
    y = min(max(from_pt.y(), float(rect.top())), float(rect.bottom()))
    return QPointF(x, y)


class FilamentField:
    """Sim + painter for the filament stream. Lives on ArelisWindow."""

    def __init__(self) -> None:
        rng = random.Random(11)
        self.state: Weather = "idle"
        self.span = 1
        self._desk_left = 0.0
        self._desk_w = 0.0
        self.form = 0.0
        self.speed = 0.08
        self.pulse = 0.0
        self.warm = 0.0
        self.words = 0.0
        self.time = 0.0
        self._open: set[str] = set()
        self._hidden: set[str] = set()
        self._live: set[str] = set()
        self._hot: set[str] = set()
        self._live_phase = 0.0
        self._tethers: dict[str, dict] = {}
        self._load = ""
        self.dust = []
        for i in range(_DUST):
            size = 0.5 + rng.random() ** 2.2 * 3.6
            spread = 0.28 if size > 2.4 else 0.46
            self.dust.append(
                {
                    "t": 0.5 + (rng.random() * 2 - 1) * spread,
                    "s": (rng.random() * 2 - 1) * 1.15,
                    "z": rng.random() ** 1.7,
                    "size": size,
                    "life": rng.random(),
                    "strand": float(i % _STRANDS),
                    "hot": rng.random() < 0.14,
                }
            )

    def set_state(self, state: Weather) -> None:
        if state in _WEATHER:
            self.state = state

    def set_span(
        self,
        screens: int,
        desk_left: float = 0.0,
        desk_width: float = 0.0,
    ) -> None:
        self.span = max(1, min(3, int(screens)))
        self._desk_left = max(0.0, float(desk_left))
        self._desk_w = max(0.0, float(desk_width))

    def set_load(self, name: str) -> None:
        """Extra paint cost on the desk — currently just `camera`."""
        self._load = str(name or "")

    def atmosphere_ms(self) -> int:
        """Field timer. Camera + 3-span do not try for 30 Hz of 11 Mpx."""
        if self._load == "camera":
            return 50
        if self.span >= 3:
            return 40
        return 33

    def strand_steps(self, w: float) -> int:
        """Segments per strand. Caps so a 7680 desk stays drawable."""
        return 96 + min(48, max(0, int(float(w) / 90)))

    def dust_draw_stride(self, w: float) -> int:
        """Draw every Nth grain. Sim still walks all 1100."""
        stride = 1
        if w >= 7000:
            stride = 3
        elif w >= 4000:
            stride = 2
        if self._load == "camera":
            stride += 1
        return min(4, stride)

    def dirty_rect(self, rect: QRect) -> QRect:
        """Horizontal band the current actually occupies. Not the whole HWND.

        Idle is a tall ellipse; the unwrapped wave is a short ribbon. Using
        only the wave left the apex uncleared — dashed ghosts above `days`.
        """
        w, h = rect.width(), rect.height()
        if w <= 0 or h <= 0:
            return QRect(rect)
        _cx, cy, _rx, ry = self.ellipse(rect)
        amp = h * 0.11 * 1.28 + 40.0
        # Titles sit a pad outside the bead; dust sways past the rim.
        reach = max(amp, ry) + 96.0
        top = int(cy - reach)
        bot = int(cy + reach)
        prompt = self.prompt_rect(rect)
        if prompt.isValid():
            top = min(top, prompt.top() - 8)
            bot = max(bot, prompt.bottom() + 8)
        for tether in self._tethers.values():
            if float(tether.get("grow", 0)) < 0.02:
                continue
            end = tether["end"]
            top = min(top, int(end.y()) - 20)
            bot = max(bot, int(end.y()) + 20)
        for name in FREE_FLOATS:
            if name in self._hidden:
                continue
            p = self.bead_point(name, rect)
            reach = int(_REALITY_RY * _REALITY_RINGS[-1]) + 16
            top = min(top, int(p.y()) - reach - 36)
            bot = max(bot, int(p.y()) + reach)
        top = max(rect.top(), top)
        bot = min(rect.bottom() + 1, bot)
        if bot <= top:
            return QRect(rect)
        return QRect(rect.left(), top, w, bot - top)

    def tick(self, dt: float) -> None:
        dt = min(0.05, max(0.0, float(dt)))
        want = _WEATHER[self.state]
        self.form = _ease(self.form, want["form"], dt, 1.85)
        self.speed = _ease(self.speed, want["speed"], dt, 1.1)
        self.pulse = _ease(self.pulse, want["pulse"], dt, 0.9)
        self.warm = _ease(self.warm, want["warm"], dt, 1.2)
        self.words = _ease(self.words, want["words"], dt, 0.8)
        self.time += dt * self.speed * 1.7
        if self._live:
            self._live_phase += dt * 3.7
        for name, tether in list(self._tethers.items()):
            reach = 0.32 if tether["want"] > 0.5 else 0.48
            tether["grow"] = _ease(tether["grow"], tether["want"], dt, reach)
            if tether["want"] <= 0.0 and tether["grow"] < 0.02:
                del self._tethers[name]
        for d in self.dust:
            d["t"] += dt * (0.012 + self.speed * 0.028) * (0.5 + d["z"])
            if d["t"] > 0.96 or d["t"] < 0.04:
                d["t"] = 0.08 + random.random() * 0.84
                d["life"] = 0.0
            d["life"] += dt * 0.16

    def ellipse(self, rect: QRect) -> tuple[float, float, float, float]:
        w, h = float(rect.width()), float(rect.height())
        desk = self._desk_width(w)
        if self._desk_w > 80.0:
            cx = rect.left() + self._desk_left + desk * 0.5
        else:
            cx = rect.left() + w * 0.5
        cy = rect.top() + h * 0.40
        rx = min(desk * 0.48, h * 0.44)
        ry = rx * 0.50
        return cx, cy, rx, ry

    def set_open_faces(self, names: set[str]) -> None:
        self._open = set(names)

    def set_hidden_faces(self, names: set[str]) -> None:
        self._hidden = set(names)

    def set_live_faces(self, names: set[str]) -> None:
        """Titles that should breathe — a turn, a yes, an unread."""
        self._live = set(names)

    def set_hot(self, names: set[str]) -> None:
        """Bead under a hand aperture. Glow only — not a click."""
        self._hot = set(names)

    def is_live(self, name: str) -> bool:
        return name in self._live

    def live_breath(self) -> float:
        """0..1, ~1.7s period. Independent of unwrap speed so it stays a clock."""
        return 0.5 + 0.5 * math.sin(self._live_phase)

    def bind_tether(self, name: str, end: QPointF | None) -> None:
        """Grow a faint strand from the current to an open plate. None lets it die."""
        if end is None:
            if name in self._tethers:
                self._tethers[name]["want"] = 0.0
            return
        cur = self._tethers.get(name)
        if cur is None:
            self._tethers[name] = {"end": QPointF(end), "grow": 0.0, "want": 1.0}
            return
        cur["end"] = QPointF(end)
        cur["want"] = 1.0

    def tether_grow(self, name: str) -> float:
        cur = self._tethers.get(name)
        return float(cur["grow"]) if cur is not None else 0.0

    def spec(self, name: str) -> tuple[float, float] | None:
        for key, t, pad in FLOATS:
            if key == name:
                return t, float(pad)
        return None

    def anchor_point(self, name: str, rect: QRect) -> QPointF:
        """Point on the light itself. Titles sit a pad outside this."""
        if name in FREE_FLOATS:
            return self._free_bead(rect)
        found = self.spec(name)
        if found is None:
            cx, cy, _rx, _ry = self.ellipse(rect)
            return QPointF(cx, cy)
        return self._point(found[0], 2.0, rect)

    def _free_bead(self, rect: QRect) -> QPointF:
        """Reality sits off the current, squared to the home corner."""
        home = self.home_rect(rect)
        if not home.isValid():
            home = QRect(rect)
        reach_x = _REALITY_RX * _REALITY_RINGS[-1]
        reach_y = _REALITY_RY * _REALITY_RINGS[-1]
        x = float(home.right()) - _REALITY_MARGIN - reach_x
        y = float(home.bottom()) - _REALITY_MARGIN - reach_y
        sway = math.sin(self.time * 0.70 + 1.3) * 3.0
        bob = math.cos(self.time * 0.55) * 2.5
        return QPointF(x + sway, y + bob)

    def _radial(self, name: str, rect: QRect, pad: float) -> QPointF:
        p = self.anchor_point(name, rect)
        cx, cy, _rx, _ry = self.ellipse(rect)
        dx, dy = p.x() - cx, p.y() - cy
        length = math.hypot(dx, dy) or 1.0
        return QPointF(p.x() + dx / length * pad, p.y() + dy / length * pad)

    def bead_point(self, name: str, rect: QRect) -> QPointF:
        """The tile's own particle — off the dust, same motion as the word."""
        if name in FREE_FLOATS:
            return self._free_bead(rect)
        found = self.spec(name)
        pad = float(found[1]) if found is not None else 58.0
        return self._radial(name, rect, pad * 0.62)

    def hit_float(self, pos: QPoint, rect: QRect) -> str | None:
        """Which tile bead is under the point. Same motion as the title."""
        best: str | None = None
        best_d = 1e9
        for name, _t, _pad in FLOATS:
            if name in self._hidden:
                continue
            a = self.bead_point(name, rect)
            reach = _REALITY_HIT if name in FREE_FLOATS else 26.0
            dist = math.hypot(pos.x() - a.x(), pos.y() - a.y())
            if dist < reach and dist < best_d:
                best = name
                best_d = dist
        return best

    def title_point(self, name: str, rect: QRect) -> QPointF:
        if name in FREE_FLOATS:
            p = self._free_bead(rect)
            return QPointF(p.x(), p.y() - 36.0)
        found = self.spec(name)
        if found is None:
            cx, cy, _rx, _ry = self.ellipse(rect)
            return QPointF(cx, cy)
        return self._radial(name, rect, float(found[1]) + 18.0)

    def home_rect(self, rect: QRect) -> QRect:
        """The primary desk. Ask + chrome stay inside this, even on a 3-span."""
        w, h = float(rect.width()), float(rect.height())
        desk = self._desk_width(w)
        if self._desk_w > 80.0:
            return QRect(int(rect.left() + self._desk_left), rect.top(), int(desk), int(h))
        return QRect(rect)

    def prompt_point(self, rect: QRect) -> QPointF:
        """Ask cluster sits under the ring, on the home desk."""
        cx, cy, _rx, ry = self.ellipse(rect)
        return QPointF(cx, cy + ry + 96)

    def prompt_rect(self, rect: QRect) -> QRect:
        p = self.prompt_point(rect)
        return QRect(int(p.x()) - 200, int(p.y()) - 8, 400, 96)

    def hit_band(self, rect: QRect) -> QRect:
        cx, cy, rx, ry = self.ellipse(rect)
        pad = 48
        return QRect(
            int(cx - rx - pad),
            int(cy - ry - pad),
            int((rx + pad) * 2),
            int((ry + pad) * 2),
        )

    def shape_region(self, rect: QRect, extras: list[QRect] | None = None) -> QRegion:
        """The field is the window. No hole — particles need the void."""
        return QRegion(rect)

    def paint(self, painter: QPainter, rect: QRect) -> None:
        w, h = rect.width(), rect.height()
        if w <= 0 or h <= 0:
            return
        warm_orb_stamps()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(rect, _VOID)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)

        word_beat = max(0.0, math.sin(self.time * 1.55)) ** 8 * self.words
        speak_head = (self.time * 0.14) % 1.0
        pulse_t = (math.sin(self.time * 1.15) * 0.5 + 0.5) * self.pulse + word_beat * 0.85
        steps = self.strand_steps(w)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        for s in range(_STRANDS):
            prev: QPointF | None = None
            for i in range(steps + 1):
                t = i / steps
                p = self._point(t, float(s), rect)
                if prev is not None:
                    fade = min(
                        self._edge_fade(p.x(), w, rect.left()),
                        self._edge_fade(prev.x(), w, rect.left()),
                        self._path_fade(t),
                        self._path_fade((i - 1) / steps),
                    )
                    if fade > 0.12:
                        rgb = _tone(t, self.warm)
                        pen = QPen(_lit(rgb, (0.10 + s * 0.016) * fade))
                        pen.setWidthF(2.8 - s * 0.22)
                        painter.setPen(pen)
                        painter.drawLine(prev, p)
                prev = p

        painter.setPen(Qt.PenStyle.NoPen)
        cx, cy, _rx, _ry = self.ellipse(rect)
        stride = self.dust_draw_stride(w)
        lean = stride > 1
        for i, d in enumerate(self.dust):
            if i % stride:
                continue
            p = self._point(d["t"], float(d.get("strand", 2.0)), rect)
            fade = min(
                self._edge_fade(p.x(), w, rect.left()),
                self._path_fade(d["t"]),
                min(1.0, d["life"] * 2.2),
            )
            if fade < 0.14:
                continue
            along = (
                max(0.0, 1.0 - abs(d["t"] - speak_head) / 0.07) if self.words else 0.0
            )
            ndx, ndy = p.x() - cx, p.y() - cy
            nlen = math.hypot(ndx, ndy) or 1.0
            off = d["s"] * 18.0
            sway = math.sin(self.time * 0.55 + d["life"] * 7 + d["z"] * 5)
            x = p.x() + ndx / nlen * off + sway * (1.6 + d["size"] * 0.6)
            y = (
                p.y()
                + ndy / nlen * off
                + math.cos(self.time * 0.4 + d["t"] * 10) * (1.2 + d["size"] * 0.6)
            )
            hot = bool(d.get("hot"))
            rgb = _CORE if hot or d["size"] > 2.8 else _tone(d["t"], self.warm)
            glow = (0.34 + d["z"] * 0.52 + pulse_t * 0.22 + along * 0.7) * fade
            if hot:
                glow = min(1.35, glow * 1.85)
            halo = d["size"] * (3.8 if hot else 2.6)
            core = d["size"] * (0.70 if hot else 0.48)
            pin = 0.85 if hot or d["size"] > 2.6 else (0.45 if d["size"] > 1.4 else 0.0)
            _paint_soft_orb(
                painter,
                QPointF(x, y),
                halo,
                rgb,
                glow,
                core=core,
                pin=pin,
                lean=lean and not hot,
            )

        self._paint_beads(painter, rect)
        self._paint_stems(painter, rect)
        self._paint_tethers(painter, rect)
        painter.restore()

    def _paint_beads(self, painter: QPainter, rect: QRect) -> None:
        """One particle per tile, off the dust, same path-speed as the word."""
        painter.setPen(Qt.PenStyle.NoPen)
        for name, t, _pad in FLOATS:
            if name in self._hidden:
                continue
            p = self.bead_point(name, rect)
            open_ = name in self._open
            pulse = 0.5 + 0.5 * math.sin(self.time * 1.7 + t * 8.0)
            if name in FREE_FLOATS:
                self._paint_reality_orbit(painter, p)
                lure = 0.5 + 0.5 * math.sin(self.time * 1.15)
                if open_:
                    halo, core, glow = 14.0, 4.6, 0.62 + lure * 0.08
                else:
                    halo, core, glow = 28.0 + lure * 5.0, 10.4, 1.04 + lure * 0.12
                if name in self._hot:
                    halo *= 1.28
                    glow = min(1.4, glow + 0.22)
                _paint_soft_orb(
                    painter,
                    p,
                    halo,
                    _CORE,
                    glow,
                    core=core,
                    pin=1.8 if not open_ else 0.9,
                )
                continue
            if name in self._live:
                breath = self.live_breath()
                # Closed is the call: look at this bead. Open just keeps time.
                if open_:
                    halo = 12.0 + breath * 6.0
                    core = 4.2 + breath * 1.2
                    glow = 0.62 + breath * 0.22
                else:
                    halo = 24.0 + breath * 16.0
                    core = 8.0 + breath * 3.2
                    glow = 0.78 + breath * 0.42
            elif open_:
                halo, core, glow = 10.0, 3.6, 0.50 + pulse * 0.08
            else:
                halo, core, glow = 22.0 + pulse * 2.0, 8.2, 0.92 + pulse * 0.08
            if name in self._hot:
                halo *= 1.35
                core *= 1.2
                glow = min(1.4, glow + 0.28)
            rgb = _tone(t, self.warm)
            _paint_soft_orb(
                painter,
                p,
                halo,
                rgb,
                glow,
                core=core,
                pin=1.6 if not open_ else 0.9,
            )

    def _paint_reality_orbit(self, painter: QPainter, center: QPointF) -> None:
        """A little world of its own. Not a stem back to the current."""
        rx, ry = _REALITY_RX, _REALITY_RY
        steps = 32
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for s, scale in enumerate(_REALITY_RINGS):
            prev: QPointF | None = None
            phase = self.time * (0.72 + s * 0.11) + s * 0.55
            for i in range(steps + 1):
                t = i / steps
                ang = t * math.tau + phase
                wobble = 0.97 + 0.03 * math.sin(t * math.tau * 2.0 + s)
                p = QPointF(
                    center.x() + math.cos(ang) * rx * scale * wobble,
                    center.y() + math.sin(ang) * ry * scale * wobble,
                )
                if prev is not None:
                    fade = self._path_fade(t)
                    if fade > 0.12:
                        pen = QPen(_lit(_GOLD, (0.14 + s * 0.05) * fade))
                        pen.setWidthF(1.45 - s * 0.12)
                        painter.setPen(pen)
                        painter.drawLine(prev, p)
                prev = p
        painter.setPen(Qt.PenStyle.NoPen)
        outer = _REALITY_RINGS[-2]
        for i in range(8):
            ang = self.time * 0.85 + i * (math.tau / 8)
            q = QPointF(
                center.x() + math.cos(ang) * rx * outer,
                center.y() + math.sin(ang) * ry * outer,
            )
            _paint_soft_orb(painter, q, 2.6, _CORE, 0.56, core=0.9, pin=0.4)

    def _paint_stems(self, painter: QPainter, rect: QRect) -> None:
        """Short strand from the light to each closed title."""
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for name, _t, _pad in FLOATS:
            if name in FREE_FLOATS:
                continue
            if name in self._open or name in self._tethers:
                continue
            a = self.anchor_point(name, rect)
            mid = self.bead_point(name, rect)
            b = self.title_point(name, rect)
            for src, dst in ((a, mid), (mid, b)):
                prev: QPointF | None = None
                for i in range(6):
                    u = i / 5
                    p = QPointF(_mix(src.x(), dst.x(), u), _mix(src.y(), dst.y(), u))
                    if prev is not None:
                        pen = QPen(_lit(_GOLD, 0.16 + u * 0.10))
                        pen.setWidthF(1.6)
                        painter.setPen(pen)
                        painter.drawLine(prev, p)
                    prev = p

    def _paint_tethers(self, painter: QPainter, rect: QRect) -> None:
        """Grown, very faint current from the light into an open plate."""
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for name, tether in self._tethers.items():
            grow = float(tether["grow"])
            if grow < 0.02:
                continue
            start = self.bead_point(name, rect)
            end = tether["end"]
            steps = 28
            prev: QPointF | None = None
            for i in range(steps + 1):
                u = (i / steps) * grow
                p = self._tether_point(start, end, u)
                if prev is not None:
                    fade = (1.0 - u) * 0.22 + 0.04
                    pen = QPen(_lit(_CORE, fade * 0.55))
                    pen.setWidthF(2.2 - u * 1.1)
                    painter.setPen(pen)
                    painter.drawLine(prev, p)
                    pen = QPen(_lit(_GOLD, fade * 0.28))
                    pen.setWidthF(1.1)
                    painter.setPen(pen)
                    painter.drawLine(prev, p)
                prev = p
            if grow > 0.2:
                painter.setPen(Qt.PenStyle.NoPen)
                for k in range(7):
                    u = ((k + 0.5) / 7) * grow
                    p = self._tether_point(start, end, u)
                    painter.setBrush(_lit(_CORE, 0.10 * (1.0 - u)))
                    painter.drawEllipse(p, 2.4, 2.4)

    def _tether_point(self, start: QPointF, end: QPointF, u: float) -> QPointF:
        dx, dy = end.x() - start.x(), end.y() - start.y()
        length = math.hypot(dx, dy) or 1.0
        sag = min(70.0, length * 0.18)
        px, py = -dy / length * sag, dx / length * sag
        c1 = QPointF(start.x() + dx * 0.32 + px, start.y() + dy * 0.32 + py)
        c2 = QPointF(start.x() + dx * 0.68 + px * 0.45, start.y() + dy * 0.68 + py * 0.45)
        omt = 1.0 - u
        return QPointF(
            omt**3 * start.x()
            + 3 * omt**2 * u * c1.x()
            + 3 * omt * u**2 * c2.x()
            + u**3 * end.x(),
            omt**3 * start.y()
            + 3 * omt**2 * u * c1.y()
            + 3 * omt * u**2 * c2.y()
            + u**3 * end.y(),
        )

    def _desk_width(self, w: float) -> float:
        """Home monitor width. The ribbon uses the full window; the coil stays here."""
        if self._desk_w > 80.0:
            return min(self._desk_w, w)
        if self.span >= 2 and w >= 3000:
            return w / float(self.span)
        return w

    def _fade_margin(self, w: float) -> float:
        return max(40.0, self._desk_width(w) * 0.03)

    def _ribbon_half(self, w: float) -> float:
        return max(80.0, w * 0.5 - self._fade_margin(w))

    def _coil(self, t: float, strand: float, rect: QRect) -> QPointF:
        cx, cy, rx, ry = self.ellipse(rect)
        ang = t * math.tau + self.time * 1.05 + strand * 0.35
        rad = 0.90 + 0.10 * math.sin(t * math.tau * 2.0 + strand)
        return QPointF(
            cx + math.cos(ang) * rx * rad,
            cy + math.sin(ang) * ry * rad,
        )

    def _wave(self, t: float, strand: float, rect: QRect, half: float) -> QPointF:
        w, h = rect.width(), rect.height()
        cx = rect.left() + w * 0.5
        cy = rect.top() + h * 0.40
        amp = h * 0.11
        wave = (
            math.sin(t * math.pi * 2.05 + self.time * 0.3 + strand * 0.5) * amp
            + math.sin(t * math.pi * 4.6 + self.time * 0.12) * amp * 0.28
            + (strand - 1.5) * h * 0.01
        )
        return QPointF(cx + (t - 0.5) * 2 * half, cy + wave)

    def _point(self, t: float, strand: float, rect: QRect) -> QPointF:
        w = rect.width()
        knot = self._desk_width(w)
        full_half = self._ribbon_half(w)
        listen_half = min(max(knot * 0.82, full_half * 0.55), full_half)
        coil = self._coil(t, strand, rect)
        if self.form <= 0.5:
            u = self.form / 0.5
            listen = self._wave(t, strand, rect, listen_half)
            return QPointF(_mix(coil.x(), listen.x(), u), _mix(coil.y(), listen.y(), u))
        u = (self.form - 0.5) / 0.5
        listen = self._wave(t, strand, rect, listen_half)
        full = self._wave(t, strand, rect, full_half)
        return QPointF(_mix(listen.x(), full.x(), u), _mix(listen.y(), full.y(), u))

    def _edge_fade(self, x: float, w: float, left: float) -> float:
        local = x - left
        m = self._fade_margin(w)
        if m <= 0.0 or w <= 0.0:
            return 0.0
        if local < m:
            t = max(0.0, local / m)
            return t ** 1.6
        if local > w - m:
            t = max(0.0, (w - local) / m)
            return t ** 1.6
        return 1.0

    @staticmethod
    def _path_fade(t: float) -> float:
        a = 0.08
        if t < a:
            return max(0.0, (t / a) ** 1.5)
        if t > 1.0 - a:
            return max(0.0, ((1.0 - t) / a) ** 1.5)
        return 1.0


class FilamentFloatBar(QObject):
    """Gold words on the current. Click opens a plate. Not a menu target."""

    opened = Signal(str)
    hands_toggled = Signal(bool)

    def __init__(self, field: FilamentField, host: QWidget) -> None:
        super().__init__(host)
        self._field = field
        self._host = host
        self._open: set[str] = set()
        self._skip: set[str] = set()
        self._buttons: dict[str, QPushButton] = {}
        self._beads: dict[str, QPushButton] = {}
        for name, _t, _oy in FLOATS:
            btn = QPushButton(name, host)
            btn.setObjectName("FilamentFloat")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            btn.clicked.connect(lambda _=False, n=name: self.opened.emit(n))
            btn.hide()
            self._buttons[name] = btn
            bead = QPushButton("", host)
            bead.setObjectName("FilamentBead")
            bead.setFixedSize(56, 56) if name in FREE_FLOATS else bead.setFixedSize(40, 40)
            bead.setCursor(Qt.CursorShape.PointingHandCursor)
            bead.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            bead.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            bead.setToolTip(name)
            bead.clicked.connect(lambda _=False, n=name: self.opened.emit(n))
            bead.hide()
            self._beads[name] = bead
        self.hands_btn = QPushButton("hands", host)
        self.hands_btn.setObjectName("FilamentFloat")
        self.hands_btn.setCheckable(True)
        self.hands_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hands_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hands_btn.setToolTip("C920 hands. Camera tile is inspect-only.")
        self.hands_btn.toggled.connect(self.hands_toggled.emit)
        self.hands_btn.hide()

    def chips(self) -> dict[str, QPushButton]:
        return self._buttons

    def hide(self) -> None:
        self.setVisible(False)

    def setVisible(self, on: bool) -> None:
        if not on:
            for btn in self._buttons.values():
                btn.hide()
            for bead in self._beads.values():
                bead.hide()
            self.hands_btn.hide()

    def set_open(self, name: str, open: bool) -> None:
        if open:
            self._open.add(name)
        else:
            self._open.discard(name)

    def skip(self, name: str, on: bool) -> None:
        if on:
            self._skip.add(name)
        else:
            self._skip.discard(name)

    def place(self, window_rect: QRect) -> None:
        host = self._host
        win = host.window()
        for name, _t, _oy in FLOATS:
            btn = self._buttons[name]
            bead = self._beads[name]
            parent = win if name in FREE_FLOATS and win is not None else host
            if btn.parent() is not parent:
                btn.setParent(parent)
            if bead.parent() is not parent:
                bead.setParent(parent)
            if name in self._skip:
                btn.hide()
                bead.hide()
                self._breath_title(btn, name, force_off=True)
                continue
            ap = self._field.bead_point(name, window_rect)
            if parent is win:
                local_a = ap.toPoint()
            else:
                local_a = host.mapFrom(win, ap.toPoint()) if win is not None else ap.toPoint()
            bead.show()
            bx = int(local_a.x() - bead.width() / 2)
            by = int(local_a.y() - bead.height() / 2)
            if bead.x() != bx or bead.y() != by:
                bead.move(bx, by)
            bead.raise_()
            if name in self._open:
                btn.hide()
                self._breath_title(btn, name, force_off=True)
                continue
            btn.show()
            p = self._field.title_point(name, window_rect)
            if parent is win:
                local = p.toPoint()
            else:
                local = host.mapFrom(win, p.toPoint()) if win is not None else p.toPoint()
            btn.adjustSize()
            x = int(local.x() - btn.width() / 2)
            y = int(local.y() - btn.height() / 2)
            if btn.x() != x or btn.y() != y:
                btn.move(x, y)
            self._breath_title(btn, name)
            btn.raise_()
        self._place_hands(window_rect)

    def _place_hands(self, window_rect: QRect) -> None:
        from arelis.spatial.grant import world_stage_allowed

        btn = self.hands_btn
        if not world_stage_allowed():
            btn.hide()
            return
        win = self._host.window()
        parent = win if win is not None else self._host
        if btn.parent() is not parent:
            btn.setParent(parent)
        home = self._field.home_rect(window_rect)
        btn.adjustSize()
        x = int(home.left() + 18)
        y = int(home.top() + 8)
        if parent is not win and win is not None:
            mapped = self._host.mapFrom(win, QPoint(x, y))
            x, y = mapped.x(), mapped.y()
        btn.show()
        if btn.x() != x or btn.y() != y:
            btn.move(x, y)
        btn.raise_()

    def set_hands_on(self, on: bool) -> None:
        if self.hands_btn.isChecked() == bool(on):
            return
        self.hands_btn.blockSignals(True)
        self.hands_btn.setChecked(bool(on))
        self.hands_btn.blockSignals(False)

    def _breath_title(self, btn: QPushButton, name: str, *, force_off: bool = False) -> None:
        """Soft opacity clock on a live title. Not a blink."""
        live = (not force_off) and self._field.is_live(name)
        want = "true" if live else "false"
        if btn.property("live") != want:
            btn.setProperty("live", want)
            style = btn.style()
            if style is not None:
                style.unpolish(btn)
                style.polish(btn)
        if not live:
            if btn.graphicsEffect() is not None:
                btn.setGraphicsEffect(None)
            return
        effect = btn.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(btn)
            btn.setGraphicsEffect(effect)
        breath = self._field.live_breath()
        effect.setOpacity(0.62 + 0.38 * breath)


class FilamentChatWindow(QWidget):
    """Chat plate. Own HWND so it can sit on any monitor."""

    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FilamentChatWindow")
        self.setWindowTitle("chat")
        self.resize(380, 400)
        self.setMinimumSize(240, 180)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.Window
        )
        from arelis.ui.glass import GlassFrame, seal_tool_window
        from arelis.ui.icons import window_close_icon
        from arelis.ui.theme import GLASS, METRICS

        seal_tool_window(self, round_corners=True)
        self.setMouseTracking(True)
        self._drag: QPoint | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        plate = GlassFrame(
            self,
            object_name="FilamentChatGlass",
            fill_alpha=int(GLASS.get("fill_float", 255)),
            radius=float(GLASS["radius"]),
            pulse_rim=False,
            round_cutout=True,
        )
        outer.addWidget(plate)
        root = QVBoxLayout(plate)
        root.setContentsMargins(14, 8, 10, 12)
        root.setSpacing(8)
        head = QHBoxLayout()
        title = QLabel("chat")
        title.setObjectName("SettingsHeading")
        title.setCursor(Qt.CursorShape.OpenHandCursor)
        title.installEventFilter(self)
        head.addWidget(title, stretch=1)
        close_btn = QToolButton()
        close_btn.setObjectName("SettingsClose")
        close_btn.setIcon(window_close_icon(12))
        close_btn.setFixedSize(METRICS["row"], METRICS["row"])
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setToolTip("hide chat — talk still works")
        close_btn.clicked.connect(self.close)
        head.addWidget(close_btn)
        root.addLayout(head)
        self.body = QWidget()
        self.body.setObjectName("FilamentChatBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        root.addWidget(self.body, stretch=1)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        from arelis.ui.window_resize import enable_win32_resize_frame

        enable_win32_resize_frame(self)
        self.setMouseTracking(True)

    def changeEvent(self, event) -> None:  # type: ignore[override]
        from PySide6.QtCore import QEvent

        from arelis.ui.window_resize import enable_win32_resize_frame

        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            if not (self.isMaximized() or self.isFullScreen()):
                enable_win32_resize_frame(self)

    def nativeEvent(self, eventType, message):
        from arelis.ui.window_resize import handle_native_resize

        handled = handle_native_resize(self, eventType, message)
        if handled is not None:
            return handled
        return super().nativeEvent(eventType, message)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        from arelis.ui.window_resize import try_system_resize

        if event.button() == Qt.MouseButton.LeftButton:
            if try_system_resize(self, event.globalPosition().toPoint()):
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        from arelis.ui.window_resize import cursor_for_hit, hit_test_resize

        shape = cursor_for_hit(hit_test_resize(self))
        if shape is not None:
            self.setCursor(shape)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def eventFilter(self, obj, event):  # type: ignore[override]
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QMouseEvent

        from arelis.ui.window_resize import try_system_resize

        if event.type() == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            if event.button() == Qt.MouseButton.LeftButton:
                if try_system_resize(self, event.globalPosition().toPoint()):
                    return True
                self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return True
        if event.type() == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
            if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
                if not (self.isMaximized() or self.isFullScreen()):
                    self.move(event.globalPosition().toPoint() - self._drag)
                return True
        if event.type() == QEvent.Type.MouseButtonRelease:
            self._drag = None
        return super().eventFilter(obj, event)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.closed.emit()
        super().closeEvent(event)
