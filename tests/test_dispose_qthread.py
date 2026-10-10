"""Window teardown must not destroy a QThread that is still in run().

The macOS job aborted in the autouse window drain: DeferredDelete destroyed
a parent, that deleted a child QThread, and Qt called abort. These tests
keep a worker blocked across that drain.
"""

from __future__ import annotations

import threading

import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread
from PySide6.QtWidgets import QWidget

from arelis.ui.live_threads import quiesce_widget_threads


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
