"""Orbit idle face, empty session, not a dashboard.

The real composer lives in conversation.py. This widget is the void around it:
orbit ring + tick + core, ghost recent sessions, and a live readiness readout.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from arelis.core.compact_prompt import TOOLS_SLASH
from arelis.ui.glass import Hairline
from arelis.ui.stage import BLOOM_X, BLOOM_Y
from arelis.ui.theme import SPACE, active_theme, color

_GHOST_WIDTH = 220

_CLEAR = QColor(0, 0, 0, 0)


def _lit(base: QColor, alpha: float) -> QColor:
    return QColor(base.red(), base.green(), base.blue(), max(0, min(255, int(alpha))))

# Sodium idle: "what are we working on" is the typeable ask; wake status only
# while something is latched. Filament idle: the field is not a composer —
# the line is say "hey arelis", one line. Text lives on the chat plate.
#
# Keep these no wider than the prompt host. This label sits in the centre
# column, so its width becomes the column's width, and a longer line pushed the
# column out far enough that _layout_idle had no room left for the session
# ghosts and hid them.
_LISTEN_IDLE = 'say "hey arelis"'
_LISTEN_TALKING = "talking · say goodbye"
_LISTEN_DICTATING = "dictating · ctrl+m to stop"
_LISTEN_ACK = "listening"
_LISTEN_PREPARING = "getting the ear…"

# Shown in the ghost column only while there is no history to put there, and
# gone for good after the first conversation. The face is deliberately bare —
# an orbit and "what are we working on" — which is right for the owner and tells
# a first-time user nothing about what this can reach. These are the answer:
# real asks, each routing through a different part of the tool surface, filled
# into the composer rather than sent, so nothing happens without a keypress.
FIRST_RUN_ASKS: tuple[str, ...] = (
    "what's the weather going to be like tomorrow?",
    "what's on my calendar today?",
    "remember that I climb on Tuesdays",
)

# Persistent ghost: opens the capability list the same way /tools does.
# Fills the composer — Enter still belongs to the user, same as TRY.
TOOLS_CHIP_TITLE = "what she can do"


# Arelis's aether palette, from persona_face/web/config.js (LOOK plus the ellah
# override) as it reads after bloom: blue-violet threads, lilac glow, and
# white-lilac where the light is brightest. aether_colors() tints it to the
# room's accent.
AETHER = {
    "violet": (98, 52, 230),
    "lilac": (150, 112, 255),
    "spark": (232, 222, 255),
    "interior": (15, 5, 41),
}


# A room whose accent is already this close to her violet keeps her colours.
_AETHER_HUE_KEEP = 30


def aether_hue_shift() -> int:
    """Degrees to turn her violet to the active room's accent; 0 keeps her own.

    Filament and a cool room (accent near her violet, as in night) keep her
    exact colours; a warm room (sodium's lamp) turns her amber. One number
    so the painted orbit and the web scene's tint pass always agree.
    """
    if active_theme() == "filament":
        return 0
    accent_hue = color("accent").hsvHue()
    home = QColor(*AETHER["violet"]).hsvHue()
    gap = abs(accent_hue - home) % 360
    if accent_hue < 0 or min(gap, 360 - gap) <= _AETHER_HUE_KEEP:
        return 0
    return accent_hue - home


def aether_colors() -> dict[str, QColor]:
    """Her palette turned by aether_hue_shift, same saturation and value."""
    base = {name: QColor(*rgb) for name, rgb in AETHER.items()}
    shift = aether_hue_shift()
    if not shift:
        return base
    return {
        name: QColor.fromHsv((c.hsvHue() + shift) % 360, c.hsvSaturation(), c.value())
        for name, c in base.items()
    }


def _star_field(count: int) -> tuple[tuple[float, float, float, float], ...]:
    """Fixed stars as (x, y, size, phase) in a unit box. Seeded, so frames agree."""
    stars = []
    seed = 1013904223
    for _ in range(count):
        vals = []
        for _ in range(4):
            seed = (seed * 1664525 + 1013904223) % 4294967296
            vals.append(seed / 4294967296.0)
        stars.append((vals[0], vals[1], vals[2], vals[3]))
    return tuple(stars)


_STARS = _star_field(80)


def paint_aether_orbit(
    painter: QPainter,
    cx: float,
    cy: float,
    *,
    box: float = 220.0,
    dim: float = 1.0,
    angle: float = 0.0,
    beat: float = 0.0,
) -> None:
    """The idle orbit in Arelis's aether: a tall woven frame, a floor of rings
    and loose stars, sized to hold her standing figure."""
    tint = aether_colors()
    violet = tint["violet"]
    lilac = tint["lilac"]
    spark = tint["spark"]
    s = box / 220.0
    d = max(0.2, min(1.0, float(dim)))
    t = 0.5 - 0.5 * math.cos(beat * 6.283185307179586)
    rx, ry = 58.0 * s, 84.0 * s
    oy = cy - 4.0 * s
    phase = math.radians(angle)

    painter.setPen(Qt.PenStyle.NoPen)
    room = QRadialGradient(QPointF(cx, oy), ry + 24.0 * s)
    room.setColorAt(0.0, _lit(tint["interior"], 190 * d))
    room.setColorAt(0.62, _lit(tint["interior"], 150 * d))
    room.setColorAt(0.8, _lit(violet, 40 * d))
    room.setColorAt(1.0, _CLEAR)
    painter.setBrush(room)
    painter.drawEllipse(QPointF(cx, oy), ry + 24.0 * s, ry + 24.0 * s)
    inner = QRadialGradient(QPointF(cx, oy - 12.0 * s), ry * 0.8)
    inner.setColorAt(0.0, _lit(lilac, (46 + 14 * t) * d))
    inner.setColorAt(1.0, _CLEAR)
    painter.setBrush(inner)
    painter.drawEllipse(QPointF(cx, oy - 12.0 * s), rx * 0.9, ry * 0.8)

    # Floor: the thread hem she stands on, in perspective.
    painter.setBrush(Qt.BrushStyle.NoBrush)
    floor_y = oy + ry - 6.0 * s
    # Three rings ripple outward and fade, one slow cycle per orbit turn.
    for i in range(3):
        u = (i / 3.0 + angle / 360.0) % 1.0
        frac = 0.4 + 0.6 * u
        alpha = 70.0 * math.sin(math.pi * u)
        pen = QPen(_lit(violet if u > 0.66 else lilac, alpha * d))
        pen.setWidthF(max(0.8, 1.0 * s))
        painter.setPen(pen)
        painter.drawEllipse(QPointF(cx, floor_y), rx * 1.25 * frac, 9.0 * s * frac)

    # Ribbons that fall from the frame to the floor, like her hem.
    for k in range(6):
        side = -1.0 if k % 2 else 1.0
        lift = 0.15 + 0.12 * (k // 2)
        start = QPointF(cx + side * rx * 0.98, oy - ry * lift)
        sway = 5.0 * s * math.sin(phase * 0.7 + k)
        rib = QPainterPath(start)
        rib.cubicTo(
            QPointF(cx + side * (rx + 26.0 * s) + sway, oy + ry * 0.2),
            QPointF(cx + side * (rx + 10.0 * s) - sway, oy + ry * 0.7),
            QPointF(cx + side * rx * (1.05 + 0.12 * (k // 2)), floor_y + 2.0 * s),
        )
        pen = QPen(_lit(lilac, (34 + 14 * (k // 2)) * d))
        pen.setWidthF(max(0.6, 0.8 * s))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(rib)

    # The frame: fine threads woven around a tall oval, each with its own wobble.
    for k in range(6):
        pen = QPen(_lit(lilac if k % 2 else violet, (70 + 20 * k) * d))
        pen.setWidthF(max(0.6, (0.7 + 0.25 * (k == 2)) * s))
        painter.setPen(pen)
        path = []
        for j in range(97):
            a = j / 96.0 * 6.283185307179586
            wob = 3.6 * s * math.sin((3 + k % 2) * a + phase * (1 + k * 0.3) + k * 1.7)
            path.append(QPointF(cx + (rx + wob) * math.sin(a), oy - (ry + wob) * math.cos(a)))
        painter.drawPolyline(path)

    # Loose stars around her, twinkling on the beat.
    painter.setPen(Qt.PenStyle.NoPen)
    half = box / 2.0
    for ux, uy, size, ph in _STARS:
        x = cx + (ux * 2.0 - 1.0) * half * 0.96
        y = cy + (uy * 2.0 - 1.0) * half * 0.96
        tw = 0.5 + 0.5 * math.sin((beat + ph) * 6.283185307179586)
        painter.setBrush(_lit(spark if size > 0.86 else lilac, (60 + 150 * tw * size) * d))
        r = (0.5 + 1.1 * (size > 0.86)) * s
        painter.drawEllipse(QPointF(x, y), r, r)

    # One bright spark travels the frame with a short tail.
    for i in range(7):
        a = phase - math.radians(i * 4.0)
        px = cx + rx * math.sin(a)
        py = oy - ry * math.cos(a)
        glow = QRadialGradient(QPointF(px, py), (8.0 - i) * s)
        glow.setColorAt(0.0, _lit(spark if i == 0 else lilac, (200 - 26 * i) * d))
        glow.setColorAt(1.0, _CLEAR)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(px, py), (8.0 - i) * s, (8.0 - i) * s)

    # Heart light, where her body glow is brightest.
    glow_r = (18.0 + 8.0 * t) * s
    heart = QPointF(cx, oy - 12.0 * s)
    core = QRadialGradient(heart, glow_r)
    core.setColorAt(0.0, _lit(spark, (150 + 60 * t) * d))
    core.setColorAt(0.4, _lit(lilac, (70 + 30 * t) * d))
    core.setColorAt(1.0, _CLEAR)
    painter.setBrush(core)
    painter.drawEllipse(heart, glow_r, glow_r)
    painter.setBrush(_lit(spark, 255 * d))
    painter.drawEllipse(heart, (2.0 + t) * s, (2.0 + t) * s)


class OrbitCanvas(QWidget):
    """QPainter orbit in Arelis's aether, tinted to the room: frame, floor, stars, spark."""

    def __init__(self, parent=None, *, size: int = 220, dim: float = 1.0) -> None:
        super().__init__(parent)
        self._box = max(48, int(size))
        self._dim = max(0.2, min(1.0, float(dim)))
        self.setFixedSize(self._box, self._box)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._angle = 0.0
        self._beat = 0.0
        self._thinking = False
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def set_thinking(self, on: bool) -> None:
        """Brighter, slower breath while a turn is in flight, never hide/show."""
        want = bool(on)
        if want == self._thinking:
            return
        self._thinking = want
        self._dim = 0.92 if want else 0.42
        from arelis.ui import idle_ab

        if want and self.isVisible() and not self._timer.isActive() and idle_ab.idle_timers():
            self._timer.start()
        elif not want and not self.isVisible():
            self._timer.stop()
        self.update()

    def set_animating(self, on: bool) -> None:
        from arelis.ui import idle_ab

        if on and not idle_ab.idle_timers():
            self.update()
            return
        if on:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self.update()

    def _tick(self) -> None:
        step = 0.03 if self._thinking else 0.04
        period = 4.8 if self._thinking else 3.2
        self._angle = (self._angle + 360.0 * step / 14.0) % 360.0
        self._beat = (self._beat + step / period) % 1.0
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        if active_theme() == "filament":
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        paint_aether_orbit(
            painter,
            self.width() / 2.0,
            self.height() / 2.0,
            box=float(self._box),
            dim=self._dim,
            angle=self._angle,
            beat=self._beat,
        )


class _GhostRow(QWidget):
    """Clickable recent-session chip. Not a QPushButton: the app button style
    sizes from empty text and clips the title mid-glyph.

    ``key`` is the small caps word above the title. On a machine with no history
    there are no recents to show and the column sits empty, so the same chip
    carries the opening suggestions under TRY, same shape, same weight, nothing
    new to learn.
    """

    clicked = Signal()

    def __init__(
        self, session_id: str, title: str, parent=None, *, key_text: str = "RECENT"
    ) -> None:
        super().__init__(parent)
        self.session_id = session_id
        self._pressed = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(_GHOST_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        key = QLabel(key_text)
        key.setObjectName("VoidGhostKey")
        key.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        val = QLabel(title)
        val.setObjectName("VoidGhostValue")
        val.setWordWrap(True)
        val.setFixedWidth(_GHOST_WIDTH)
        val.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        val.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(key)
        lay.addWidget(val)
        self._title = val
        self.ensurePolished()
        val.ensurePolished()
        wrap_h = max(val.heightForWidth(_GHOST_WIDTH), val.fontMetrics().height())
        val.setMinimumHeight(wrap_h)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        key = self.layout().itemAt(0).widget() if self.layout() is not None else None
        key_h = key.sizeHint().height() if key is not None else 12
        title_h = self._title.heightForWidth(max(1, int(width)))
        line = self._title.fontMetrics().height()
        return key_h + 4 + max(int(title_h), line)

    def sizeHint(self) -> QSize:
        return QSize(_GHOST_WIDTH, self.heightForWidth(_GHOST_WIDTH))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            inside = self.rect().contains(event.position().toPoint())
            if self._pressed and inside:
                self.clicked.emit()
            self._pressed = False
            event.accept()
            return
        super().mouseReleaseEvent(event)


class OrbitIdle(QWidget):
    """Empty-session surface. Composer stays in ConversationStage.

    Orbit + prompt are laid on the window bloom, not the leftover chat column.
    Ghosts and readout overlay the sides; they do not reflow the face. Docks
    may cover the edges. The face only leaves this lock when a thread starts.
    """

    session_clicked = Signal(str)
    # An opening suggestion was clicked. Carries the text to put in the composer;
    # it is never sent on the user's behalf.
    suggestion_clicked = Signal(str)
    new_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ChatEmpty")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._want_ghosts = True
        self._want_readout = True

        self._ghosts = QWidget(self)
        self._ghosts.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._ghosts.setFixedWidth(_GHOST_WIDTH)
        self._ghosts.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)
        self._ghost_layout = QVBoxLayout(self._ghosts)
        self._ghost_layout.setContentsMargins(0, 0, 0, 0)
        self._ghost_layout.setSpacing(SPACE["stage"])

        self._center = QWidget(self)
        self._center.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._center.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        col = QVBoxLayout(self._center)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.orbit = OrbitCanvas(self._center)
        col.addWidget(self.orbit, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.listen_word = QLabel(_LISTEN_IDLE)
        self.listen_word.setObjectName("VoidListenWord")
        self.listen_word.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Wrap rather than widen: the centre column's width decides how much
        # room is left for the ghosts and the readout on either side.
        self.listen_word.setWordWrap(True)
        self.listen_word.setMaximumWidth(300)
        col.addSpacing(SPACE["stage"])
        col.addWidget(self.listen_word)
        self.prompt_host = QWidget()
        self.prompt_host.setObjectName("VoidPromptHost")
        self.prompt_host.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.prompt_host.setFixedSize(280, 44)
        prompt_l = QVBoxLayout(self.prompt_host)
        prompt_l.setContentsMargins(0, 4, 0, 0)
        prompt_l.setSpacing(0)
        # QPlainTextEdit's placeholder is left-aligned; this label is the idle
        # prompt so "what are we working on" sits on the same axis as the orbit.
        self.idle_placeholder = QLabel("what are we working on", self.prompt_host)
        self.idle_placeholder.setObjectName("VoidIdlePlaceholder")
        self.idle_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.idle_placeholder.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        col.addSpacing(8)
        col.addWidget(self.prompt_host, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.idle_hairline = Hairline(width=280)
        col.addSpacing(SPACE["plate"])
        col.addWidget(self.idle_hairline, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.voice_host = QWidget()
        self.voice_host.setObjectName("VoidVoiceHost")
        self.voice_host.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        voice_l = QHBoxLayout(self.voice_host)
        voice_l.setContentsMargins(0, SPACE["gap"], 0, 0)
        voice_l.setSpacing(8)
        voice_l.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.voice_host.hide()
        col.addWidget(self.voice_host, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._prompt_typing = False
        self._voice_preparing = False
        self.listen_word.hide()

        self._readout = QWidget(self)
        self._readout.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._readout.setFixedWidth(160)
        self._readout.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)
        read_l = QVBoxLayout(self._readout)
        read_l.setContentsMargins(0, 0, 0, 0)
        read_l.setSpacing(16)
        read_l.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._model_row = self._make_readout("server", "-")
        self._listen_row = self._make_readout("listening", "off")
        read_l.addWidget(self._model_row, alignment=Qt.AlignmentFlag.AlignRight)
        read_l.addWidget(self._listen_row, alignment=Qt.AlignmentFlag.AlignRight)

        self.hint = QLabel("talk or type whenever you're ready", self)
        self.hint.setObjectName("VoidListenWord")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.phone_note = QLabel("", self)
        self.phone_note.setObjectName("VoidPhoneNote")
        self.phone_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.phone_note.setWordWrap(True)
        self.phone_note.hide()
        self.apply_theme_face()

    def apply_theme_face(self) -> None:
        """Sodium keeps the lamp. Filament hides it, the window paints the field."""
        filament = active_theme() == "filament"
        orbit = getattr(self, "orbit", None)
        if orbit is not None:
            orbit.setVisible(not filament)
            if filament:
                orbit.set_animating(False)
        hair = getattr(self, "idle_hairline", None)
        if hair is not None:
            hair.setVisible(not filament)
        host = getattr(self, "prompt_host", None)
        if host is not None:
            host.setVisible(not filament)
        label = getattr(self, "idle_placeholder", None)
        if label is not None:
            label.setVisible(not filament)
        listen = getattr(self, "listen_word", None)
        if listen is not None:
            listen.setProperty("wake", "true" if filament else "false")
            listen.setWordWrap(not filament)
            listen.setMaximumWidth(480 if filament else 300)
            style = listen.style()
            if style is not None:
                style.unpolish(listen)
                style.polish(listen)
        self._sync_listen_visibility()
        hint = getattr(self, "hint", None)
        if hint is not None:
            hint.setVisible(not filament)
        self._layout_idle()

    def refresh_theme_icons(self) -> None:
        self.apply_theme_face()

    def set_side_chrome(self, *, ghosts: bool, readout: bool) -> None:
        """Hide idle ghosts/readout when a dock already shows the same facts."""
        self._want_ghosts = bool(ghosts)
        self._want_readout = bool(readout)
        self._layout_idle()

    def _make_readout(self, key: str, value: str) -> QWidget:
        row = QWidget()
        row.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignmentFlag.AlignRight)
        k = QLabel(key)
        k.setObjectName("VoidReadoutKey")
        v = QLabel(value)
        v.setObjectName("VoidReadoutValue")
        v.setProperty("role", "value")
        lay.addWidget(k)
        lay.addWidget(v)
        row._value = v  # type: ignore[attr-defined]
        return row

    def set_sessions(self, sessions: list[tuple[str, str]]) -> None:
        """Left ghosts: (session_id, title), most recent first.

        With no sessions the column stood empty, which is exactly the moment a
        first-time user has nothing to go on. The opening asks take that space
        and give it back as soon as there is a real recent to show.
        """
        while self._ghost_layout.count():
            item = self._ghost_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if not sessions:
            from arelis.i18n import tr

            for ask in FIRST_RUN_ASKS:
                shown = tr(ask)
                row = _GhostRow(ask, shown, self._ghosts, key_text="TRY")
                row.clicked.connect(
                    lambda text=shown: self.suggestion_clicked.emit(text)
                )
                self._ghost_layout.addWidget(row)
                row.adjustSize()
            self._add_tools_chip()
            self._layout_idle()
            return
        from arelis.i18n import tr

        fresh = _GhostRow("new", tr("new chat"), self._ghosts, key_text="NEW")
        fresh.clicked.connect(self.new_requested.emit)
        self._ghost_layout.addWidget(fresh)
        fresh.adjustSize()
        for sid, title in sessions[:3]:
            row = _GhostRow(sid, title or tr("new chat"), self._ghosts)
            row.clicked.connect(lambda s=sid: self.session_clicked.emit(s))
            self._ghost_layout.addWidget(row)
            row.adjustSize()
        self._add_tools_chip()
        self._layout_idle()

    def _add_tools_chip(self) -> None:
        """TOOLS ghost, same shape as TRY / RECENT. Fills `/tools`."""
        from arelis.i18n import tr

        row = _GhostRow(
            TOOLS_SLASH, tr(TOOLS_CHIP_TITLE), self._ghosts, key_text="TOOLS"
        )
        row.clicked.connect(lambda: self.suggestion_clicked.emit(TOOLS_SLASH))
        self._ghost_layout.addWidget(row)
        row.adjustSize()

    def set_voice_preparing(self, on: bool) -> None:
        """Hold the idle line on getting the ear until wake can actually hear."""
        self._voice_preparing = bool(on)
        if on:
            self.set_voice_mode("preparing")
        else:
            self.set_voice_mode("off")

    def set_voice_mode(self, mode: str) -> None:
        """Say the latched voice mode in the copy, not just in the button.

        ``mode`` is the controller's mode: conversation, dictate, wake, or off.
        Wake and off are both "nothing is latched" as far as the operator is
        concerned, idle is always listening for Hey Arelis. Preparing wins
        until the ear is loaded, so a first-run "say hey arelis" is not a lie.
        """
        if self._voice_preparing and mode != "preparing":
            mode = "preparing"
        from arelis.i18n import tr

        if mode == "conversation":
            text, live = tr(_LISTEN_TALKING), True
        elif mode == "dictate":
            text, live = tr(_LISTEN_DICTATING), True
        elif mode == "ack":
            text, live = tr(_LISTEN_ACK), True
        elif mode == "preparing":
            text, live = tr(_LISTEN_PREPARING), True
        else:
            text, live = tr(_LISTEN_IDLE), False
        changed = self.listen_word.text() != text
        if changed:
            self.listen_word.setText(text)
            self.listen_word.setProperty("live", "true" if live else "false")
            style = self.listen_word.style()
            if style is not None:
                style.unpolish(self.listen_word)
                style.polish(self.listen_word)
            self.listen_word.adjustSize()
        self._sync_listen_visibility()
        if changed:
            self._layout_idle()

    def _sync_listen_visibility(self) -> None:
        """Sodium: status only while voice is on. Filament: the wake is the face."""
        listen = getattr(self, "listen_word", None)
        if listen is None:
            return
        typing = getattr(self, "_prompt_typing", False)
        if active_theme() == "filament":
            listen.setVisible(not typing)
            return
        live = listen.property("live") == "true"
        listen.setVisible(live and not typing)

    def voice_mode_text(self) -> str:
        return self.listen_word.text()

    def set_readout(self, *, server: str, listening: str) -> None:
        self._model_row._value.setText((server or "-").lower())  # type: ignore[attr-defined]
        self._listen_row._value.setText((listening or "off").lower())  # type: ignore[attr-defined]

    def fit_prompt(self, width: int, height: int, *, typing: bool) -> None:
        """Idle composer grows with the sentence; hint yields once typing."""
        self._prompt_typing = bool(typing)
        self.prompt_host.setFixedSize(max(120, int(width)), max(36, int(height) + 8))
        self.idle_hairline.setFixedWidth(max(120, int(width)))
        self._sync_listen_visibility()
        self.idle_placeholder.setVisible(not typing)
        self.idle_placeholder.setGeometry(self.prompt_host.rect())
        self.idle_placeholder.lower()
        self._layout_idle()

    def set_animating(self, on: bool) -> None:
        orbit = getattr(self, "orbit", None)
        if orbit is not None:
            orbit.set_animating(on)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._layout_idle()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        orbit = getattr(self, "orbit", None)
        if orbit is not None:
            orbit.set_animating(True)
        self._layout_idle()

    def hideEvent(self, event) -> None:  # type: ignore[override]
        orbit = getattr(self, "orbit", None)
        if orbit is not None:
            orbit.set_animating(False)
        super().hideEvent(event)

    def _bloom_in_self(self) -> QPoint:
        """Window bloom, mapped into this widget (the leftover chat column)."""
        w, h = self.width(), self.height()
        win = self.window()
        if win is None or win is self or w <= 0 or h <= 0:
            return QPoint(max(0, w // 2), max(0, int(h * BLOOM_Y)))
        return self.mapFrom(
            win,
            QPoint(int(win.width() * BLOOM_X), int(win.height() * BLOOM_Y)),
        )

    def set_phone_note(self, text: str) -> None:
        """Welcome-screen note on the orb's axis, under the hint."""
        note = getattr(self, "phone_note", None)
        if note is None:
            return
        note.setText(text or "")
        note.setVisible(bool((text or "").strip()))
        self._layout_idle()

    def _layout_idle(self) -> None:
        """Pin orbit core to the bloom; side chrome overlays and never shoves."""
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        margin = 16
        self.hint.adjustSize()
        hint_h = (
            0
            if active_theme() == "filament" or not self.hint.isVisible()
            else self.hint.height() + 20
        )
        center_layout = self._center.layout()
        if center_layout is not None:
            center_layout.activate()
        self._center.adjustSize()
        cw, ch = self._center.width(), self._center.height()
        if cw <= 0 or ch <= 0:
            return
        bloom = self._bloom_in_self()
        orbit_h = self.orbit.height()
        pinned_home = False
        if active_theme() == "filament":
            win = self.window()
            field = getattr(win, "_filament", None) if win is not None else None
            if field is not None and win is not None:
                p = field.prompt_point(win.rect())
                local = self.mapFrom(win, p.toPoint())
                cx = local.x() - cw // 2
                cy = local.y()
                home = field.home_rect(win.rect())
                band = QRect(self.mapFrom(win, home.topLeft()), home.size())
                if band.width() > cw + margin * 2:
                    cx = max(band.left() + margin, min(cx, band.right() - cw - margin))
                    cy = max(band.top() + margin, min(cy, band.bottom() - ch - margin))
                    pinned_home = True
            else:
                cx = bloom.x() - cw // 2
                cy = bloom.y() + 80
        else:
            cx = bloom.x() - cw // 2
            cy = bloom.y() - orbit_h // 2
        # Sodium: stay inside the leftover column. Filament already pinned to
        # the primary band — clamping to this widget yanks the ask onto the
        # left desk when the idle face has not grown with a 3-span yet.
        if not pinned_home:
            cx = max(margin, min(cx, w - cw - margin))
            cy = max(margin, min(cy, h - hint_h - ch - margin))
        self._center.move(cx, cy)
        self._center.raise_()

        hint_x = bloom.x() - self.hint.width() // 2
        hint_x = max(margin, min(hint_x, w - self.hint.width() - margin))
        # Room under the hint is always reserved, so the hint does not jump
        # when the phone line appears.
        band = 56
        self.hint.move(hint_x, h - self.hint.height() - 8 - band)
        self.hint.raise_()
        note = getattr(self, "phone_note", None)
        if note is not None and not note.isHidden():
            note.setFixedWidth(min(420, max(80, w - 2 * margin)))
            note.adjustSize()
            nx = bloom.x() - note.width() // 2
            nx = max(margin, min(nx, w - note.width() - margin))
            note.move(nx, self.hint.y() + self.hint.height() + 6)
            note.raise_()

        ghost_layout = self._ghosts.layout()
        if ghost_layout is not None:
            ghost_layout.activate()
        self._ghosts.adjustSize()
        gx = self._window_inset_x(from_left=True, width=self._ghosts.width())
        room_left = (
            self._want_ghosts
            and active_theme() != "filament"
            and gx + self._ghosts.width() + 12 <= cx
        )
        self._ghosts.setVisible(room_left)
        if self._ghosts.isVisible():
            gy = max(margin, min(cy, h - hint_h - self._ghosts.height() - margin))
            self._ghosts.move(gx, gy)
            self._ghosts.raise_()

        self._readout.adjustSize()
        rx = self._window_inset_x(from_left=False, width=self._readout.width())
        room_right = (
            self._want_readout
            and active_theme() != "filament"
            and (cx + cw) + 12 <= rx
        )
        self._readout.setVisible(room_right)
        if self._readout.isVisible():
            ry = max(margin, min(cy, h - hint_h - self._readout.height() - margin))
            self._readout.move(rx, ry)
            self._readout.raise_()

        if self.idle_placeholder.isVisible():
            self.idle_placeholder.setGeometry(self.prompt_host.rect())
            self.idle_placeholder.lower()

    def _window_inset_x(self, *, from_left: bool, width: int) -> int:
        """Place side chrome from the window edge so it is not clipped."""
        inset = 56
        win = self.window()
        if win is None or win is self:
            x = inset if from_left else max(inset, self.width() - width - inset)
        elif from_left:
            x = self.mapFrom(win, QPoint(inset, 0)).x()
        else:
            x = self.mapFrom(win, QPoint(max(inset, win.width() - width - inset), 0)).x()
        lo = 16
        hi = max(lo, self.width() - width - 16)
        return max(lo, min(x, hi))
