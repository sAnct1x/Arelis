"""Her three.js figure plus the short line under her. The window places this."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from PySide6.QtCore import QEvent, QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QRadialGradient
from PySide6.QtWidgets import QApplication, QWidget

from arelis.ui.theme import app_font, color, load_fonts

_DONE_S = 2.0
_STATUS_S = 8.0
_TEXT_H = 92
_LEVEL_MS = 33
_BLUSH = QColor(245, 163, 199)
LOG = logging.getLogger("arelis.avatar")


def alog(event: str, **fields: object) -> None:
    """One structured avatar line: ``[avatar] event k=v ...``."""
    tail = "".join(f" {k}={v}" for k, v in fields.items())
    LOG.info("[avatar] %s%s", event, tail)


class LoadingVeil(QWidget):
    """What shows while her scene loads, or if it cannot: a still, theme-tinted glow.

    No face and no motion. It only paints a soft wash of the theme accent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("avatarLoading")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def tint(self) -> QColor:
        return QColor(color("accent"))

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self.rect()
        c = self.tint()
        grad = QRadialGradient(QPointF(r.center()), max(1.0, min(r.width(), r.height()) * 0.5))
        inner = QColor(c)
        inner.setAlpha(46)
        outer = QColor(c)
        outer.setAlpha(0)
        grad.setColorAt(0.0, inner)
        grad.setColorAt(1.0, outer)
        painter.fillRect(r, grad)
        painter.end()


class PersonaPanel(QWidget):
    """Her figure, a state word, and one quiet status line."""

    state_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("personaPanel")
        self.setFont(app_font(load_fonts()))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        # No floor of its own: her stage sizes her. The old dock floor (220x300)
        # overflowed a small hub, which clipped her off centre.
        self.setMinimumSize(1, 1)
        self._state = "rest"
        self._speaking = False
        self._busy = False
        self._listening = False
        self._lipsync = False
        self._pose = "rest"
        self._place_due = False
        self._done_at: float | None = None
        self._status = ""
        self._status_at = 0.0
        self._level: Callable[[], float | None] | None = None
        self._clock: Callable[[], float] | None = None
        self.loading = LoadingVeil(self)
        self._level_timer = QTimer(self)
        self._level_timer.setInterval(_LEVEL_MS)
        self._level_timer.timeout.connect(self._tick_level)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._invalidate_caption)
        self.web = None
        self.web_avatar_reason = self._start_web()
        self._place()

    def sizeHint(self) -> QSize:
        return QSize(370, 520)

    def set_clock(self, clock: Callable[[], float] | None) -> None:
        """Tests pass a clock so a status line does not take seconds to age."""
        self._clock = clock

    def scene_pending(self) -> bool:
        """Her scene is still on its way (not failed, not unavailable)."""
        return self.web is not None and self.is_loading()

    def is_loading(self) -> bool:
        """True while the neutral veil stands in for her (loading or no scene)."""
        return not self.loading.isHidden()

    def set_state(self, name: str) -> None:
        if name not in {"rest", "thinking", "speaking", "done"}:
            name = "rest"
        self._state = name
        if name == "speaking":
            self._speaking = True
        elif name in {"thinking", "done"}:
            self._speaking = False
            if name == "done":
                self._done_at = self._now()
                self._status_timer.start(int(_DONE_S * 1000) + 50)
        else:
            self._speaking = False
        self._push()
        self.state_changed.emit(self._state)
        self._invalidate_caption()

    def set_model_busy(self, busy: bool) -> None:
        self._busy = bool(busy)

    def set_speaking(self, speaking: bool) -> None:
        self._speaking = bool(speaking)
        self._push()
        self._invalidate_caption()

    def set_listening(self, on: bool) -> None:
        """Mic is open: she shows it in her pose."""
        self._listening = bool(on)
        self._push()

    def set_level_source(self, source: Callable[[], float | None] | None) -> None:
        self._level = source

    def show_status(self, text: str) -> None:
        self._status = " ".join(text.split())
        self._status_at = self._now()
        self._status_timer.start(int(_STATUS_S * 1000) + 50)
        self._invalidate_caption()

    def caption_text(self) -> str:
        if self._state == "done" and self._done_at is not None:
            if (self._now() - self._done_at) < _DONE_S:
                return "done"
        if self._is_speaking():
            return "speaking"
        return ""

    def status_text(self) -> str:
        if not self._status or self._now() - self._status_at >= _STATUS_S:
            return ""
        return self._status

    def elided_status(self, width: int | None = None) -> str:
        """Status keeps its first characters. The tail ellipsizes to the width."""
        text = self.status_text()
        if not text:
            return ""
        if width is None:
            width = self.width()
        font = self.font()
        font.setPixelSize(12)
        limit = max(8, int(width) - 16)
        return QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, limit)

    def refresh_theme_icons(self) -> None:
        """Theme change: retint the veil. The scene retints through its own hook."""
        self.loading.update()

    # ---- web scene ----

    def _start_web(self) -> str | None:
        """Start the three.js scene. Returns why not, or None when it is starting."""
        from arelis.ui.persona_face import web_avatar

        reason = web_avatar.unavailable_reason()
        if reason is None:
            try:
                self.web = web_avatar.WebAvatar(self)
            except Exception as exc:
                reason = f"web avatar failed to start: {exc}"
        if reason is not None:
            alog("unavailable", reason=repr(reason))
            return reason
        # The page loads shown and sized, under the veil. A hidden view is a
        # hidden page to Chromium: it started at 0x0 and its frames and fetches
        # were held back, so scene ready and the clips came about 9 s late and
        # the first frames resized from 100x30. Before ready the canvas is clear.
        self._place()
        self.web.show()
        self.loading.raise_()
        self.web.ready.connect(self._on_web_ready)
        self.web.failed.connect(self._on_web_failed)
        return None

    def _on_web_ready(self) -> None:
        if self.web is None:
            return
        self._place()
        self.web.show()
        self.web.raise_()
        self.loading.hide()
        self.web.refit()

    def _on_web_failed(self, reason: str) -> None:
        self.web_avatar_reason = reason
        web, self.web = self.web, None
        self.loading.show()
        if web is not None:
            web.hide()
            web.deleteLater()

    def _is_speaking(self) -> bool:
        return self._speaking or self._state == "speaking"

    def _push(self) -> None:
        speaking = self._is_speaking()
        if speaking != self._lipsync:
            self._lipsync = speaking
            alog("lipsync start" if speaking else "lipsync stop")
            if speaking:
                self._level_timer.start()
            else:
                self._level_timer.stop()
        if speaking:
            state = "speaking"
        elif self._state in {"thinking", "done"}:
            state = self._state
        elif self._listening:
            state = "listening"
        else:
            state = "rest"
        if self.web is None:
            return
        if state != self._pose:
            # One line per pose she takes, so a turn reads thinking, speaking, done.
            self._pose = state
            alog("clip play", name="idle" if state == "rest" else state)
        self.web.set_state(state)
        if not speaking:
            self.web.set_level(0.0)

    def _tick_level(self) -> None:
        if self.web is None or self._level is None:
            return
        try:
            level = self._level()
        # A broken level source must not stop her; she keeps her own envelope.
        except Exception:
            level = None
        self.web.set_level(level)

    # ---- painting and layout ----

    def _invalidate_caption(self) -> None:
        self.update(0, max(0, self.height() - _TEXT_H), self.width(), _TEXT_H)

    def resizeEvent(self, event) -> None:
        # One theme switch hides the chrome bars one at a time, so her panel
        # stepped through three sizes and the page reallocated its canvas for
        # each (a 116 ms frame on the switch into Filament). The veil follows
        # at once; the page takes the settled size once the layout is done.
        height = max(1, self.height() - _TEXT_H)
        self.loading.setGeometry(0, 0, max(1, self.width()), height)
        if self.web is not None and not self._place_due:
            self._place_due = True
            QTimer.singleShot(0, self, self._place_now)
        super().resizeEvent(event)

    def _place_now(self) -> None:
        # The slim title bar and the hidden chrome reach her through posted
        # layout requests, some queued after this turn was. Let them land
        # first, so the page takes one size per switch, not one per step.
        for _ in range(8):
            before = self.size()
            QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
            if self.size() == before:
                break
        self._place_due = False
        self._place()
        # The view may have been resized while Chromium held frames back (a
        # room switch): make the page fit and draw now, never an empty hub.
        refit = getattr(self.web, "refit", None)
        if callable(refit):
            refit()

    def hideEvent(self, event) -> None:
        self._level_timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        width = self.width()
        caption = self.caption_text()
        status = self.status_text()
        y = self.height() - _TEXT_H + 8
        if caption:
            self._draw_caption(painter, caption, y, width)
            y += 22
        if status:
            age = self._now() - self._status_at
            fade = 1.0
            if age > _STATUS_S - 1.5:
                fade = max(0.0, (_STATUS_S - age) / 1.5)
            painter.setOpacity(fade)
            self._draw_line(painter, status, y, width, "text_muted", 12)
            painter.setOpacity(1.0)
        painter.end()

    def _draw_caption(self, painter: QPainter, text: str, y: int, width: int) -> None:
        painter.setPen(color("text_muted"))
        font = self.font()
        font.setPixelSize(15)
        painter.setFont(font)
        if text == "speaking":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_BLUSH)
            painter.drawEllipse(int(width / 2 - 46), y + 4, 7, 7)
            painter.setPen(color("text_muted"))
        painter.drawText(0, y, width, 20, int(Qt.AlignmentFlag.AlignHCenter), text)

    def _draw_line(
        self, painter: QPainter, text: str, y: int, width: int, token: str, px: int
    ) -> None:
        painter.setPen(color(token))
        font = self.font()
        font.setPixelSize(px)
        painter.setFont(font)
        shown = QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, max(8, width - 16))
        align = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        painter.drawText(8, y, width - 16, 18, align, shown)

    def _place(self) -> None:
        height = max(1, self.height() - _TEXT_H)
        self.loading.setGeometry(0, 0, max(1, self.width()), height)
        if self.web is not None:
            self.web.setGeometry(0, 0, max(1, self.width()), height)

    def _now(self) -> float:
        if self._clock is not None:
            return float(self._clock())
        return time.monotonic()
