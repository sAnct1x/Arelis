"""Native shutdown regression: no model, camera, or network; abort stays in a child."""

from __future__ import annotations

import threading
import time
import weakref

import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QThread

from tests.overseer_render_helpers import isolated_render


@isolated_render()
def test_delayed_close_retains_worker_through_restart_and_owner_destruction(qt_app, monkeypatch):
    from arelis.ui import spatial_hands as sh
    from arelis.ui.live_threads import _PARKED

    def drain():
        qt_app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()

    def until(predicate):
        deadline = time.monotonic() + 4
        while not predicate() and time.monotonic() < deadline:
            drain()
            threading.Event().wait(0.005)
        assert predicate()

    def cycle():
        ready = [threading.Event(), threading.Event()]
        closing = [threading.Event(), threading.Event()]
        release = [threading.Event(), threading.Event()]
        index = iter(range(2))

        class Backend:
            name = "controlled-delayed-close"

            def __init__(self, i):
                self.i = i

            def close(self):
                closing[self.i].set()
                assert release[self.i].wait(8)

        def backend():
            i = next(index)
            ready[i].set()
            return Backend(i)

        monkeypatch.setattr(sh, "load_backend", backend)
        parked_before = len(_PARKED)
        owner = sh.SpatialHands()
        destroyed = []
        previews = []
        statuses = []
        owner.preview_ready.connect(previews.append)
        owner.hint.connect(statuses.append)
        try:
            assert owner.start_track()
            first = owner._worker
            assert first is not None and ready[0].wait(2)
            first.destroyed.connect(lambda: destroyed.append(QThread.currentThread()))
            reference = weakref.ref(first)

            def late_signals(worker=first):
                worker.preview_ready.emit("retired")
                worker.status.emit("retired")
                worker.hands_ready.emit(None)

            queued = threading.Thread(target=late_signals)
            queued.start()
            queued.join()
            del queued, late_signals
            start = time.monotonic()
            owner.stop_track()
            elapsed = time.monotonic() - start
            assert closing[0].wait(2)
            # The old implementation aborts here: close is still blocked, but
            # stop_track queued deletion despite wait(2000) returning False.
            drain()
            assert elapsed < 1
            assert previews == [] and "retired" not in statuses
            assert not owner.tracking and owner._worker is None
            assert first.parent() is None and first.isRunning()
            del first
            assert reference() is not None  # application owns the closing worker

            assert owner.start_track()
            second = owner._worker
            assert second is not None and ready[1].wait(2)
            release[0].set()
            until(lambda: len(destroyed) == 1)
            assert reference() is None or not shiboken6.isValid(reference())
            assert owner.tracking and owner._worker is second
            second.destroyed.connect(lambda: destroyed.append(QThread.currentThread()))
            owner.stop_track()
            assert closing[1].wait(2)
            owner.deleteLater()
            drain()  # closing worker must outlive destruction of its former owner
            assert second.isRunning() and second.parent() is None
            release[1].set()
            until(lambda: len(destroyed) == 2)
            assert not shiboken6.isValid(second)
            assert all(thread == qt_app.thread() for thread in destroyed)
            assert len(_PARKED) == parked_before
        finally:
            for event in release:
                event.set()
            if shiboken6.isValid(owner):
                owner.stop_track()
                owner.deleteLater()
            drain()

    for _ in range(3):
        cycle()
