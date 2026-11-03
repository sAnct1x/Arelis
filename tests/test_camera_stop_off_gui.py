"""QCamera.stop() blocked the GUI ~0.55 s on close; it now runs on its own thread (v11c)."""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, Slot

from arelis.ui.panels.camera import stop_camera_reaper, stop_off_gui_thread


class _SlowCam(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.ran_on: list[int] = []
        self.done = threading.Event()

    @Slot()
    def stop(self) -> None:
        time.sleep(0.5)
        self.ran_on.append(threading.get_ident())
        self.done.set()


def test_camera_stop_runs_off_the_gui_thread(qt_app) -> None:
    cam = _SlowCam()
    done = cam.done
    ran_on = cam.ran_on
    t0 = time.monotonic()
    stop_off_gui_thread(cam)
    elapsed = time.monotonic() - t0
    del cam
    assert done.wait(3.0)
    stop_camera_reaper()
    assert elapsed < 0.2, f"stop blocked the GUI thread {elapsed:.2f}s"
    assert ran_on and ran_on[0] != threading.get_ident()
