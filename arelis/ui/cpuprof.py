"""CPU-side frame pacing, measured (a measurement build; everything is off unless asked for).

``ARELIS_TIMER_RES=1``
    At startup, before the QApplication: winmm ``timeBeginPeriod(1)`` (Windows' system timer
    from 15.6 ms ticks to 1 ms for this process), and on Windows 11 opt this process out of
    timer-resolution throttling (``PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION``), so the
    request holds while the window is not in front. ``timeEndPeriod(1)`` at exit.

``ARELIS_WAKE_LOG=<path>``
    A GUI-thread wakeup probe: a single-shot ``Qt.PreciseTimer`` armed for
    ``ARELIS_WAKE_PROBE_MS`` (default 1) and re-armed from its own timeout. Each timeout writes
    ``t_epoch_ms,scheduled_ms,actual_ms,late_ms`` (perf-counter times relative to the probe's
    start): how late the GUI thread's event loop got to a timer that was due. Lateness in
    15.6 ms steps is timer granularity; lateness that tracks CPU load is the GUI thread waiting
    for a core (or busy in a long event).

Both are read once at startup; nothing here changes how she renders.
"""

from __future__ import annotations

import atexit
import logging
import os
import sys
import time

TIMER_RES_ENV = "ARELIS_TIMER_RES"
WAKE_LOG_ENV = "ARELIS_WAKE_LOG"
WAKE_MS_ENV = "ARELIS_WAKE_PROBE_MS"
_ON = {"1", "true", "yes", "on"}
LOG = logging.getLogger("arelis.cpuprof")


def raise_timer_resolution(env=os.environ) -> bool:
    """ARELIS_TIMER_RES=1 on Windows: timeBeginPeriod(1) for the life of the process."""
    if env.get(TIMER_RES_ENV, "").strip().lower() not in _ON or sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    winmm = ctypes.WinDLL("winmm")
    ok = winmm.timeBeginPeriod(1) == 0  # TIMERR_NOERROR
    if ok:
        atexit.register(winmm.timeEndPeriod, 1)

    class _Throttle(ctypes.Structure):
        _fields_ = [
            ("Version", wintypes.ULONG),
            ("ControlMask", wintypes.ULONG),
            ("StateMask", wintypes.ULONG),
        ]

    # ProcessPowerThrottling = 4; IGNORE_TIMER_RESOLUTION = 0x4 in ControlMask, 0 in StateMask:
    # always honour this process's timer resolution (Windows 11 drops it for background windows).
    state = _Throttle(1, 0x4, 0)
    k32 = ctypes.WinDLL("kernel32")
    honoured = bool(
        k32.SetProcessInformation(
            k32.GetCurrentProcess(), 4, ctypes.byref(state), ctypes.sizeof(state)
        )
    )
    print(
        f"[cpuprof] timeBeginPeriod(1) ok={ok} ignore_timer_throttling={honoured}", file=sys.stderr
    )
    return ok


class WakeProbe:
    """Re-armed 1 ms PreciseTimer on the GUI thread; logs scheduled vs actual time."""

    def __init__(self, path: str, interval_ms: int = 1) -> None:
        from PySide6.QtCore import QCoreApplication, Qt, QTimer

        self._file = open(path, "w", encoding="utf-8", buffering=1 << 16)
        self._file.write("t_epoch_ms,scheduled_ms,actual_ms,late_ms\n")
        self._ms = max(1, interval_ms)
        self._t0 = time.perf_counter()
        self._due = 0.0
        self._timer = QTimer()
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)
        self._flush = QTimer()
        self._flush.setInterval(1000)
        self._flush.timeout.connect(lambda: self._file and self._file.flush())
        self._flush.start()
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.close)
        atexit.register(self.close)
        self._arm()

    def _now(self) -> float:
        return (time.perf_counter() - self._t0) * 1000.0

    def _arm(self) -> None:
        self._due = self._now() + self._ms
        self._timer.start(self._ms)

    def _tick(self) -> None:
        if self._file is None:
            return
        now = self._now()
        self._file.write(
            f"{time.time() * 1000.0:.2f},{self._due:.3f},{now:.3f},{now - self._due:.3f}\n"
        )
        self._arm()

    def close(self) -> None:
        if self._file is not None:
            self._timer.stop()
            self._file.close()
            self._file = None


_PROBE: WakeProbe | None = None


def start_wake_probe(env=os.environ) -> WakeProbe | None:
    """After the QApplication exists, on the GUI thread."""
    global _PROBE
    path = env.get(WAKE_LOG_ENV, "").strip()
    if not path or _PROBE is not None:
        return _PROBE
    try:
        ms = int(env.get(WAKE_MS_ENV, "1") or 1)
    except ValueError:
        ms = 1
    _PROBE = WakeProbe(path, ms)
    LOG.info("[cpuprof] wake probe every %d ms -> %s", ms, path)
    return _PROBE
