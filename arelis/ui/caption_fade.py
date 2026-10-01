"""Hide window chrome until the pointer is in that corner.

Minimize, maximize, and close — whatever subset a plate actually has — ease
in together. Sodium and filament share the timing.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QRect,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QCursor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton, QWidget

_APPROACH_X = 48
_APPROACH_Y = 6
_HIDE_MS = 220
_FADE_IN_MS = 140
_FADE_OUT_MS = 180
_POLL_MS = 16

# Names the tests patch. Kept as module globals so a zero-duration check can
# shorten the fade without touching the widgets.
_CAPTION_APPROACH_X = _APPROACH_X
_CAPTION_APPROACH_Y = _APPROACH_Y
_CAPTION_HIDE_MS = _HIDE_MS
_CAPTION_FADE_IN_MS = _FADE_IN_MS
_CAPTION_FADE_OUT_MS = _FADE_OUT_MS
_CAPTION_POLL_MS = _POLL_MS


def _init_fade(widget: QWidget) -> None:
    widget._strength = 0.0  # type: ignore[attr-defined]
    widget._fade_buffer = None  # type: ignore[attr-defined]
    widget._painting_source = False  # type: ignore[attr-defined]
    widget.setAutoFillBackground(False)
    widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
    # Non-opaque so a fade repaints the plate under the glyph. An opaque
    # button keeps the last frame, so the icon would stay after it left.
    widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)


def _render_full(widget: QWidget) -> QPixmap:
    dpr = widget.devicePixelRatioF() or 1.0
    buffer = QPixmap(
        max(1, round(widget.width() * dpr)),
        max(1, round(widget.height() * dpr)),
    )
    buffer.setDevicePixelRatio(dpr)
    buffer.fill(Qt.GlobalColor.transparent)
    widget._painting_source = True  # type: ignore[attr-defined]
    try:
        widget.render(buffer)
    finally:
        widget._painting_source = False  # type: ignore[attr-defined]
    return buffer


def _refresh_under(widget: QWidget) -> None:
    parent = widget.parentWidget()
    if parent is None:
        return
    parent.update(widget.geometry())
    grand = parent.parentWidget()
    if grand is not None:
        grand.update(parent.geometry())


def set_fade_strength(widget: QWidget, value: float) -> None:
    value = 0.0 if value < 0.0 else 1.0 if value > 1.0 else float(value)
    widget._strength = value  # type: ignore[attr-defined]
    if value <= 0.02 or value >= 0.98 or widget.width() < 2 or widget.height() < 2:
        widget._fade_buffer = None  # type: ignore[attr-defined]
    else:
        # Opacity on the widget's painter does not scale the glyph. Bake the
        # strength into a pixmap, where it does, and draw that.
        full = _render_full(widget)
        faded = QPixmap(full.size())
        faded.setDevicePixelRatio(full.devicePixelRatio())
        faded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(faded)
        try:
            painter.setOpacity(value)
            painter.drawPixmap(0, 0, full)
        finally:
            painter.end()
        widget._fade_buffer = faded  # type: ignore[attr-defined]
    widget.update()
    _refresh_under(widget)


def paint_faded(widget: QWidget, event, base_paint: Callable[..., None]) -> None:
    if widget._painting_source:  # type: ignore[attr-defined]
        base_paint(widget, event)
        return
    strength = widget._strength  # type: ignore[attr-defined]
    buffer = widget._fade_buffer  # type: ignore[attr-defined]
    if strength <= 0.02:
        return
    if strength >= 0.98:
        base_paint(widget, event)
        return
    if buffer is None or buffer.isNull():
        return
    painter = QPainter(widget)
    try:
        painter.drawPixmap(0, 0, buffer)
    finally:
        painter.end()


class CaptionButton(QPushButton):
    """Push-button window glyph that can fade out. Used by the main chrome."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _init_fade(self)

    def set_strength(self, value: float) -> None:
        set_fade_strength(self, value)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        paint_faded(self, event, QPushButton.paintEvent)


class CaptionTool(QToolButton):
    """Tool-button window glyph that can fade out. Used by the plates."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _init_fade(self)

    def set_strength(self, value: float) -> None:
        set_fade_strength(self, value)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        paint_faded(self, event, QToolButton.paintEvent)


class CaptionHover(QObject):
    """Fade a plate's window buttons while the pointer is away from them."""

    def __init__(
        self,
        host: QWidget,
        buttons: tuple[QWidget, ...],
        *,
        zone: QWidget | None = None,
    ) -> None:
        super().__init__(host)
        self._host = host
        self._buttons = buttons
        self._zone = zone
        self.opacity = 0.0
        self.anim = QVariantAnimation(self)
        self.anim.valueChanged.connect(self._on_opacity)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide_if_idle)
        self.poll = QTimer(self)
        self.poll.setInterval(_CAPTION_POLL_MS)
        self.poll.timeout.connect(self.sync)
        self._set_hit(False)
        host.installEventFilter(self)
        if host.isVisible():
            self.poll.start()
            self.sync()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if watched is self._host:
            kind = event.type()
            if kind == QEvent.Type.Show:
                if not self.poll.isActive():
                    self.poll.start()
                self.sync()
            elif kind == QEvent.Type.Hide:
                self.poll.stop()
                self.hide_timer.stop()
                self.anim.stop()
            elif kind in (
                QEvent.Type.MouseMove,
                QEvent.Type.MouseButtonRelease,
                QEvent.Type.Leave,
            ):
                self.sync()
        return False

    def _on_opacity(self, value: object) -> None:
        if value is None:
            return
        self.opacity = max(0.0, min(1.0, float(value)))
        for btn in self._buttons:
            setter = getattr(btn, "set_strength", None)
            if callable(setter):
                setter(self.opacity)

    def _set_hit(self, interactive: bool) -> None:
        targets = [self._zone] if self._zone is not None else list(self._buttons)
        flag = Qt.WidgetAttribute.WA_TransparentForMouseEvents
        for widget in targets:
            if widget is None:
                continue
            if widget.testAttribute(flag) == interactive:
                widget.setAttribute(flag, not interactive)

    def _fade(self, show: bool) -> None:
        target = 1.0 if show else 0.0
        anim = self.anim
        running = anim.state() == QAbstractAnimation.State.Running
        end = anim.endValue()
        if running and end is not None and abs(float(end) - target) < 0.001:
            return
        if not running and abs(self.opacity - target) < 0.001:
            self._set_hit(show)
            return
        anim.stop()
        anim.setDuration(_CAPTION_FADE_IN_MS if show else _CAPTION_FADE_OUT_MS)
        anim.setEasingCurve(
            QEasingCurve.Type.OutCubic if show else QEasingCurve.Type.InCubic
        )
        anim.setStartValue(self.opacity)
        anim.setEndValue(target)
        self._set_hit(show)
        anim.start()

    def hide_if_idle(self) -> None:
        if self.cursor_near() or self.pinned():
            return
        self._fade(False)

    def pinned(self) -> bool:
        app = QApplication.instance()
        if app is None:
            return False
        focus = app.focusWidget()
        if focus is None:
            return False
        if self._zone is not None and (focus is self._zone or self._zone.isAncestorOf(focus)):
            return True
        return any(focus is btn or btn.isAncestorOf(focus) for btn in self._buttons)

    def _host_dragging(self) -> bool:
        host = self._host
        for name in ("_drag_pos", "_drag_origin", "_drag"):
            if isinstance(getattr(host, name, None), QPoint):
                return True
        return False

    def _zone_rect(self) -> QRect | None:
        zone = self._zone
        if zone is not None and zone.isVisible() and zone.width() >= 8 and zone.height() >= 8:
            rect = QRect(zone.mapToGlobal(QPoint(0, 0)), zone.size())
        else:
            rect = None
            for btn in self._buttons:
                if not btn.isVisible() or btn.width() < 8 or btn.height() < 8:
                    continue
                piece = QRect(btn.mapToGlobal(QPoint(0, 0)), btn.size())
                rect = piece if rect is None else rect.united(piece)
            if rect is None:
                return None
        return rect.adjusted(-_CAPTION_APPROACH_X, -4, 12, _CAPTION_APPROACH_Y)

    def cursor_near(self) -> bool:
        if self._host_dragging() or not self._host.isVisible():
            return False
        rect = self._zone_rect()
        if rect is None:
            return False
        return rect.contains(QCursor.pos())

    def sync(self) -> None:
        if self.cursor_near() or self.pinned():
            self.hide_timer.stop()
            self._fade(True)
            return
        if self.opacity <= 0.02 and self.anim.state() != QAbstractAnimation.State.Running:
            return
        if not self.hide_timer.isActive():
            self.hide_timer.setInterval(_CAPTION_HIDE_MS)
            self.hide_timer.start()


def watch_caption(
    host: QWidget,
    *buttons: QWidget,
    zone: QWidget | None = None,
) -> CaptionHover:
    """Fade these chrome buttons until the pointer is near them."""
    for btn in buttons:
        if not callable(getattr(btn, "set_strength", None)):
            raise TypeError("window chrome buttons must be CaptionButton or CaptionTool")
    return CaptionHover(host, buttons, zone=zone)
