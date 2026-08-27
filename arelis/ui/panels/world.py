"""The physics-room world: one sphere in z. Chat stays in Arelis."""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QPoint, QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPen,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import QLabel, QSizePolicy, QSlider, QWidget

from arelis.spatial.depth import world_to_apparent
from arelis.spatial.scene import (
    REACH_MAX,
    REACH_MIN,
    SPAWN_KINDS,
    WorldScene,
    clamp_reach,
    polygon_xy,
)
from arelis.ui.stage import paint_corner_ticks
from arelis.ui.theme import color


def make_reach_control(parent: QWidget | None, reach: float) -> tuple[QSlider, QLabel]:
    """Feel slider. Hands only — mouse on this plane stays 1:1 pixels."""
    value = clamp_reach(reach)
    slider = QSlider(Qt.Orientation.Horizontal, parent)
    slider.setObjectName("SettingsSlider")
    slider.setRange(int(round(REACH_MIN * 100)), int(round(REACH_MAX * 100)))
    slider.setSingleStep(5)
    slider.setPageStep(10)
    slider.setFixedWidth(128)
    slider.setValue(int(round(value * 100)))
    slider.setToolTip("Reach — how far a small hand move goes. Like mouse DPI.")
    label = QLabel(f"{value:.2f}x", parent)
    label.setObjectName("InstrumentHint")
    label.setFixedWidth(42)
    return slider, label


class WorldPanel(QWidget):
    """Paints the plane. Mouse is the control; a fist uses the same scene."""

    changed = Signal()

    def __init__(self, scene: WorldScene, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("WorldPanel")
        self.setMinimumSize(360, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.scene = scene
        self._dragging = False
        self._tools_open = False
        self._sheet_open = False
        self._hands: list[tuple[float, float, float, float, bool]] = []
        self._flashes: list[float] = []
        self._lock_flash = 0.0
        self._pulse = QTimer(self)
        self._pulse.setInterval(40)
        self._pulse.timeout.connect(self._tick_flash)
        self._clock = QTimer(self)
        self._clock.setInterval(16)
        self._clock.timeout.connect(self._tick_physics)
        self._phys_t = time.perf_counter()
        self.menu_up = False

    def set_aperture(
        self,
        thumb: tuple[float, float],
        index: tuple[float, float],
        *,
        pinched: bool,
    ) -> None:
        """One hand. Prefer set_apertures when both are in frame."""
        self.set_apertures(((thumb, index, pinched),))

    def set_apertures(
        self,
        items: list[tuple[tuple[float, float], tuple[float, float], bool]]
        | tuple[tuple[tuple[float, float], tuple[float, float], bool], ...],
    ) -> None:
        """Glow is per close — left does not light with right."""
        prev = [bool(row[4]) for row in self._hands]
        hands: list[tuple[float, float, float, float, bool]] = []
        flashes = list(self._flashes)
        while len(flashes) < len(items):
            flashes.append(0.0)
        flashes = flashes[: len(items)]
        for i, (thumb, index, pinched) in enumerate(items):
            was = prev[i] if i < len(prev) else False
            if pinched and not was:
                flashes[i] = 1.0
                self._pulse.start()
            hands.append(
                (
                    float(thumb[0]),
                    float(thumb[1]),
                    float(index[0]),
                    float(index[1]),
                    bool(pinched),
                )
            )
        self._hands = hands
        self._flashes = flashes
        self._lock_flash = max(self._flashes) if self._flashes else 0.0
        self.update()

    def clear_hand(self) -> None:
        self._hands = []
        self._flashes = []
        self._lock_flash = 0.0
        self._pulse.stop()
        self.update()

    def _tick_flash(self) -> None:
        self._flashes = [max(0.0, flash - 0.08) for flash in self._flashes]
        self._lock_flash = max(self._flashes) if self._flashes else 0.0
        if self._lock_flash <= 0.0:
            self._pulse.stop()
        self.update()

    def refresh(self) -> None:
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._phys_t = time.perf_counter()
        self._clock.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._clock.stop()
        super().hideEvent(event)

    def _tick_physics(self) -> None:
        now = time.perf_counter()
        dt = now - self._phys_t
        self._phys_t = now
        if self.menu_up:
            return
        self.scene.step(dt)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), color("bg0"))
        paint_corner_ticks(painter, self.rect(), inset=18, length=12)
        for disc in self.scene.bodies:
            self._paint_disc(painter, disc)
        self._paint_hands(painter)
        self._paint_tools(painter)
        if self._sheet_open and self.scene.selected is not None:
            self._paint_sheet(painter)

    def _paint_disc(self, painter: QPainter, disc) -> None:
        cx, cy = self._to_px(disc.x, disc.y)
        rad = float(disc.radius)
        if disc.kind == "sphere":
            rad = world_to_apparent(disc.radius, disc.z)
        radius = max(8, int(rad * min(self.width(), self.height())))
        ring = color("accent2") if disc.attached else color("accent")
        if disc.frozen:
            ring = color("text_dim")
        width = 3 if disc.attached else 2
        if disc.mass > 1.2:
            width += 1
        if disc.mass < 0.8:
            width = max(1, width - 1)
        if disc.kind == "sphere":
            self._paint_sphere(painter, disc, cx, cy, radius, ring, width)
        else:
            poly = polygon_xy(disc)
            fill = QColor(255, 122, 34, 36 if disc.attached else 22)
            pen = QPen(ring)
            pen.setWidth(width)
            painter.setPen(pen)
            painter.setBrush(fill)
            if poly:
                shape = QPolygonF(
                    [QPointF(*self._to_px(px, py)) for px, py in poly]
                )
                painter.drawPolygon(shape)
            else:
                painter.drawEllipse(QPoint(cx, cy), radius, radius)
            painter.setBrush(ring)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPoint(cx, cy), 3, 3)
            if disc.attached:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(color("text"), 1.4))
                painter.drawEllipse(QPoint(cx, cy), 10, 10)
        if self.scene.selected is disc:
            mark = QPen(color("text"))
            mark.setWidth(1)
            painter.setPen(mark)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPoint(cx, cy), radius + 5, radius + 5)
        if disc.scaler:
            dash = QPen(color("accent2"))
            dash.setWidth(1)
            dash.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(dash)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPoint(cx, cy), radius + 7, radius + 7)
        self._paint_spin(painter, disc, cx, cy, radius, ring)

    def _paint_spin(
        self,
        painter: QPainter,
        disc,
        cx: int,
        cy: int,
        radius: int,
        ring: QColor,
    ) -> None:
        """Rim pip + tick so a sphere can show spin the same as an n-gon.

        Axes on: opposite pip (CW vs CCW) and a tilt meridian. Not XYZ —
        only spin and tilt exist on this plane.
        """
        reach = max(6, int(radius * max(0.38, abs(math.cos(float(disc.tilt))))))
        a = float(disc.angle) - math.pi / 2.0
        ca, sa = math.cos(a), math.sin(a)
        mx = int(round(cx + reach * ca))
        my = int(round(cy + reach * sa))
        inner = max(4, int(radius * 0.45))
        ix = int(round(cx + inner * ca))
        iy = int(round(cy + inner * sa))
        tick = QPen(ring)
        tick.setWidth(2)
        painter.setPen(tick)
        painter.drawLine(QPoint(ix, iy), QPoint(mx, my))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color("text"))
        painter.drawEllipse(QPoint(mx, my), 4, 4)
        if not disc.axes_on:
            return
        ox = int(round(cx - reach * ca))
        oy = int(round(cy - reach * sa))
        painter.drawEllipse(QPoint(ox, oy), 3, 3)
        painter.setPen(tick)
        painter.drawLine(QPoint(cx, cy), QPoint(ox, oy))
        tilt_reach = max(5, int(radius * 0.82 * abs(math.cos(float(disc.tilt)))))
        px = int(round(cx - tilt_reach * sa))
        py = int(round(cy + tilt_reach * ca))
        qx = int(round(cx + tilt_reach * sa))
        qy = int(round(cy - tilt_reach * ca))
        meridian = QPen(color("text_dim"))
        meridian.setWidth(1)
        painter.setPen(meridian)
        painter.drawLine(QPoint(px, py), QPoint(qx, qy))
        painter.setPen(color("text"))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(mx + 6, my - 2, "spin")
        painter.drawText(qx + 4, qy + 4, "tilt")

    def _paint_sphere(
        self,
        painter: QPainter,
        disc,
        cx: int,
        cy: int,
        radius: int,
        ring: QColor,
        width: int,
    ) -> None:
        depth = min(1.0, max(0.0, float(disc.z)))
        shade = QColor(0, 0, 0, int(36 + 28 * depth))
        shadow_r = max(6, int(radius * (0.50 + 0.22 * depth)))
        shadow_y = cy + int(radius * (0.58 + 0.22 * depth))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shade)
        painter.drawEllipse(QPoint(cx, shadow_y), shadow_r, max(4, shadow_r // 3))
        hx = float(cx) - radius * 0.34
        hy = float(cy) - radius * 0.34
        ball = QRadialGradient(QPointF(hx, hy), float(max(radius, 8)) * 1.2)
        # Opaque. Alpha on the fill read as a ring; the spec read as a dot.
        lit = QColor(255, 220, 160) if disc.attached else QColor(255, 206, 128)
        mid = QColor(255, 138, 42) if disc.attached else QColor(255, 122, 34)
        dark = QColor(72, 28, 6)
        ball.setColorAt(0.0, lit)
        ball.setColorAt(0.42, mid)
        ball.setColorAt(1.0, dark)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ball)
        painter.drawEllipse(QPoint(cx, cy), radius, radius)
        spec = max(3, int(radius * 0.16))
        painter.setBrush(QColor(255, 240, 210))
        painter.drawEllipse(QPoint(int(hx), int(hy)), spec, spec)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        px = int(event.position().x())
        py = int(event.position().y())
        if event.button() == Qt.MouseButton.RightButton:
            self._tools_open = False
            x, y = self._from_px(px, py)
            body = self.scene.select_at(x, y)
            self._sheet_open = body is not None
            self.update()
            self.changed.emit()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._dots_rect().contains(px, py):
            self._tools_open = not self._tools_open
            self._sheet_open = False
            self.update()
            return
        if self._tools_open:
            kind = self._spawn_hit(px, py)
            if kind is not None:
                self.scene.spawn(kind)
                self.update()
                self.changed.emit()
                return
            if self._gravity_hit(px, py):
                self.scene.set_gravity(not self.scene.gravity)
                self.update()
                self.changed.emit()
                return
            if self._tools_rect().contains(px, py):
                return
            self._tools_open = False
        if self._sheet_open:
            if self._lock_hit(px, py):
                body = self.scene.selected
                if body is not None:
                    body.size_locked = not body.size_locked
                self.update()
                self.changed.emit()
                return
            if self._axes_hit(px, py):
                body = self.scene.selected
                if body is not None:
                    body.axes_on = not body.axes_on
                self.update()
                self.changed.emit()
                return
            if self._delete_hit(px, py):
                self.scene.delete()
                self._sheet_open = False
                self.update()
                self.changed.emit()
                return
            if self._sheet_rect().contains(px, py):
                return
            self._sheet_open = False
        x, y = self._from_px(px, py)
        self.scene.select_at(x, y)
        if self.scene.near_any(x, y):
            self._dragging = True
            self.scene.apply_pointer(x, y, True, t=time.perf_counter())
        self.update()
        self.changed.emit()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._dragging:
            return
        x, y = self._from_px(event.position().x(), event.position().y())
        self.scene.apply_pointer(x, y, True, t=time.perf_counter())
        self.update()
        self.changed.emit()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._dragging:
            x, y = self._from_px(event.position().x(), event.position().y())
            self.scene.apply_pointer(x, y, False, t=time.perf_counter())
            self._dragging = False
            self.update()
            self.changed.emit()

    def _paint_hands(self, painter: QPainter) -> None:
        for i, (tx, ty, ix, iy, pinched) in enumerate(self._hands):
            flash = self._flashes[i] if i < len(self._flashes) else 0.0
            self._paint_aperture(painter, tx, ty, ix, iy, pinched, flash)

    def _paint_aperture(
        self,
        painter: QPainter,
        tx: float,
        ty: float,
        ix: float,
        iy: float,
        pinched: bool,
        flash: float,
    ) -> None:
        p0 = QPoint(*self._to_px(tx, ty))
        p1 = QPoint(*self._to_px(ix, iy))
        mid = QPoint((p0.x() + p1.x()) // 2, (p0.y() + p1.y()) // 2)
        if pinched or flash > 0:
            span = 28 + int(36 * flash)
            held = 18 if pinched else 0
            glow = QRadialGradient(QPointF(mid), float(max(span, held)))
            alpha = 20 + int(70 * flash) + (16 if pinched else 0)
            core = color("accent2")
            core.setAlpha(min(120, alpha))
            edge = color("accent")
            edge.setAlpha(0)
            glow.setColorAt(0.0, core)
            glow.setColorAt(1.0, edge)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(mid, span, span)
        ink = color("text") if pinched else color("accent2")
        painter.setBrush(ink)
        painter.setPen(Qt.PenStyle.NoPen)
        if pinched:
            # One mark. A chord between close tips flips every frame.
            painter.drawEllipse(mid, 5, 5)
            return
        pen = QPen(ink)
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawLine(p0, p1)
        painter.setBrush(ink)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(p0, 3, 3)
        painter.drawEllipse(p1, 3, 3)

    def _dots_rect(self) -> QRect:
        box = self._plane()
        return QRect(box.right() - 30, box.top() + 4, 24, 16)

    def _tools_rect(self) -> QRect:
        dots = self._dots_rect()
        box = self._plane()
        w, h = 188, 86
        x = min(max(box.left(), dots.right() - w), box.right() - w)
        y = min(dots.bottom() + 6, box.bottom() - h)
        return QRect(x, y, w, h)

    def _chip_rects(self) -> list[tuple[str, QRect]]:
        panel = self._tools_rect().adjusted(8, 22, -8, -28)
        n = len(SPAWN_KINDS)
        w = max(18, panel.width() // n)
        rows: list[tuple[str, QRect]] = []
        for i, (kind, _) in enumerate(SPAWN_KINDS):
            rows.append((kind, QRect(panel.left() + i * w, panel.top(), w - 2, panel.height())))
        return rows

    def _gravity_rect(self) -> QRect:
        panel = self._tools_rect()
        return QRect(panel.left() + 8, panel.bottom() - 22, panel.width() - 16, 16)

    def _sheet_rect(self) -> QRect:
        body = self.scene.selected
        box = self._plane()
        w, h = 128, 94
        if body is None:
            return QRect(box.left() + 8, box.top() + 8, w, h)
        cx, cy = self._to_px(body.x, body.y)
        x = min(max(box.left(), cx + 14), box.right() - w)
        y = min(max(box.top(), cy - h // 2), box.bottom() - h)
        return QRect(x, y, w, h)

    def _lock_rect(self) -> QRect:
        sheet = self._sheet_rect()
        return QRect(sheet.left() + 8, sheet.top() + 22, sheet.width() - 16, 20)

    def _axes_rect(self) -> QRect:
        sheet = self._sheet_rect()
        return QRect(sheet.left() + 8, sheet.top() + 44, sheet.width() - 16, 20)

    def _delete_rect(self) -> QRect:
        sheet = self._sheet_rect()
        return QRect(sheet.left() + 8, sheet.top() + 66, sheet.width() - 16, 20)

    def _spawn_hit(self, px: float, py: float) -> str | None:
        for kind, rect in self._chip_rects():
            if rect.contains(int(px), int(py)):
                return kind
        return None

    def _gravity_hit(self, px: float, py: float) -> bool:
        return self._gravity_rect().contains(int(px), int(py))

    def _lock_hit(self, px: float, py: float) -> bool:
        return self._lock_rect().contains(int(px), int(py))

    def _axes_hit(self, px: float, py: float) -> bool:
        return self._axes_rect().contains(int(px), int(py))

    def _delete_hit(self, px: float, py: float) -> bool:
        return self._delete_rect().contains(int(px), int(py))

    def _paint_tools(self, painter: QPainter) -> None:
        dots = self._dots_rect()
        ink = color("text_dim")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ink)
        cy = dots.center().y()
        gap = 6
        x0 = dots.center().x() - gap
        for i in range(3):
            painter.drawEllipse(QPoint(x0 + i * gap, cy), 2, 2)
        if not self._tools_open:
            return
        panel = self._tools_rect()
        painter.setBrush(QColor(22, 13, 7, 230))
        painter.setPen(QPen(color("edge"), 1))
        painter.drawRoundedRect(panel, 6, 6)
        painter.setPen(color("text_dim"))
        painter.drawText(panel.adjusted(8, 4, -8, -60), Qt.AlignmentFlag.AlignLeft, "Tools")
        for kind, rect in self._chip_rects():
            self._paint_chip(painter, kind, rect)
        grav = self._gravity_rect()
        on = self.scene.gravity
        painter.setPen(color("text") if on else color("text_dim"))
        label = "Gravity on" if on else "Gravity off"
        painter.drawText(grav, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)

    def _paint_chip(self, painter: QPainter, kind: str, rect: QRect) -> None:
        cx, cy = rect.center().x(), rect.center().y()
        r = min(rect.width(), rect.height()) * 0.32
        ink = color("accent")
        painter.setPen(QPen(ink, 1))
        painter.setBrush(QColor(255, 122, 34, 40))
        if kind == "sphere":
            painter.drawEllipse(QPoint(cx, cy), int(r), int(r))
            return
        sides = next((n for name, n in SPAWN_KINDS if name == kind), 0)
        if sides < 3:
            return
        pts = []
        spin = -math.pi / 2.0
        for i in range(sides):
            a = spin + 2.0 * math.pi * i / sides
            pts.append(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
        painter.drawPolygon(QPolygonF(pts))

    def _paint_sheet(self, painter: QPainter) -> None:
        body = self.scene.selected
        if body is None:
            return
        sheet = self._sheet_rect()
        painter.setBrush(QColor(22, 13, 7, 230))
        painter.setPen(QPen(color("edge"), 1))
        painter.drawRoundedRect(sheet, 6, 6)
        painter.setPen(color("text_dim"))
        painter.drawText(sheet.adjusted(8, 4, -8, -50), Qt.AlignmentFlag.AlignLeft, body.kind)
        lock = self._lock_rect()
        mark = "on" if body.size_locked else "off"
        painter.setPen(color("text"))
        painter.drawText(
            lock,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            f"Lock size {mark}  {body.radius:.2f}",
        )
        axes = "on" if body.axes_on else "off"
        painter.setPen(color("text"))
        painter.drawText(
            self._axes_rect(),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            f"Axes {axes}",
        )
        painter.setPen(color("accent"))
        painter.drawText(
            self._delete_rect(),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "Delete",
        )

    def _plane(self) -> QRect:
        inset = 28
        return self.rect().adjusted(inset, inset, -inset, -inset)

    def _to_px(self, x: float, y: float) -> tuple[int, int]:
        box = self._plane()
        return (
            int(box.left() + x * box.width()),
            int(box.top() + y * box.height()),
        )

    def _from_px(self, px: float, py: float) -> tuple[float, float]:
        box = self._plane()
        if box.width() < 1 or box.height() < 1:
            return (0.5, 0.5)
        return (
            (px - box.left()) / box.width(),
            (py - box.top()) / box.height(),
        )
