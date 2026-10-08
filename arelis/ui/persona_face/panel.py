"""Avatar plus the short line under her. Job 2 docks this. It does not open the window."""

from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from arelis.ui.persona_face.avatar import PersonaAvatar
from arelis.ui.persona_face.motion import Motion, frame_interval_ms
from arelis.ui.theme import app_font, color, load_fonts

_BLOOM_S = 1.2
_FOLD_S = 1.6
_QUIET_S = 60.0
_DONE_S = 2.0
_STATUS_S = 8.0
_TEXT_H = 92
_BLUSH = QColor(245, 163, 199)


def _ease(u: float) -> float:
    u = 0.0 if u < 0.0 else (1.0 if u > 1.0 else u)
    return u * u * (3.0 - 2.0 * u)


class PersonaPanel(QWidget):
    """Her face, a state word, and one quiet status line."""

    stop_speaking_requested = Signal()
    state_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("personaPanel")
        self.setFont(app_font(load_fonts()))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setMinimumSize(220, 300)
        self.avatar = PersonaAvatar(self)
        self.avatar.pressed.connect(self._pressed)
        self._motion = Motion(seed=7)
        self._state = "rest"
        self._speaking = False
        self._busy = False
        self._mode = "orb"
        self._mode_t = 0.0
        self._quiet: float | None = None
        self._done_at: float | None = None
        self._status = ""
        self._status_at = 0.0
        self._level: Callable[[], float | None] | None = None
        self._clock: Callable[[], float] | None = None
        self._last = self._now()
        self._bake_delay = 1.5
        self._bake_armed = False
        self._hooked = False
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._on_timer)
        self._bake_arm = QTimer(self)
        self._bake_arm.setSingleShot(True)
        self._bake_arm.timeout.connect(self._kick_bake)
        self._place()

    def sizeHint(self) -> QSize:
        return QSize(370, 520)

    def set_clock(self, clock: Callable[[], float] | None) -> None:
        """Tests pass a clock so a quiet minute does not take a minute."""
        self._clock = clock
        self._last = self._now()

    def set_bake_delay(self, seconds: float) -> None:
        self._bake_delay = 0.0 if seconds < 0.0 else float(seconds)

    def set_state(self, name: str) -> None:
        if name not in {"rest", "thinking", "speaking", "done"}:
            name = "rest"
        self._state = name
        now = self._now()
        if name == "thinking":
            self._speaking = False
            self._quiet = None
            if self._mode == "orb":
                self._begin("bloom", now)
        elif name == "speaking":
            self._speaking = True
            self._quiet = None
            if self._mode == "orb":
                self._begin("bloom", now)
        elif name == "done":
            self._speaking = False
            self._done_at = now
            if self._mode == "orb":
                self._begin("bloom", now)
            if self._mode == "face":
                self._quiet = now
        else:
            self._speaking = False
            if self._mode == "face" and self._quiet is None:
                self._quiet = now
        self._push(now, 0.0)
        self._apply_interval()
        self.state_changed.emit(self._state)
        self.update()

    def set_model_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        if busy:
            self._quiet = None
        self._apply_interval()

    def set_speaking(self, speaking: bool) -> None:
        self._speaking = bool(speaking)
        now = self._now()
        if speaking:
            self._quiet = None
            if self._mode == "orb":
                self._begin("bloom", now)
        elif self._mode == "face" and self._state in {"rest", "done"} and self._quiet is None:
            self._quiet = now
        self._push(now, 0.0)
        self._apply_interval()
        self.update()

    def set_level_source(self, source: Callable[[], float | None] | None) -> None:
        self._level = source

    def show_status(self, text: str) -> None:
        self._status = " ".join(text.split())
        self._status_at = self._now()
        self.update()

    def form(self) -> str:
        if self._mode == "orb":
            return "orb"
        if self._mode == "face":
            return "face"
        return self._mode

    def caption_text(self) -> str:
        now = self._now()
        if self._state == "done" and self._done_at is not None and (now - self._done_at) < _DONE_S:
            return "done"
        if self._speaking or self._state == "speaking":
            return "speaking"
        if self._state == "thinking":
            return "thinking"
        return ""

    def hint_text(self) -> str:
        if self._speaking or self._state == "speaking":
            return "click her to stop speaking"
        return ""

    def status_text(self) -> str:
        if not self._status:
            return ""
        if self._now() - self._status_at >= _STATUS_S:
            return ""
        return self._status

    def timer_running(self) -> bool:
        return self._timer.isActive()

    def timer_interval(self) -> int:
        return int(self._timer.interval())

    @property
    def bake_ready(self) -> bool:
        return self.avatar.bake_ready()

    def bake_thread_name(self) -> str:
        return self.avatar.bake_thread_name()

    def painted_orb_while_baking(self) -> bool:
        return self.avatar.painted_orb_while_baking()

    def layer_shapes(self) -> dict:
        return self.avatar.layer_shapes()

    def rest_face_image(self):
        return self.avatar.rest_face_image()

    def _on_timer(self) -> None:
        if not self.isVisible() or self.window().isMinimized():
            self._timer.stop()
            return
        self.tick()

    def tick(self) -> None:
        now = self._now()
        dt = now - self._last
        if dt < 0.0:
            dt = 0.0
        elif dt > 0.1:
            dt = 0.1
        self._last = now
        if self._mode == "bloom":
            u = (now - self._mode_t) / _BLOOM_S
            self.avatar.reveal = _ease(u)
            if u >= 1.0:
                self._mode = "face"
                self.avatar.reveal = 1.0
                if (
                    self._state in {"rest", "done"}
                    and not self._speaking
                    and not self._busy
                    and self._quiet is None
                ):
                    self._quiet = now
        elif self._mode == "fold":
            u = (now - self._mode_t) / _FOLD_S
            self.avatar.reveal = 1.0 - _ease(u)
            if u >= 1.0:
                self._mode = "orb"
                self.avatar.reveal = 0.0
                self._quiet = None
        elif self._mode == "face" and self._fold_due(now):
            self._begin("fold", now)
        if self._status and now - self._status_at >= _STATUS_S:
            self._status = ""
        self._push(now, dt)
        self._apply_interval()
        self.avatar.update()
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._place()
        self._hook_window()
        self._sync_timer()
        if not self._bake_armed:
            self._bake_armed = True
            self._bake_arm.start(int(self._bake_delay * 1000))

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        self._place()
        self.avatar.note_resize()
        super().resizeEvent(event)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_timer()
        super().changeEvent(event)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_timer()
        return False

    def closeEvent(self, event) -> None:
        self._timer.stop()
        self._bake_arm.stop()
        self.avatar.shutdown()
        super().closeEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        width = self.width()
        caption = self.caption_text()
        hint = self.hint_text()
        status = self.status_text()
        y = self.height() - _TEXT_H + 8
        if caption:
            self._draw_caption(painter, caption, y, width)
            y += 22
        if hint:
            self._draw_line(painter, hint, y, width, "text_faint", 12)
            y += 18
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
        painter.drawText(8, y, width - 16, 18, int(Qt.AlignmentFlag.AlignHCenter), text)

    def _pressed(self) -> None:
        if self._speaking or self._state == "speaking":
            self.stop_speaking_requested.emit()
            return
        if self._mode == "orb":
            self._begin("bloom", self._now())
            self._quiet = None
            self._apply_interval()
            self.avatar.update()
            self.update()

    def _begin(self, mode: str, now: float) -> None:
        self._mode = mode
        self._mode_t = now

    def _fold_due(self, now: float) -> bool:
        if self._speaking or self._busy or self._state not in {"rest", "done"}:
            return False
        if self._quiet is None:
            return False
        return (now - self._quiet) >= _QUIET_S

    def _push(self, now: float, dt: float) -> None:
        level = None
        if self._level is not None:
            try:
                level = self._level()
            except Exception:
                level = None
        speaking = self._speaking or self._state == "speaking"
        self.avatar.frame = self._motion.step(
            now,
            dt,
            state=self._state,
            speaking=speaking,
            model_busy=self._busy,
            loudness=level,
        )
        self.avatar.thinking = self._state == "thinking"
        self.avatar.speaking = speaking
        if self._state == "done" and self._done_at is not None:
            self.avatar.glow = max(0.0, 1.0 - (now - self._done_at) / 0.8)
        else:
            self.avatar.glow = 0.0

    def _apply_interval(self) -> None:
        transitioning = self._mode in {"bloom", "fold"}
        state = "speaking" if (self._speaking or self._state == "speaking") else self._state
        form = "orb" if self._mode == "orb" else "face"
        self._timer.setInterval(
            frame_interval_ms(
                form=form,
                state=state,
                model_busy=self._busy,
                transitioning=transitioning,
            )
        )

    def _sync_timer(self) -> None:
        if not self.isVisible() or self.window().isMinimized():
            self._timer.stop()
            return
        self._apply_interval()
        if not self._timer.isActive():
            self._timer.start()

    def _hook_window(self) -> None:
        window = self.window()
        if window is None or self._hooked:
            return
        window.installEventFilter(self)
        self._hooked = True

    def _kick_bake(self) -> None:
        if self.isVisible():
            self.avatar.request_bake(0)

    def _place(self) -> None:
        height = max(1, self.height() - _TEXT_H)
        self.avatar.setGeometry(0, 0, max(1, self.width()), height)

    def _now(self) -> float:
        if self._clock is not None:
            return float(self._clock())
        return time.monotonic()
