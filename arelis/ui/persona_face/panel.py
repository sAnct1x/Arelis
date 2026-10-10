"""Avatar plus the short line under her. Job 2 docks this. It does not open the window."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QWidget

from arelis.ui.persona_face.avatar import PersonaAvatar
from arelis.ui.persona_face.engine import PHASE_COUNT
from arelis.ui.persona_face.motion import Motion, frame_interval_ms
from arelis.ui.theme import app_font, color, load_fonts

# She materializes over a couple of seconds. Folding back is shorter.
BLOOM_S = 2.6
FOLD_S = 1.25
_BLOOM_S = BLOOM_S
_FOLD_S = FOLD_S
_DONE_S = 2.0
_STATUS_S = 8.0
_TEXT_H = 92
_BLUSH = QColor(245, 163, 199)
_LOG = logging.getLogger("arelis.persona_face")


def _ease(u: float) -> float:
    """Ease in and out. The middle of the bloom sits strictly between 0 and 1."""
    u = 0.0 if u < 0.0 else (1.0 if u > 1.0 else u)
    return u * u * (3.0 - 2.0 * u)


def client_animations() -> bool:
    """Windows client-area animation flag. Other platforms keep the bloom."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        flag = ctypes.c_int(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(flag), 0)
        if not ok:
            return True
        return bool(flag.value)
    # user32 missing or blocked: keep the bloom rather than a hard cut.
    except Exception:
        return True


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
        # The avatar waits for the dock size to settle, then reads the cache.
        # A second delay here used to start after layout and miss that file.
        self._bake_delay = 0.0
        self._bake_armed = False
        self._hooked = False
        self._force_motion: bool | None = None
        self._phase0_at: float | None = None
        self._bloom_before_face = False
        self.wake_start_perf: float | None = None
        self.wake_end_perf: float | None = None
        self.wake_duration_s: float | None = None
        self.fold_start_perf: float | None = None
        self.fold_end_perf: float | None = None
        self.fold_duration_s: float | None = None
        self.avatar.layers_in.connect(self._on_layers)
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
            # Reply finished: a warm smile eases in, then out.
            if self._mode == "face":
                self._motion.cue("smile", now)
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
        self.avatar.update()
        self._invalidate_caption()

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

    def set_chat_side(self, side: float) -> None:
        """Where the chat is from her: -1 to the left (dock on the right), +1 right."""
        self._motion.chat_side = -1.0 if side < 0.0 else 1.0

    def cue(self, name: str) -> None:
        """Trigger one motion event now: smile, wink, nod, look or glance."""
        self._motion.cue(name, self._now())

    def set_level_source(self, source: Callable[[], float | None] | None) -> None:
        self._level = source

    def show_status(self, text: str) -> None:
        self._status = " ".join(text.split())
        self._status_at = self._now()
        self._invalidate_caption()

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

    def face_ready(self) -> bool:
        """Phase 0 is up and the materialize has finished.

        All hair phases count, or a few seconds after phase 0 if the rest is
        still landing. Shots wait on this instead of a fixed sleep.
        """
        phases = self.avatar.phases_ready()
        if phases < 1 or self._mode != "face" or self.avatar.reveal < 0.999:
            return False
        if phases >= PHASE_COUNT:
            return True
        if self._phase0_at is None:
            return False
        return (self._now() - self._phase0_at) >= 4.0

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
        if self.avatar.phases_ready() >= 1 and self._phase0_at is None:
            self._phase0_at = now
        # A turn can ask for the wake while the orb is still the only thing
        # drawn. The clock used to run out during the bake, so the face popped
        # in. Start the 2.6 s when the layers actually exist.
        self._release_wake(now)
        if self._mode == "bloom":
            u = (now - self._mode_t) / _BLOOM_S
            self.avatar.reveal = _ease(u)
            if u >= 1.0:
                self._mode = "face"
                self.avatar.reveal = 1.0
                self._wake_end()
                # Greeting: she smiles as she arrives.
                self._motion.cue("smile", now)
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
                self._fold_end()
        elif self._mode == "face" and self._fold_due(now):
            self._begin("fold", now)
        if self._status and now - self._status_at >= _STATUS_S:
            self._status = ""
        self._push(now, dt)
        self._apply_interval()
        self.avatar.update()
        self._invalidate_caption()

    def _caption_signature(self) -> tuple:
        return (self.caption_text(), self.hint_text(), self.status_text(), self._status_fade_step())

    def _status_fade_step(self) -> int:
        if not self._status:
            return 0
        age = self._now() - self._status_at
        if age <= _STATUS_S - 1.5:
            return 0
        return int(age * 10)

    def _invalidate_caption(self) -> None:
        """Repaint the strip under her only when the words or the fade step changed."""
        sig = self._caption_signature()
        if sig == getattr(self, "_caption_sig", None):
            return
        self._caption_sig = sig
        self.update(0, max(0, self.height() - _TEXT_H), self.width(), _TEXT_H)

    def wake_for_window(self) -> None:
        """Start the bake and the bloom once the window is up. Not from showEvent."""
        if not self._bake_armed:
            self._bake_armed = True
            self._bake_arm.start(int(self._bake_delay * 1000))
        if self._mode == "orb" and self._quiet is None:
            self._begin("bloom", self._now())
            self._apply_interval()

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
        shown = QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, max(8, width - 16))
        painter.drawText(
            8,
            y,
            width - 16,
            18,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            shown,
        )

    def _pressed(self) -> None:
        if self._speaking or self._state == "speaking":
            self.stop_speaking_requested.emit()
            return
        if self._mode == "orb":
            self._begin("bloom", self._now())
            self._quiet = None
            self._apply_interval()
            self.avatar.update()
            self._invalidate_caption()

    def _animations_on(self) -> bool:
        if self._force_motion is not None:
            return bool(self._force_motion)
        return client_animations()

    def _wake_begin(self) -> None:
        stamp = time.perf_counter()
        self.wake_start_perf = stamp
        self.wake_end_perf = None
        self.wake_duration_s = None
        _LOG.info("persona wake start %.6f", stamp)

    def _wake_end(self) -> None:
        if self.wake_start_perf is None or self.wake_end_perf is not None:
            return
        stamp = time.perf_counter()
        self.wake_end_perf = stamp
        self.wake_duration_s = stamp - self.wake_start_perf
        _LOG.info("persona wake end %.6f duration %.3f", stamp, self.wake_duration_s)

    def _fold_begin(self) -> None:
        stamp = time.perf_counter()
        self.fold_start_perf = stamp
        self.fold_end_perf = None
        self.fold_duration_s = None
        _LOG.info("persona fold start %.6f", stamp)

    def _fold_end(self) -> None:
        if self.fold_start_perf is None or self.fold_end_perf is not None:
            return
        stamp = time.perf_counter()
        self.fold_end_perf = stamp
        self.fold_duration_s = stamp - self.fold_start_perf
        _LOG.info("persona fold end %.6f duration %.3f", stamp, self.fold_duration_s)

    def _release_wake(self, now: float) -> None:
        """Start the 2.6 s clock when the layers exist, not on the next timer."""
        if not (self.avatar.bake_ready() and self._bloom_before_face):
            return
        self._bloom_before_face = False
        if not self._animations_on():
            self._mode = "face"
            self._mode_t = now
            self.avatar.reveal = 1.0
            self._wake_begin()
            self._wake_end()
            return
        self._mode = "bloom"
        self._mode_t = now
        self.avatar.reveal = 0.0
        self._wake_begin()

    def _on_layers(self) -> None:
        self._release_wake(self._now())

    def _begin(self, mode: str, now: float) -> None:
        if not self._animations_on():
            if mode == "bloom":
                self._mode = "face"
                self._mode_t = now
                self.avatar.reveal = 1.0
                self._bloom_before_face = False
                self._wake_begin()
                self._wake_end()
                return
            if mode == "fold":
                self._mode = "orb"
                self._mode_t = now
                self.avatar.reveal = 0.0
                self._quiet = None
                self._fold_begin()
                self._fold_end()
                return
        self._mode = mode
        self._mode_t = now
        if mode == "bloom" and not self.avatar.bake_ready():
            # The clock restarts when the layers land, so a bake does not eat it.
            self._bloom_before_face = True
            return
        if mode == "bloom":
            self._wake_begin()
        elif mode == "fold":
            self._fold_begin()

    def _fold_due(self, now: float) -> bool:
        """She stays out. A quiet minute does not fold her back into the orb."""
        del now
        return False

    def _push(self, now: float, dt: float) -> None:
        level = None
        if self._level is not None:
            try:
                level = self._level()
            # A broken level source must not stop her; fall back to the gentle envelope.
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
