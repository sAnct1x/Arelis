from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, QRect, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QRegion,
)
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QWidget

from arelis.ui.theme import GLASS, HAIRLINE, PLATE, color

# The plate is lit from above by the same lamp as everything else. Rim alphas
# come from GLASS / HAIRLINE so a dock, a float, and the composer line stay
# one light. Read live — apply_theme mutates those dicts in place.

_CLEAR = QColor(0, 0, 0, 0)


def _alpha(base: QColor, value: float) -> QColor:
    return QColor(base.red(), base.green(), base.blue(), max(0, min(255, int(value))))

# Shared slow rim breath — driven by the main window atmosphere timer.
_rim_pulse_phase = 0.0


def set_rim_pulse_phase(phase: float) -> None:
    """Set global rim pulse phase in radians (shared across all GlassFrames)."""
    global _rim_pulse_phase
    _rim_pulse_phase = float(phase) % 6.283185307179586


def advance_rim_pulse(dt_seconds: float = 0.1) -> float:
    """Advance pulse by wall time; returns new phase."""
    period = max(1.5, float(GLASS.get("rim_pulse_seconds", 6.0)))
    set_rim_pulse_phase(_rim_pulse_phase + (6.283185307179586 * dt_seconds / period))
    return _rim_pulse_phase


def _pulse_rim_alpha(lo: int | None = None, hi: int | None = None) -> int:
    lo_a = int(GLASS.get("rim_pulse_lo", 68) if lo is None else lo)
    hi_a = int(GLASS.get("rim_pulse_hi", 128) if hi is None else hi)
    t = (math.sin(_rim_pulse_phase) + 1.0) * 0.5
    return int(lo_a + (hi_a - lo_a) * t)


class GlassFrame(QFrame):
    """Void plate — opaque warm fill on floats, amber hairline rim."""

    def __init__(
        self,
        parent=None,
        *,
        object_name: str = "GlassPanel",
        fill_alpha: int | None = None,
        radius: float | None = None,
        pulse_rim: bool = False,
        round_cutout: bool = False,
        surface_owned: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        # True when something else decides this widget's HWND surface — see
        # _apply_seal.
        self._surface_owned = bool(surface_owned)
        self._fill_alpha = int(
            GLASS.get("fill_docked", 72) if fill_alpha is None else fill_alpha
        )
        self._radius = float(GLASS.get("radius", 12.0) if radius is None else radius)
        self._pulse_rim = bool(pulse_rim)
        # Paint hint: skip the sharp fillRect. The parent HWND stays opaque
        # and is clipped with a mask — do not punch a translucent hole here.
        self._round_cutout = bool(round_cutout)
        self._attention = False
        self._ember = False
        self._attention_phase = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._apply_seal()

    def set_fill_alpha(self, fill_alpha: int) -> None:
        """Raise/lower body opacity (floating docks use smoked fill)."""
        self._fill_alpha = max(0, min(255, int(fill_alpha)))
        self._apply_seal()
        self.update()

    def _apply_seal(self) -> None:
        """Opaque floats must not stay a translucent HWND — chat ghosts through.

        Skipped when the surface is owned elsewhere. Deriving translucency from
        fill alpha is a reasonable default for a lone plate, but on a dock it is
        a second writer racing arelis.ui.dock_surface, and losing that race by
        one frame is how a float ends up layered.
        """
        if self._surface_owned:
            return
        sealed = self._fill_alpha >= 240
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, not sealed)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, sealed)
        self.setAutoFillBackground(False)

    def set_pulse_rim(self, enabled: bool) -> None:
        self._pulse_rim = bool(enabled)
        self.update()

    def set_attention(self, enabled: bool, *, ember: bool = False) -> None:
        """Warm rim for an unfocused chat tile. ember = steady, not breathing."""
        if ember:
            self._attention = False
            self._ember = True
        elif enabled:
            self._attention = True
            self._ember = False
            self._attention_phase = 0.0
        else:
            self._attention = False
            self._ember = False
        self.update()

    def advance_attention(self, dt_seconds: float = 0.1) -> None:
        """Local ~2s breath. Does not touch the global rim phase."""
        if not self._attention:
            return
        self._attention_phase = (
            self._attention_phase + (6.283185307179586 * dt_seconds / 2.0)
        ) % 6.283185307179586

    @property
    def has_attention(self) -> bool:
        return self._attention or self._ember

    def paintEvent(self, event: QPaintEvent) -> None:
        a = self._fill_alpha
        # Docked instruments are type in the void (alpha 0) — no plate.
        # A one-shot attention rim still has to paint, or a click on
        # "thinking…" cannot flash that dock without turning it into a TV.
        rim_only = a <= 4 and (self._pulse_rim or self._attention or self._ember)
        if a <= 4 and not rim_only:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)

        # Near-opaque floating plates: seal the body so other HWNDs (chat) cannot
        # composite through. Void is a color, not a transparent HWND.
        # Round-cutout plates skip the sharp fillRect — that was the black frame.
        catch = color("accent2")
        glint = color("accent")
        if not rim_only:
            if a >= 240:
                if not self._round_cutout:
                    painter.fillRect(self.rect(), QColor(*PLATE["seal"]))
                painter.fillPath(path, QColor(*PLATE["body"]))
            body = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            if a >= 240:
                for stop, (r, g, b) in PLATE["opaque"]:
                    body.setColorAt(stop, QColor(r, g, b, 255))
            else:
                for stop, (r, g, b), lift in PLATE["smoked"]:
                    body.setColorAt(stop, QColor(r, g, b, max(28, min(255, a + lift))))
            painter.fillPath(path, body)

            sheen = QLinearGradient(rect.topLeft(), rect.bottomRight())
            if a >= 240:
                sheen.setColorAt(0.0, _alpha(catch, 80))
                sheen.setColorAt(0.22, _alpha(glint, 36))
            else:
                sheen.setColorAt(0.0, _alpha(catch, 36))
                sheen.setColorAt(0.22, _alpha(glint, 16))
            sheen.setColorAt(1.0, _CLEAR)
            painter.fillPath(path, sheen)

        # Floats need an edge you can see. Docked plates skip this unless a
        # one-shot click pulse asked for a hairline (rim_only).
        # No outer glow — that was the three-TV silhouette.
        rest = int(HAIRLINE["rest"])
        live = int(HAIRLINE["live"])
        if self._attention or self._ember:
            if self._attention:
                t = (math.sin(self._attention_phase) + 1.0) * 0.5
                rim_a = int(rest + (live - rest) * t)
                if not rim_only:
                    glow = QLinearGradient(rect.topLeft(), rect.bottomRight())
                    glow.setColorAt(0.0, _alpha(glint, 44 + 36 * t))
                    glow.setColorAt(0.35, _alpha(catch, 20 + 18 * t))
                    glow.setColorAt(1.0, _CLEAR)
                    painter.fillPath(path, glow)
            else:
                rim_a = live
            width = 2.4
        else:
            if a >= 240:
                rim_a = int(GLASS["rim_pulse_hi"]) if not self._pulse_rim else _pulse_rim_alpha()
            else:
                rim_a = rest if not self._pulse_rim else _pulse_rim_alpha()
            width = 1.15
        pen = QPen(_alpha(glint, rim_a))
        pen.setWidthF(width)
        painter.setPen(pen)
        painter.drawPath(path)


class Hairline(QWidget):
    """The 1px amber rule under the composer, and its listening breath.

    A widget rather than a stylesheet because the breath is a continuous alpha
    and a stylesheet can only be reassigned as a whole string. Both callers
    used to rebuild `background: rgba(255, 180, 87, N)` twenty times a second,
    which put the accent colour in two files that the palette does not reach.
    """

    def __init__(self, parent=None, *, width: int | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("VoidHairline")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedHeight(1)
        if width is not None:
            self.setFixedWidth(int(width))
        self._glow = int(HAIRLINE["rest"])

    def set_glow(self, alpha: int) -> None:
        wanted = max(int(HAIRLINE["rest"]), min(int(HAIRLINE["live"]), int(alpha)))
        if wanted != self._glow:
            self._glow = wanted
            self.update()

    def rest(self) -> None:
        self.set_glow(int(HAIRLINE["rest"]))

    @property
    def glow(self) -> int:
        return self._glow

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), _alpha(color("accent"), self._glow))


def apply_round_window_mask(widget: QWidget, radius: float | None = None) -> None:
    """Clip an opaque HWND to the glass radius so corner wedges are gone."""
    if widget.width() <= 0 or widget.height() <= 0:
        return
    r = float(GLASS.get("radius", 12.0) if radius is None else radius)
    bounds = QRect(0, 0, widget.width(), widget.height()).adjusted(0, 0, -1, -1)
    path = QPainterPath()
    path.addRoundedRect(QRectF(bounds), r, r)
    widget.setMask(QRegion(path.toFillPolygon().toPolygon()))


class _RoundMaskFilter(QObject):
    def __init__(self, radius: float, parent: QWidget) -> None:
        super().__init__(parent)
        self._radius = radius

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if event.type() in (QEvent.Type.Show, QEvent.Type.Resize):
            apply_round_window_mask(watched, self._radius)
        return False


def seal_tool_window(
    widget: QWidget,
    *,
    round_corners: bool = False,
    radius: float | None = None,
) -> None:
    """Top-level glass must be an opaque HWND.

    Settings, inboxes, calendar, and the main window. A translucent HWND on
    Windows is a layered window: the OS keeps the last bitmap across hide and
    resize (offset orbit, see-through contacts). Rounded tiles use a mask so
    the four corner wedges are not a black rectangle.
    """
    widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
    widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
    widget.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
    widget.setAutoFillBackground(True)
    pal = widget.palette()
    pal.setColor(widget.backgroundRole(), QColor(*PLATE["seal"]))
    widget.setPalette(pal)
    if round_corners:
        r = float(GLASS.get("radius", 12.0) if radius is None else radius)
        filt = _RoundMaskFilter(r, widget)
        widget.installEventFilter(filt)
        apply_round_window_mask(widget, r)


def fade_in_widget(widget: QWidget, duration_ms: int = 280) -> QPropertyAnimation:
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    effect.setOpacity(0.0)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration_ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _drop() -> None:
        # The effect caches a pixmap. Left on a translucent plate it keeps
        # the previous frame after a resize — duplicate corner ticks, leftover
        # dock strips. Take it off the moment the fade is done.
        if widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)

    anim.finished.connect(_drop)
    anim.start()
    widget._arelis_fade_anim = anim
    return anim
