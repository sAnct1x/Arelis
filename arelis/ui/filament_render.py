"""Filament's orbit painted on a worker thread: the GUI thread only blits the last frame.

Her Quick 3D view renders on the GUI thread (QQuickWidget). A full-window Python paint of
the orbit there (10 ms idle, 20 to 40 ms with a model loading every core) held each frame
it landed on, so frame times alternated 16 / 45 ms. The GUI thread still runs the sim
(tick); each tick hands a snapshot to the worker, which paints it into a QImage.
"""

from __future__ import annotations

import copy
import time

from PySide6.QtCore import QObject, QRect, QSize, QThread, Signal, Slot
from PySide6.QtGui import QImage, QPainter

from arelis.ui.filament_field import FilamentField, warm_orb_stamps


def snapshot(field: FilamentField) -> FilamentField:
    """A copy the worker may paint while the GUI thread ticks the original."""
    snap = copy.copy(field)
    snap.dust = [dict(d) for d in field.dust]
    snap._tethers = {k: dict(v) for k, v in field._tethers.items()}
    for name in ("_open", "_hidden", "_live", "_hot"):
        setattr(snap, name, set(getattr(field, name)))
    return snap


class _Painter(QObject):
    done = Signal(QImage, float)

    @Slot(object, QRect, float)
    def paint(self, field: FilamentField, rect: QRect, dpr: float) -> None:
        t0 = time.perf_counter()
        img = QImage(
            QSize(int(rect.width() * dpr), int(rect.height() * dpr)),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        img.setDevicePixelRatio(dpr)
        p = QPainter(img)
        field._paint(p, QRect(0, 0, rect.width(), rect.height()))
        p.end()
        self.done.emit(img, (time.perf_counter() - t0) * 1000.0)


class FieldRenderer(QObject):
    """request() after each tick; frame() is the newest painted orbit (None until the first)."""

    _job = Signal(object, QRect, float)
    ready = Signal()

    def __init__(self, field: FilamentField, parent: QObject | None = None) -> None:
        super().__init__(parent)
        warm_orb_stamps()  # stamps are made on the GUI thread; the worker only draws them
        self.field = field
        self._image: QImage | None = None
        self._busy = False
        self._pending: tuple[QRect, float] | None = None
        self._thread = QThread()
        self._thread.setObjectName("filament-paint")
        self._worker = _Painter()
        self._worker.moveToThread(self._thread)
        self._job.connect(self._worker.paint)
        self._worker.done.connect(self._on_done)
        self._thread.start(QThread.Priority.LowPriority)
        from PySide6.QtCore import QCoreApplication

        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)
        self.destroyed.connect(self._thread.quit)

    def request(self, rect: QRect, dpr: float) -> None:
        """Paint the field as it is now. One job in flight; a newer one replaces a waiting one."""
        if self._busy:
            self._pending = (QRect(rect), dpr)
            return
        self._busy = True
        self._job.emit(snapshot(self.field), QRect(rect), dpr)

    def frame(self) -> QImage | None:
        return self._image

    def frame_for(self, rect: QRect, dpr: float) -> QImage | None:
        """The newest frame if it was painted at this size; else None (paint in place)."""
        img = self._image
        if (
            img is None
            or img.devicePixelRatio() != dpr
            or img.size() != QSize(int(rect.width() * dpr), int(rect.height() * dpr))
        ):
            self.request(rect, dpr)
            return None
        return img

    @Slot(QImage, float)
    def _on_done(self, img: QImage, ms: float) -> None:
        self._image = img
        self._busy = False
        self.field.note_paint_ms(ms)
        self.ready.emit()
        if self._pending is not None:
            rect, dpr = self._pending
            self._pending = None
            self.request(rect, dpr)

    def stop(self) -> None:
        self._pending = None
        self._thread.quit()
        self._thread.wait(2000)
