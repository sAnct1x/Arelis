"""Window teardown must not destroy a QThread that is still in run().

The macOS job aborted in the autouse window drain: DeferredDelete destroyed
a parent, that deleted a child QThread, and Qt called abort. These tests
keep a worker blocked across that drain.
"""

from __future__ import annotations

import inspect
import threading

import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread
from PySide6.QtWidgets import QWidget

from arelis.ui.live_threads import HANDED_OFF_WAIT_S, drain_parked_threads, quiesce_widget_threads


def test_fixture_dispose_survives_a_blocked_child_thread(qt_app) -> None:
    """The autouse drain runs after this returns, while the worker is blocked.

    A fix that only waits for a thread which is about to exit still aborts
    here: the worker stays in run() for longer than that wait.
    """
    started = threading.Event()

    class Worker(QThread):
        def run(self) -> None:
            started.set()
            threading.Event().wait(1.5)

    window = QWidget()
    worker = Worker(QObject(window))
    worker.setObjectName("dispose-probe")
    worker.start()
    assert started.wait(2)
    assert worker.isRunning()
    window.deleteLater()


def test_quiesce_unparents_a_blocked_thread_before_deferred_delete(qt_app) -> None:
    started = threading.Event()
    release = threading.Event()

    class Worker(QThread):
        def run(self) -> None:
            started.set()
            release.wait(timeout=5)

    window = QWidget()
    worker = Worker(QObject(window))
    worker.setObjectName("dispose-probe")
    worker.start()
    assert started.wait(2)
    window.deleteLater()
    try:
        quiesce_widget_threads(qt_app, wait_ms=0)
        assert worker.isRunning()
        assert worker.parent() is None
        qt_app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qt_app.processEvents()
        assert shiboken6.isValid(worker)
        assert worker.isRunning()
    finally:
        release.set()
        worker.wait(2000)


def test_run_ui_exits_drain_handed_off_threads(qt_app, monkeypatch) -> None:
    """Every run_ui exit waits out parked QThreads, including setup-not-finished.

    That return is before app.exec(), so aboutToQuit never fires. The drain
    bound must beat the 5s download connect timeout. Drop either call site
    or shrink the wait to 4s or under, and this fails.
    """
    import arelis.ui.live_threads as live
    from arelis.ui import launch as launch_mod

    assert HANDED_OFF_WAIT_S > 5.0
    assert drain_parked_threads.__defaults__ == (HANDED_OFF_WAIT_S,)
    src = inspect.getsource(launch_mod.run_ui)
    notice_at = src.index("Setup is not finished")
    return_at = src.index("return 1", notice_at)
    assert "drain_parked_threads" in src[notice_at:return_at]
    failed_at = src.index("Arelis window failed to start")
    raise_at = src.index("\n        raise", failed_at)
    assert "drain_parked_threads" in src[failed_at:raise_at]
    finally_at = src.rindex("finally:")
    assert "drain_parked_threads" in src[finally_at:]
    assert ".wait(" in inspect.getsource(live.drain_parked_threads)

    started = threading.Event()
    release = threading.Event()

    class Worker(QThread):
        def run(self) -> None:
            started.set()
            release.wait(timeout=8)

    worker = Worker()
    calls: list[float] = []
    real = live.drain_parked_threads

    def spy(timeout_s: float = HANDED_OFF_WAIT_S) -> None:
        calls.append(float(timeout_s))
        real(0.05)
        release.set()

    monkeypatch.setattr(live, "drain_parked_threads", spy)
    monkeypatch.setattr(launch_mod, "prompt_for_workspace_root", lambda: None)
    monkeypatch.setattr(launch_mod, "try_quiet_complete_model_setup", lambda: None)
    monkeypatch.setattr(launch_mod, "needs_model_setup", lambda: True)
    monkeypatch.setattr(launch_mod, "first_run_blocks_main", lambda: True)

    def fake_setup(parent: object | None = None) -> None:
        del parent
        worker.start()
        assert started.wait(2)
        live.park_running_thread(worker)
        return None

    monkeypatch.setattr(launch_mod, "prompt_for_model_setup", fake_setup)
    monkeypatch.setattr("arelis.ui.dialog.notice", lambda *a, **k: None)

    class _Lock:
        def acquire(self) -> bool:
            return True

        def release(self) -> None:
            return None

    monkeypatch.setattr("arelis.presence.lock.PresenceLock", lambda path: _Lock())
    monkeypatch.setattr(
        "arelis.presence.ipc_token.claim_session_token", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "arelis.jobs.schedule.repoint_moved_tasks_on_launch", lambda: None
    )

    try:
        code = launch_mod.run_ui({})
        assert code == 1
        assert calls, "Setup is not finished returned without drain_parked_threads"
        assert all(timeout > 5.0 for timeout in calls)
        assert worker.wait(2000)
        assert not worker.isRunning()
    finally:
        release.set()
        worker.wait(2000)
