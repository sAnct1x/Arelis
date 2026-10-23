"""Keep a running QThread from being destroyed with the widget that owns it.

QThread's destructor aborts the process when ``run()`` has not returned
("QThread: Destroyed while thread is still running"). A worker parented to
a window is deleted by that window's destructor. The macOS test run died
that way while tearing down the pre-upgrade backup prompt: the copy was
still inside ``run()``, deferred delete destroyed the window, and the
process aborted.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication

# Python owns a thread after setParent(None). Dropping the last wrapper
# while run() is active aborts the same way a parent destructor does.
_PARKED: list[QThread] = []


def park_running_thread(thread: QThread) -> None:
    """Unparent a live thread and hold its wrapper until ``run()`` returns."""
    from PySide6.QtCore import Qt

    if any(held is thread for held in _PARKED):
        try:
            thread.setParent(None)
        except RuntimeError:
            return
        return

    _PARKED.append(thread)
    try:
        thread.setParent(None)
    except RuntimeError:
        _PARKED.remove(thread)
        return

    def _drop(kept: QThread = thread) -> None:
        try:
            _PARKED.remove(kept)
        except ValueError:
            pass

    try:
        thread.finished.connect(_drop, Qt.ConnectionType.QueuedConnection)
    except RuntimeError:
        return
    try:
        if not thread.isRunning():
            _drop()
    except RuntimeError:
        _drop()


def quiesce_widget_threads(app: QApplication, wait_ms: int = 500) -> None:
    """Let child threads leave ``run()``, or detach any that will not.

    ``wait`` releases the GIL, so a worker that only needed the interpreter
    to return can finish. A thread that is still blocked is unparented
    before deferred delete, which is what would otherwise destroy it.
    """
    import shiboken6
    from PySide6.QtCore import QThread

    current = QThread.currentThread()
    seen: list[QThread] = []
    for widget in list(app.topLevelWidgets()):
        try:
            found = widget.findChildren(QThread)
        except RuntimeError:
            continue
        for thread in found:
            if any(held is thread for held in seen):
                continue
            seen.append(thread)

    for thread in seen:
        if thread is current or not shiboken6.isValid(thread):
            continue
        try:
            if not thread.isRunning():
                continue
            thread.requestInterruption()
            thread.quit()
            if wait_ms > 0 and thread.wait(wait_ms):
                continue
        except RuntimeError:
            continue
        if not shiboken6.isValid(thread):
            continue
        try:
            if thread.isRunning():
                park_running_thread(thread)
        except RuntimeError:
            continue


# Longer than the first-run download connect timeout (5s). A shorter
# bound leaves a handed-off QThread in run() and Qt aborts on destroy.
HANDED_OFF_WAIT_S = 6.0


def drain_parked_threads(timeout_s: float = HANDED_OFF_WAIT_S) -> None:
    """Wait out handed-off QThreads so their destructors do not abort.

    Park any workers still parented to a widget, then join each parked
    thread for up to ``timeout_s``. ``finished`` is queued, so the app
    is pumped when one exists. No app is not an excuse to skip the join.
    """
    import shiboken6
    from PySide6.QtWidgets import QApplication

    try:
        bound = max(0.0, float(timeout_s))
    except (TypeError, ValueError):
        bound = HANDED_OFF_WAIT_S
    deadline = time.monotonic() + bound

    app = QApplication.instance()
    if app is not None:
        try:
            quiesce_widget_threads(app, wait_ms=0)
        except RuntimeError:
            pass

    for thread in list(_PARKED):
        left_ms = int(max(0.0, deadline - time.monotonic()) * 1000)
        try:
            if not shiboken6.isValid(thread):
                continue
            if thread.isRunning():
                thread.wait(left_ms)
        except RuntimeError:
            continue

    while _PARKED and time.monotonic() < deadline:
        app = QApplication.instance()
        if app is None:
            break
        try:
            app.processEvents()
        except RuntimeError:
            break
        time.sleep(0.01)
