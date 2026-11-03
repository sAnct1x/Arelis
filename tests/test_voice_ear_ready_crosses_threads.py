"""The ear's warm-up finishes on the asyncio thread; idle must still leave "getting the ear"."""

from __future__ import annotations

import asyncio
import threading
import time

from PySide6.QtCore import QCoreApplication, QObject, Signal
from PySide6.QtWidgets import QApplication


class _Win(QObject):
    _ui_call = Signal(object)

    def __init__(self, loop) -> None:
        super().__init__()
        self._ui_call.connect(lambda fn: fn())
        self.loop = loop
        self._voice_preload_future = None
        self._voice_ear_ready = False
        self.preloaded = threading.Event()
        win = self

        class _Voice:
            async def warm_wake(self) -> None:
                return None

            async def preload(self) -> None:
                win.preloaded.set()

        self.voice = _Voice()


def test_the_ear_reads_ready_once_wake_warms_on_the_loop_thread(monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    from arelis.ui import voice_host

    marks = []
    monkeypatch.setattr(voice_host, "_mark_voice_preparing", lambda w, on: marks.append(on))
    monkeypatch.setattr(
        voice_host,
        "on_voice_ear_ready",
        lambda w, fut: (setattr(w, "_voice_ear_ready", True), marks.append(False)),
    )
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    try:
        win = _Win(loop)
        voice_host.preload_voice(win)
        deadline = time.monotonic() + 5.0
        while not win._voice_ear_ready and time.monotonic() < deadline:
            QCoreApplication.processEvents()
            time.sleep(0.01)
        assert win._voice_ear_ready
        assert win.preloaded.wait(5.0)  # and Whisper/TTS preload starts after it
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(2)
