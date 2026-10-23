"""Closing the window must not freeze the Qt thread on teardown waits."""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMainWindow

from arelis.ui.launch import _flush_pending_writes
from arelis.ui.window_lifetime import WindowLifetime

_BLOCK_LIMIT_S = 0.4


class _SlowInbound:
    owned = True

    def __init__(self) -> None:
        self.started = threading.Event()

    async def stop(self) -> None:
        self.started.set()
        await asyncio.sleep(2.0)


class _SlowIndexer:
    async def flush(self, *, max_batches: int = 50) -> int:
        del max_batches
        await asyncio.sleep(1.5)
        return 0


class _CloseHost(WindowLifetime, QMainWindow):
    def __init__(
        self,
        *,
        force_quit: bool,
        loop: asyncio.AbstractEventLoop,
        inbound: _SlowInbound,
        indexer: _SlowIndexer,
    ) -> None:
        QMainWindow.__init__(self)
        self._close_to_tray = False
        self._force_quit = force_quit
        self._disposed = False
        self._tray = None
        self._turn_busy = False
        self.voice_controller = None
        self.camera = SimpleNamespace(stop=lambda: None)
        self.inbound_runtime = inbound
        self.loop = loop
        self.indexer = indexer
        self.sms_ingest = object()
        self.sms_watcher = object()
        self.sms_auto_reply = object()
        self._index_timer = QTimer(self)
        self._atmosphere_timer = QTimer(self)
        self._notify_timer = QTimer(self)
        self._calendar_sync_timer = QTimer(self)
        self._calendar_sync_watchdog = QTimer(self)
        self._job_tick = QTimer(self)
        self.workspace_roots = SimpleNamespace(clear_external_reads=lambda: None)

    def _persist_window_layout(self) -> None:
        return None

    def _park_floating_docks(self) -> None:
        return None


def _start_loop() -> tuple[asyncio.AbstractEventLoop, threading.Thread]:
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def _run() -> None:
        asyncio.set_event_loop(loop)
        ready.set()
        loop.run_forever()

    thread = threading.Thread(target=_run, name="arelis-test-close-loop", daemon=True)
    thread.start()
    assert ready.wait(timeout=2.0)
    return loop, thread


def _stop_loop(loop: asyncio.AbstractEventLoop, thread: threading.Thread) -> None:
    async def _shutdown() -> None:
        current = asyncio.current_task()
        pending = [task for task in asyncio.all_tasks(loop) if task is not current]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.wait(pending, timeout=0.2)
        loop.stop()

    try:
        asyncio.run_coroutine_threadsafe(_shutdown(), loop).result(timeout=1.0)
    except Exception:
        loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=2.0)


def test_window_close_does_not_block_the_ui(qt_app: Any, monkeypatch: Any) -> None:
    """Window close and tray Quit must return before the slow teardown waits.

    closeEvent used to wait on inbound.stop (2s/5s), indexer.flush (1.5s on
    an ordinary close), and park_comfy (sync HTTP) on the Qt thread. hide()
    cannot paint while that thread is blocked, so the window froze for
    about 2.5 s. Writes and Comfy park share the leftover #384 deadline
    after the glass is gone.
    """
    del qt_app
    parked: list[str] = []
    flushed: list[str] = []

    def _park() -> None:
        parked.append("park")
        time.sleep(1.0)

    def _flush(**kwargs: Any) -> None:
        del kwargs
        flushed.append("writes")

    monkeypatch.setattr("arelis.tools.comfy_lifecycle.park_comfy", _park)
    monkeypatch.setattr("arelis.tools.comfy_lifecycle.cancel_comfy_idle", lambda: None)
    monkeypatch.setattr("arelis.ui.window_lifetime.stop_speech", lambda window: None)
    monkeypatch.setattr("arelis.ui.window_lifetime.bind_app_bus", lambda bus: None)
    monkeypatch.setattr("arelis.ui.launch.flush_background_writes", _flush)

    loop, thread = _start_loop()
    failures: list[str] = []
    try:
        for label, force in (("window_close", False), ("tray_quit", True)):
            parked.clear()
            inbound = _SlowInbound()
            host = _CloseHost(
                force_quit=force,
                loop=loop,
                inbound=inbound,
                indexer=_SlowIndexer(),
            )
            t0 = time.monotonic()
            host.close()
            elapsed = time.monotonic() - t0
            if elapsed >= _BLOCK_LIMIT_S:
                failures.append(f"{label}: close blocked {elapsed:.2f}s")
            if not inbound.started.wait(timeout=1.0):
                failures.append(f"{label}: inbound stop was not started")
            if parked:
                failures.append(f"{label}: park_comfy ran on the Qt close path")
            host.deleteLater()

        parked.clear()
        flushed.clear()
        _flush_pending_writes(
            store=None,
            indexer=None,
            backup_thread=None,
            timeout_s=1.5,
        )
        if flushed != ["writes"]:
            failures.append("flush skipped the #384 write join")
        if parked != ["park"]:
            failures.append("flush leftover did not park Comfy")
    finally:
        _stop_loop(loop, thread)

    assert not failures, "\n".join(failures)
