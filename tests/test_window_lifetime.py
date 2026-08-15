"""A hidden window is not a released one, and the suite used to die of it.

Sixteen tests built an ArelisWindow and called hide(). Hiding stops nothing: the
application-wide event filter stayed installed, nine timers kept running, and the
single-shots the constructor schedules at 0, 40, 80 and 250ms were still in
flight. Past halfway through the suite the process died with a Windows access
violation, in whichever test happened to be running a nested event loop when a
late callback reached freed memory — which is why the crash appeared to wander
between test_chrome_settings and test_notifications_panel depending on file order.

The sharpest instance was in ChatPanel._scroll, which scheduled two anonymous
single-shots *capturing the scroll bar object* at 0ms and 50ms. A panel destroyed
inside that window left them holding a dangling QScrollBar, which is exactly the
"Internal C++ object (QScrollBar) already deleted" that the full suite reported.
"""

from __future__ import annotations

import asyncio

from PySide6.QtCore import QTimer

from arelis.core.bus import EventBus


def _window():
    from arelis.ui.app import ArelisWindow, BusBridge

    return ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
    )


def test_dispose_stops_every_timer_not_just_the_four_that_quit_stopped(qt_app) -> None:
    window = _window()
    try:
        timers = window.findChildren(QTimer)
        assert timers, "expected the window to own timers"
        window.dispose()
        assert not any(t.isActive() for t in timers if _alive(t))
    finally:
        window.loop.close()


def test_dispose_removes_the_application_wide_event_filter(qt_app) -> None:
    """The filter is what made a hidden window keep seeing every key press."""
    window = _window()
    try:
        window.dispose()
        # Nothing observable to assert through Qt, so assert the state the app
        # keys off, and that a second dispose is harmless.
        assert window._disposed
        window.dispose()
    finally:
        window.loop.close()


def test_a_disposed_window_drops_its_deferred_callbacks(qt_app) -> None:
    """singleShot cannot be cancelled, so the guard is the whole mechanism."""
    window = _window()
    try:
        fired: list[str] = []
        window._later(0, lambda: fired.append("early"))
        window.dispose()
        window._later(0, lambda: fired.append("late"))
        qt_app.processEvents()
        assert fired == []
    finally:
        window.loop.close()


def test_the_scroll_settle_timers_belong_to_the_panel(qt_app) -> None:
    """Owned by the panel means destroyed with it, so they cannot fire late."""
    from arelis.ui.panels.chat import ChatPanel

    panel = ChatPanel()
    try:
        panel.add_user("hello")
        assert panel._settle_now.parent() is panel
        assert panel._settle_soon.parent() is panel
        assert panel._settle_now.isSingleShot()
        assert panel._settle_soon.isSingleShot()
    finally:
        panel.deleteLater()


def test_a_panel_deleted_mid_settle_does_not_take_the_process_with_it(qt_app) -> None:
    """The original crash, reproduced as an ordinary test.

    Before the fix this scheduled two lambdas holding the scroll bar, then freed
    it 50ms early.
    """
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    from arelis.ui.panels.chat import ChatPanel

    for _ in range(12):
        panel = ChatPanel()
        panel.add_user("scroll me")
        panel.add_system("and again")
        panel.deleteLater()
    app = QApplication.instance()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def _alive(obj) -> bool:
    try:
        obj.isActive()
    except RuntimeError:
        return False
    return True
