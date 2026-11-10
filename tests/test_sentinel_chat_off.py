"""Chat is off while the Overseer is open, and back on when it closes."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from arelis import sentinel_control
from arelis.ui.sentinel_host import SentinelWindow, teardown_sentinel_window
from arelis.ui.window_turn import WindowTurn


class _Voice:
    def __init__(self) -> None:
        self._wake_suspended = False
        self.calls: list[str] = []

    def stop_all(self) -> None:
        self._wake_suspended = True
        self.calls.append("stop_all")

    def resume_wake(self) -> None:
        self._wake_suspended = False
        self.calls.append("resume_wake")


class _Owner(WindowTurn, QWidget):
    pass


def test_opening_the_overseer_turns_chat_off_and_closing_restores_it(qt_app, monkeypatch) -> None:
    # The Sentinel window is its own top-level window over this one, so its
    # open path used to fade her and leave composer, mic and turn running.
    monkeypatch.setattr(sentinel_control, "overseer_url", lambda: "")
    owner = _Owner()
    owner.resize(1280, 800)
    owner.conversation = QWidget(owner)
    owner.voice_controller = _Voice()
    owner._filament_chat_tile = QWidget()
    owner._filament_chat_tile.show()
    owner._filament_chat_open = True
    owner._turn_busy = True
    cancelled: list[bool] = []
    owner._cancel_turn = lambda *, schedule_next, reason="stop": cancelled.append(schedule_next)
    win = SentinelWindow(owner)
    owner.sentinel_window = win
    try:
        win.show()
        qt_app.processEvents()
        assert owner.conversation.isEnabled() is False
        assert owner._filament_chat_tile.isVisible() is False
        assert owner.voice_controller.calls == ["stop_all"]
        assert cancelled == [False]
        # Composer, Again and camera all submit through here: nothing starts.
        owner._on_submit("hello", "chat")

        win.close()
        qt_app.processEvents()
        assert owner.conversation.isEnabled() is True
        assert owner._filament_chat_tile.isVisible() is True
        assert owner.voice_controller.calls == ["stop_all", "resume_wake"]
    finally:
        teardown_sentinel_window(owner)
        owner._filament_chat_tile.close()
        owner.deleteLater()
        qt_app.processEvents()
