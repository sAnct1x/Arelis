"""Filament's orbit painted on a worker thread: the GUI thread only blits the last frame.

Her Quick 3D view renders on the GUI thread (QQuickWidget). A full-window Python paint of
the orbit there (10 ms idle, 20 to 40 ms with a model loading every core) held each frame
it landed on, so frame times alternated 16 / 45 ms. The GUI thread still runs the sim
(tick); each tick hands a snapshot to the worker, which paints it into a QImage.
"""

from __future__ import annotations

import atexit
import copy
import logging
import time
import weakref

from PySide6.QtCore import QObject, QRect, QSize, QThread, Signal, Slot
from PySide6.QtGui import QImage, QPainter

from arelis.ui.filament_field import FilamentField, warm_orb_stamps

# The logger the '[avatar]' lines use (persona_face.panel.alog), so the bench log has both.
LOG = logging.getLogger("arelis.avatar")
FPS_LOG_S = 5.0


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

    def __init__(self, unported_only: bool = False) -> None:
        super().__init__()
        self.unported_only = unported_only

    @Slot(object, QRect, float)
    def paint(self, field: FilamentField, rect: QRect, dpr: float) -> None:
        # Always answer, even when the paint raises: FieldRenderer holds _busy until done
        # arrives and drops every tick meanwhile, and paintEvent no longer paints the field
        # itself, so one lost done froze the field (void or one stale frame) for good.
        t0 = time.perf_counter()
        img = QImage()
        try:
            warm_orb_stamps()  # on this thread: the GUI thread never builds a stamp
            img = QImage(
                QSize(int(rect.width() * dpr), int(rect.height() * dpr)),
                QImage.Format.Format_ARGB32_Premultiplied,
            )
            img.setDevicePixelRatio(dpr)
            p = QPainter(img)
            try:
                if self.unported_only:
                    field.paint_unported(p, QRect(0, 0, rect.width(), rect.height()))
                else:
                    field._paint(p, QRect(0, 0, rect.width(), rect.height()))
            finally:
                p.end()
        except Exception:
            LOG.exception("[filament] worker paint failed")
            img = QImage()
        finally:
            self.done.emit(img, (time.perf_counter() - t0) * 1000.0)


class FieldRenderer(QObject):
    """request() after each tick; frame() is the newest painted orbit (None until the first).

    unported_only (ARELIS_SURFACE=quick): the GPU draws the void, strands, dust and hub
    threads, so the worker paints only the beads, stems and tethers, on a clear image.
    """

    _job = Signal(object, QRect, float)
    ready = Signal()

    def __init__(
        self, field: FilamentField, parent: QObject | None = None, *, unported_only: bool = False
    ) -> None:
        super().__init__(parent)
        self.field = field
        self._image: QImage | None = None
        self._busy = False
        self._busy_size: tuple[QSize, float] | None = None
        self._shown_key = 0
        self._shown = 0
        self._fps_t0 = time.monotonic()
        self._pending: tuple[QRect, float] | None = None
        self._thread = QThread()
        self._thread.setObjectName("filament-paint")
        self._worker = _Painter(unported_only)
        self._worker.moveToThread(self._thread)
        self._job.connect(self._worker.paint)
        self._worker.done.connect(self._on_done)
        self._thread.start(QThread.Priority.LowPriority)
        from PySide6.QtCore import QCoreApplication

        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)
        # A process can end without app.exec() (a probe that builds the window and calls
        # sys.exit): no aboutToQuit, and PySide's teardown then destroys the still-running
        # QThread, which Qt answers with abort (0xC0000409 on Windows). Join it at exit.
        # atexit runs these before PySide's own cleanup, which QtCore registered earlier.
        ref = weakref.ref(self)
        atexit.register(lambda: (r := ref()) is not None and r.stop())
        self.destroyed.connect(self._thread.quit)

    def request(self, rect: QRect, dpr: float) -> None:
        """Paint the field as it is now. One job in flight; ticks during it are skipped.

        A tick that lands while a frame is in flight is dropped, not queued: queuing it
        painted back to back, so a slow paint ran the worker flat out. Only a new size
        or DPR (resize, span grow) is kept, so frame_for gets a frame at that size.
        """
        if self._busy:
            if self._busy_size != (rect.size(), dpr):
                self._pending = (QRect(rect), dpr)
            return
        self._busy = True
        self._busy_size = (rect.size(), dpr)
        self._job.emit(snapshot(self.field), QRect(rect), dpr)

    def frame(self) -> QImage | None:
        return self._image

    def frame_for(self, rect: QRect, dpr: float) -> QImage | None:
        """The newest frame if it was painted at this size; else None (asks for one)."""
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
        if not img.isNull():  # a failed paint keeps the last good frame
            self._image = img
        self._busy = False
        self._busy_size = None
        self.ready.emit()
        if self._pending is not None:
            rect, dpr = self._pending
            self._pending = None
            self.request(rect, dpr)

    def note_shown(self, img: QImage) -> None:
        """paintEvent drew this worker frame. Every 5 s log '[filament] orbit fps=N'.

        Counts distinct worker frames that reached the screen, not ticks or requests:
        a repaint of the same frame (a hover, a layout flush) does not count.
        """
        key = img.cacheKey()
        if key != self._shown_key:
            self._shown_key = key
            self._shown += 1
        now = time.monotonic()
        if now - self._fps_t0 >= FPS_LOG_S:
            LOG.info("[filament] orbit fps=%d", round(self._shown / (now - self._fps_t0)))
            self._shown = 0
            self._fps_t0 = now

    def stop(self) -> None:
        self._pending = None
        try:
            self._thread.quit()
            self._thread.wait(2000)
        except RuntimeError:
            pass  # Qt already deleted it
