"""Phase 6.1: a turn that never gets Stop still unlocks when it hangs.

The 8s busy watchdog only arms after Stop. These drive `_set_busy` /
`_on_stop` on a real window so a helper-only countdown cannot hide a miss.
"""

from __future__ import annotations

from PySide6.QtTest import QTest


def _short_ceiling(window, seconds: float = 0.08) -> None:
    ui = window.config.setdefault("ui", {})
    ui["hung_turn_s"] = seconds


def test_countdown_is_not_armed_when_idle(arelis_window) -> None:
    window = arelis_window()
    timer = getattr(window, "_hung_watchdog", None)
    assert timer is None or not timer.isActive()
    assert window.chat.progress.isHidden()
    assert "left" not in window.chat.progress.text()


def test_hung_ceiling_unlocks_without_stop(arelis_window, qt_app) -> None:
    window = arelis_window()
    _short_ceiling(window)
    window._set_busy(True)
    assert window._turn_busy
    assert window._hung_watchdog.isActive()
    assert "left" not in window.chat.progress.text()
    assert window.chat.progress.text().strip()
    assert not window.chat.progress.isHidden()

    QTest.qWait(250)

    assert window._turn_busy is False
    assert not window.conversation._busy
    assert window.chat.progress.isHidden()
    shown = window.chat.view.toPlainText()
    assert "hung" in shown.lower()
    assert "stop requested" not in shown.lower()
    assert "stop requested" not in window.thinking.footer.text().lower()
    assert "hung" in window.thinking.footer.text().lower()
    assert not window._hung_watchdog.isActive()
    assert not window._busy_watchdog.isActive()


def test_stop_cancels_the_hung_ceiling(arelis_window, qt_app) -> None:
    window = arelis_window()
    _short_ceiling(window, 0.2)
    window._set_busy(True)
    window._on_stop()

    assert not window._hung_watchdog.isActive()
    assert window._turn_busy
    assert window._busy_watchdog.isActive()
    assert "stop requested" in window.thinking.footer.text()

    QTest.qWait(350)

    assert window._turn_busy
    shown = window.chat.view.toPlainText()
    assert "hung" not in shown.lower()
    assert "stop requested" in window.thinking.footer.text()


def test_clearing_busy_disarms_the_countdown(arelis_window) -> None:
    window = arelis_window()
    _short_ceiling(window, 90)
    window._set_busy(True)
    assert window._hung_watchdog.isActive()
    window._set_busy(False)
    assert not window._hung_watchdog.isActive()
    assert "left" not in window.chat.progress.text()
    assert window.chat.progress.isHidden()


def test_idle_stop_does_not_arm_the_busy_watchdog(arelis_window) -> None:
    """Login YOUR_TURN already ended the turn. Stop after closing Chrome
    used to arm an 8s timer that then killed 'excellent job'."""
    window = arelis_window()
    window._on_stop()
    assert not window._turn_busy
    assert not window._busy_watchdog.isActive()
    assert "Turn ended without a reply" not in window.chat.view.toPlainText()


def test_new_turn_after_stop_is_not_killed_by_the_watchdog(arelis_window) -> None:
    window = arelis_window()
    window._set_busy(True)
    window._on_stop()
    assert window._busy_watchdog.isActive()
    window._set_busy(True)
    assert not window._busy_watchdog.isActive()
    assert window._turn_busy
    window._on_busy_watchdog()
    assert window._turn_busy
    assert "Turn ended without a reply" not in window.chat.view.toPlainText()


class _GatheredLoop:
    def __init__(self, tools: set[str] | None = None) -> None:
        self.tools_used = set(tools or set())
        self._trace: list[str] = []
        self.terminal_sent = False
        self._in_close = False
        self.closed = False

    def request_close(self) -> None:
        self.closed = True


class _Orch:
    def __init__(self, loop: _GatheredLoop) -> None:
        self._agent_loop = loop


def test_hung_ceiling_wraps_up_when_work_is_in_hand(arelis_window, qt_app) -> None:
    window = arelis_window()
    _short_ceiling(window)
    loop = _GatheredLoop({"scrape"})
    window.orchestrator = _Orch(loop)
    window._set_busy(True)

    QTest.qWait(250)

    assert window._turn_busy
    assert loop.closed
    assert window._hung_closing
    assert window._hung_watchdog.isActive()
    assert window._hung_watchdog.remainingTime() > 5000
    shown = window.chat.view.toPlainText().lower()
    assert "hung" not in shown
    assert "wrapping up" in window.thinking.footer.text().lower()
    assert "wrapping" in window.chat.progress.text().lower()


def test_hung_ceiling_stops_when_nothing_was_gathered(arelis_window, qt_app) -> None:
    window = arelis_window()
    _short_ceiling(window)
    loop = _GatheredLoop()
    window.orchestrator = _Orch(loop)
    window._set_busy(True)

    QTest.qWait(250)

    assert loop.closed is False
    assert window._turn_busy is False
    assert "hung" in window.chat.view.toPlainText().lower()


def test_hung_ceiling_stops_if_the_close_does_not_finish(arelis_window) -> None:
    window = arelis_window()
    window._set_busy(True)
    window._hung_closing = True
    window._on_hung_turn()

    assert window._turn_busy is False
    assert "hung" in window.chat.view.toPlainText().lower()
    assert not window._hung_closing


def test_busy_watchdog_still_unlocks_the_stopped_turn(arelis_window) -> None:
    window = arelis_window()
    window._set_busy(True)
    window._on_stop()
    window._on_busy_watchdog()
    assert window._turn_busy is False
    assert "Turn ended without a reply" in window.chat.view.toPlainText()
