from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def qt_app():
    """One offscreen QApplication for the widget tests.

    Offscreen because these run in CI and over SSH, where there is no display
    and Qt would otherwise abort the whole process rather than fail a test.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def arelis_window(qt_app):
    """Build ArelisWindows that are taken apart when the test ends.

    Sixteen existing tests build one by hand and hide() it in a finally block,
    which is where this whole class of crash came from. New tests should ask for
    this instead.
    """
    import asyncio

    from arelis.core.bus import EventBus

    made = []

    def _make(config: dict | None = None):
        from arelis.ui.app import ArelisWindow, BusBridge

        base = {
            "ui": {"default_width": 800, "default_height": 600},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        }
        base.update(config or {})
        window = ArelisWindow(base, BusBridge(), asyncio.new_event_loop(), EventBus())
        made.append(window)
        return window

    yield _make

    for window in made:
        try:
            window.dispose()
            window.loop.close()
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _dispose_arelis_windows():
    """Take each window apart after the test that built it.

    Sixteen tests build an ArelisWindow and only hide() it. Hiding releases
    nothing: the application-wide event filter stays installed, nine timers keep
    running, and the single-shots the constructor schedules at 0, 40, 80 and 250ms
    are still in flight. So the suite ran with a growing pile of live windows, and
    somewhere past halfway one of those late callbacks reached a widget whose C++
    half a later drain had deleted, and the process died with an access violation
    rather than a failure.

    That is why it looked like a flake that moved: which test was executing when
    the pile got big enough depended on file order, and adding a test file moved
    it. It reproduced with all five of the heavy widget files and with no pair of
    them, which is the signature of accumulation rather than interaction.

    Autouse and cheap: for the ~800 tests that never touch Qt this is one
    ``sys.modules`` lookup.
    """
    yield

    import sys

    if "PySide6.QtWidgets" not in sys.modules:
        return
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return

    window_cls = getattr(sys.modules.get("arelis.ui.app"), "ArelisWindow", None)

    for widget in list(app.topLevelWidgets()):
        try:
            if window_cls is not None and isinstance(widget, window_cls):
                widget.dispose()
                continue
            # Chat panels, orbit faces and camera docks are built bare by other
            # tests, and they run timers too — the caret blink, the shimmer, the
            # orbit animation. A widget nobody owns is a widget nobody stops.
            for timer in widget.findChildren(QTimer):
                timer.stop()
            widget.hide()
            widget.deleteLater()
        except Exception:
            # A test that already tore its own window down is not worth failing
            # here, and the drain below still runs.
            pass

    # deleteLater only queues. Without draining it the objects survive until the
    # next event loop that happens to run, which is how a stale delete ended up
    # inside an unrelated test's processEvents().
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
