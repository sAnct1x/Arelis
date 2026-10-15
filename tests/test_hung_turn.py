"""Phase 6.1: a turn that never gets Stop still unlocks when it hangs.

The 8s busy watchdog only arms after Stop. These drive `_set_busy` /
`_on_stop` on a real window so a helper-only countdown cannot hide a miss.
"""

from __future__ import annotations

from PySide6.QtTest import QTest


def _status_line(window) -> str:
    """Status the operator can see: her caption, the progress line, or a thought."""
    panel = getattr(window, "persona_panel", None)
    caption = panel.status_text() if panel is not None else ""
    lines = [caption, window.chat.progress.text()]
    for thought in getattr(window.chat, "_thoughts", ()):
        lines.extend(thought.lines)
    return "\n".join(lines)


def _short_ceiling(window, seconds: float = 0.08) -> None:
    ui = window.config.setdefault("ui", {})
    ui["hung_turn_s"] = seconds
    ui["hung_first_token_s"] = seconds


def test_hung_ceiling_unlocks_without_stop(arelis_window, qt_app) -> None:
    window = arelis_window()
    _short_ceiling(window)
    window._set_busy(True)
    assert window._turn_busy
    assert window._hung_watchdog.isActive()
    assert "left" not in window.chat.progress.text()
    assert "Thinking for" in window.chat.view.toPlainText()
    assert window.chat.progress.isHidden()

    QTest.qWait(250)

    assert window._turn_busy is False
    assert not window.conversation._busy
    assert window.chat.progress.isHidden()
    shown = window.chat.view.toPlainText()
    assert "hung" in shown.lower()
    assert "stop requested" not in shown.lower()
    assert "stop requested" not in _status_line(window).lower()
    assert "hung" in _status_line(window).lower()
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
    assert "stop requested" in _status_line(window)

    QTest.qWait(350)

    assert window._turn_busy
    shown = window.chat.view.toPlainText()
    assert "hung" not in shown.lower()
    assert "stop requested" in _status_line(window)


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


