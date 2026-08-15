"""Orbit idle face — empty session, not a dashboard.

The real composer lives in conversation.py. This widget is the void around it:
orbit ring + tick + core, ghost recent sessions, and a live readiness readout.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPaintEvent, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from arelis.ui.stage import BLOOM_X, BLOOM_Y

_GHOST_WIDTH = 220

# The line under the orbit is the only place the idle face can say which voice
# mode is latched. The two-arc button is 34px of parked chrome and reads as
# decoration, so a chord that worked looked like a chord that did nothing.
#
# Keep these no wider than the prompt host. This label sits in the centre
# column, so its width becomes the column's width, and a longer line pushed the
# column out far enough that _layout_idle had no room left for the session
# ghosts and hid them.
_LISTEN_IDLE = "ctrl+shift+m to talk"
_LISTEN_TALKING = "talking · ctrl+shift+m to stop"
_LISTEN_DICTATING = "dictating · ctrl+m to stop"

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


class OrbitCanvas(QWidget):
    """QPainter orbit: ring, one tick, beating core. Soft bloom, not CAD lines."""

    def __init__(self, parent=None, *, size: int = 220, dim: float = 1.0) -> None:
        super().__init__(parent)
        self._box = max(48, int(size))
        self._dim = max(0.2, min(1.0, float(dim)))
        self.setFixedSize(self._box, self._box)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._angle = 0.0
        self._beat = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def set_animating(self, on: bool) -> None:
        if on:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self.update()

    def _tick(self) -> None:
        self._angle = (self._angle + 360.0 * 0.04 / 14.0) % 360.0
        self._beat = (self._beat + 0.04 / 3.2) % 1.0
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        s = self._box / 220.0
        d = self._dim
        r = 68.0 * s

        halo = QRadialGradient(QPointF(cx, cy), r + 18.0 * s)
        halo.setColorAt(0.72, QColor(255, 180, 87, 0))
        halo.setColorAt(0.88, QColor(255, 180, 87, int(28 * d)))
        halo.setColorAt(1.0, QColor(255, 180, 87, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(QPointF(cx, cy), r + 18.0 * s, r + 18.0 * s)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        for width, alpha in ((3.2, 18), (1.4, 40)):
            ring = QPen(QColor(255, 180, 87, int(alpha * d)))
            ring.setWidthF(max(1.0, width * s))
            painter.setPen(ring)
            painter.drawEllipse(QPointF(cx, cy), r, r)

        rad = math.radians(self._angle)
        tx = cx + r * math.sin(rad)
        ty = cy - r * math.cos(rad)
        tick_r = 16.0 * s
        tick_glow = QRadialGradient(QPointF(tx, ty), tick_r)
        tick_glow.setColorAt(0.0, QColor(255, 200, 120, int(190 * d)))
        tick_glow.setColorAt(0.45, QColor(255, 180, 87, int(70 * d)))
        tick_glow.setColorAt(1.0, QColor(255, 180, 87, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(tick_glow)
        painter.drawEllipse(QPointF(tx, ty), tick_r, tick_r)
        painter.setBrush(QColor(255, 210, 150, int(255 * d)))
        painter.drawEllipse(QPointF(tx, ty), 2.4 * s, 2.4 * s)

        t = 0.5 - 0.5 * math.cos(self._beat * 6.283185307179586)
        glow_r = (22.0 + 10.0 * t) * s
        core_glow = QRadialGradient(QPointF(cx, cy), glow_r)
        core_glow.setColorAt(0.0, QColor(255, 220, 170, int((160 + 50 * t) * d)))
        core_glow.setColorAt(0.35, QColor(255, 180, 87, int((70 + 30 * t) * d)))
        core_glow.setColorAt(1.0, QColor(255, 180, 87, 0))
        painter.setBrush(core_glow)
        painter.drawEllipse(QPointF(cx, cy), glow_r, glow_r)
        core_r = (2.4 + 1.2 * t) * s
        painter.setBrush(QColor(255, 230, 190, int(255 * d)))
        painter.drawEllipse(QPointF(cx, cy), core_r, core_r)


class _GhostRow(QWidget):
    """Clickable recent-session chip. Not a QPushButton: the app button style
    sizes from empty text and clips the title mid-glyph.

    ``key`` is the small caps word above the title. On a machine with no history
    there are no recents to show and the column sits empty, so the same chip
    carries the opening suggestions under TRY — same shape, same weight, nothing
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
        self._ghost_layout.setSpacing(20)

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
        font = self.listen_word.font()
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.4)
        self.listen_word.setFont(font)
        col.addSpacing(28)
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
        self.idle_hairline = QWidget()
        self.idle_hairline.setFixedSize(280, 1)
        self.idle_hairline.setStyleSheet("background: rgba(255, 180, 87, 26);")
        col.addSpacing(18)
        col.addWidget(self.idle_hairline, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.voice_host = QWidget()
        self.voice_host.setObjectName("VoidVoiceHost")
        self.voice_host.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        voice_l = QHBoxLayout(self.voice_host)
        voice_l.setContentsMargins(0, 10, 0, 0)
        voice_l.setSpacing(8)
        voice_l.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.voice_host.hide()
        col.addWidget(self.voice_host, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._readout = QWidget(self)
        self._readout.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._readout.setFixedWidth(160)
        self._readout.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)
        read_l = QVBoxLayout(self._readout)
        read_l.setContentsMargins(0, 0, 0, 0)
        read_l.setSpacing(16)
        read_l.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._ollama_row = self._make_readout("OLLAMA", "—")
        self._listen_row = self._make_readout("LISTENING", "OFF")
        read_l.addWidget(self._ollama_row, alignment=Qt.AlignmentFlag.AlignRight)
        read_l.addWidget(self._listen_row, alignment=Qt.AlignmentFlag.AlignRight)

        self.hint = QLabel("enter to speak  ·  esc to clear", self)
        self.hint.setObjectName("VoidListenWord")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

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
            for ask in FIRST_RUN_ASKS:
                row = _GhostRow(ask, ask, self._ghosts, key_text="TRY")
                row.clicked.connect(
                    lambda text=ask: self.suggestion_clicked.emit(text)
                )
                self._ghost_layout.addWidget(row)
                row.adjustSize()
            self._layout_idle()
            return
        for sid, title in sessions[:3]:
            row = _GhostRow(sid, title or "(untitled)", self._ghosts)
            row.clicked.connect(lambda s=sid: self.session_clicked.emit(s))
            self._ghost_layout.addWidget(row)
            row.adjustSize()
        self._layout_idle()

    def set_voice_mode(self, mode: str) -> None:
        """Say the latched voice mode in the copy, not just in the button.

        ``mode`` is the controller's mode: conversation, dictate, wake, or off.
        Wake and off are both "nothing is latched" as far as the operator is
        concerned — idle is always listening for the name.
        """
        if mode == "conversation":
            text, live = _LISTEN_TALKING, True
        elif mode == "dictate":
            text, live = _LISTEN_DICTATING, True
        else:
            text, live = _LISTEN_IDLE, False
        if self.listen_word.text() == text:
            return
        self.listen_word.setText(text)
        self.listen_word.setProperty("live", "true" if live else "false")
        style = self.listen_word.style()
        if style is not None:
            style.unpolish(self.listen_word)
            style.polish(self.listen_word)
        self.listen_word.adjustSize()
        self._layout_idle()

    def voice_mode_text(self) -> str:
        return self.listen_word.text()

    def set_readout(self, *, ollama: str, listening: str) -> None:
        self._ollama_row._value.setText((ollama or "—").upper())  # type: ignore[attr-defined]
        self._listen_row._value.setText((listening or "OFF").upper())  # type: ignore[attr-defined]

    def fit_prompt(self, width: int, height: int, *, typing: bool) -> None:
        """Idle composer grows with the sentence; hint yields once typing."""
        self.prompt_host.setFixedSize(max(120, int(width)), max(36, int(height) + 8))
        self.idle_hairline.setFixedWidth(max(120, int(width)))
        self.listen_word.setVisible(not typing)
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

    def _layout_idle(self) -> None:
        """Pin orbit core to the bloom; side chrome overlays and never shoves."""
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        margin = 16
        self.hint.adjustSize()
        hint_h = self.hint.height() + 20
        center_layout = self._center.layout()
        if center_layout is not None:
            center_layout.activate()
        self._center.adjustSize()
        cw, ch = self._center.width(), self._center.height()
        if cw <= 0 or ch <= 0:
            return
        bloom = self._bloom_in_self()
        orbit_h = self.orbit.height()
        cx = bloom.x() - cw // 2
        cy = bloom.y() - orbit_h // 2
        # Docks overlay the void. Do not re-center into the leftover column.
        if bloom.x() < 0 or bloom.x() > w:
            cx = max(margin, min(cx, w - cw - margin))
        if bloom.y() < 0 or bloom.y() > h:
            cy = max(margin, min(cy, h - hint_h - ch - margin))
        self._center.move(cx, cy)
        self._center.raise_()

        hint_x = bloom.x() - self.hint.width() // 2
        hint_x = max(margin, min(hint_x, w - self.hint.width() - margin))
        self.hint.move(hint_x, h - self.hint.height() - 20)
        self.hint.raise_()

        ghost_layout = self._ghosts.layout()
        if ghost_layout is not None:
            ghost_layout.activate()
        self._ghosts.adjustSize()
        gx = self._window_inset_x(from_left=True, width=self._ghosts.width())
        room_left = self._want_ghosts and gx + self._ghosts.width() + 12 <= cx
        self._ghosts.setVisible(room_left)
        if self._ghosts.isVisible():
            gy = max(margin, min(cy, h - hint_h - self._ghosts.height() - margin))
            self._ghosts.move(gx, gy)
            self._ghosts.raise_()

        self._readout.adjustSize()
        rx = self._window_inset_x(from_left=False, width=self._readout.width())
        room_right = self._want_readout and (cx + cw) + 12 <= rx
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
