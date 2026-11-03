"""Launch splash: her energy breathing while the seat, her voice and the window load.

The same breathing light as QuickSurface.qml's loadingState (three rings and a core, the
same radii, colours and 2.4 s sine), painted with QPainter so it needs no QML engine.
Imports stay light: PySide6 only.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from typing import TypeVar

from PySide6.QtCore import QEventLoop, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

T = TypeVar("T")

_BREATH_S = 2.4  # one way, as the QML SequentialAnimation
_VOID = (8, 7, 14)


def breath_at(t: float) -> float:
    """0..1..0 over 2 x 2.4 s, InOutSine both ways (QuickSurface.qml loadingState.breath)."""
    return 0.5 - 0.5 * math.cos(math.pi * (t / _BREATH_S))


SPLASH_TITLE = "Arelis loading"
_RING_GAP = 24  # clear space round the outer ring at full breath: plate edge and status line


class LaunchSplash(QWidget):
    """Small frameless plate shown before the main window exists."""

    def __init__(self, void: tuple[int, int, int] | None = None) -> None:
        super().__init__(
            None,
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setObjectName("LaunchSplash")
        # An explicit title: with none, Windows shows Qt's applicationDisplayName ('Arelis'),
        # and the installer window-probe would pass on this splash alone. The probe skips
        # exactly this title (scripts/installer_smoke.py SPLASH_TITLE).
        self.setWindowTitle(SPLASH_TITLE)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(320, 300)
        self._void = QColor(*(void or _VOID))
        self._status = "Starting"
        self._t0 = time.monotonic()
        self.frames = 0
        self._tick = QTimer(self)
        self._tick.setInterval(33)
        self._tick.timeout.connect(self.update)

    def start(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is not None:
            box = self.frameGeometry()
            box.moveCenter(screen.availableGeometry().center())
            self.move(box.topLeft())
        self.show()
        self._tick.start()
        self.pump()

    def set_status(self, text: str) -> None:
        self._status = str(text)
        self.update()
        self.pump()

    def status(self) -> str:
        return self._status

    def pump(self) -> None:
        """Paint now. Input is held back: nothing else should run before the window."""
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def finish(self) -> None:
        self._tick.stop()
        self.close()
        self.deleteLater()

    @staticmethod
    def ring_radius(i: int, breath: float) -> float:
        return 26 + i * 22 + breath * (10 + i * 8)

    def ring_centre(self) -> tuple[float, float]:
        return self.width() * 0.5, self.height() * 0.41

    def status_rect(self) -> QRectF:
        return QRectF(0, self.height() - 52, self.width(), 24)

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        self.frames += 1
        breath = breath_at(time.monotonic() - self._t0)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._void)
        p.drawRoundedRect(QRectF(self.rect()), 18, 18)
        # The outer ring at full breath kept 11 px to the top edge and ran into the status
        # line, so the rings looked jammed against the top and the text: centre them in a
        # taller plate with _RING_GAP clear all round.
        cx, cy = self.ring_centre()
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(3):
            r = self.ring_radius(i, breath)
            pen = QPen(QColor.fromRgbF(0.66, 0.56, 1.0, (0.42 - i * 0.11) * (0.55 + 0.45 * breath)))
            pen.setWidthF(1.2)
            p.setPen(pen)
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        r = 7 + breath * 3
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor.fromRgbF(0.86, 0.80, 1.0, 0.55 + 0.4 * breath))
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        font = QFont(self.font())
        font.setPixelSize(15)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        p.setFont(font)
        p.setPen(QColor.fromRgbF(0.80, 0.74, 1.0, 0.45 + 0.35 * breath))
        p.drawText(
            self.status_rect(),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            self._status,
        )
        p.end()


def run_off_ui(splash: LaunchSplash | None, status: str, work: Callable[[], T]) -> T:
    """Run work on a worker thread while the splash keeps breathing; its error is re-raised.

    Without a splash (a quiet or background launch, tests) work runs here, as before.
    """
    if splash is None:
        return work()
    splash.set_status(status)
    out: dict[str, object] = {}
    loop = QEventLoop()

    def _run() -> None:
        try:
            out["value"] = work()
        except BaseException as exc:  # handed to the UI thread below
            out["error"] = exc

    worker = threading.Thread(target=_run, name="arelis-launch-load", daemon=True)
    poll = QTimer()
    poll.setInterval(15)
    poll.timeout.connect(lambda: None if worker.is_alive() else loop.quit())
    worker.start()
    poll.start()
    loop.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    poll.stop()
    worker.join()
    if "error" in out:
        raise out["error"]  # type: ignore[misc]
    return out["value"]  # type: ignore[return-value]
