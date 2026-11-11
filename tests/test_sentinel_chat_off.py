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
    # #594 hides and disables chat; submit and the wake word follow the same
    # _overseer_chat_suspend marker.
    monkeypatch.setattr(sentinel_control, "overseer_url", lambda: "")
    owner = _Owner()
    owner.resize(1280, 800)
    owner.conversation = QWidget(owner)
    owner.voice_controller = _Voice()
    owner._filament_chat_tile = QWidget()
    owner._filament_chat_tile.show()
    owner._filament_chat_open = True
    win = SentinelWindow(owner)
    owner.sentinel_window = win
    try:
        win.show()
        qt_app.processEvents()
        assert owner._overseer_chat_suspend is not None
        assert owner.conversation.isEnabled() is False
        assert owner._filament_chat_tile.isVisible() is False
        assert owner.voice_controller.calls == ["stop_all"]
        # Composer, Again and camera all submit through here: nothing starts.
        owner._on_submit("hello", "chat")

        win.close()
        qt_app.processEvents()
        assert owner._overseer_chat_suspend is None
        assert owner.conversation.isEnabled() is True
        assert owner.voice_controller.calls == ["stop_all", "resume_wake"]
    finally:
        teardown_sentinel_window(owner)
        owner._filament_chat_tile.close()
        owner.deleteLater()
        qt_app.processEvents()


def test_a_refresh_error_keeps_chat_off_while_the_overseer_stays_open(
    qt_app, monkeypatch
) -> None:
    # _refresh used to call _restore_presence("error") which turned chat and
    # the wake word back on while the error card was still on screen.
    monkeypatch.setattr(sentinel_control, "overseer_url", lambda: "")
    owner = _Owner()
    owner.resize(1280, 800)
    owner.conversation = QWidget(owner)
    owner.voice_controller = _Voice()
    win = SentinelWindow(owner)
    owner.sentinel_window = win
    try:
        win.show()
        qt_app.processEvents()
        assert win.isVisible() is True
        assert owner._overseer_chat_suspend is not None
        assert owner.conversation.isEnabled() is False
        assert owner.voice_controller.calls == ["stop_all"]

        monkeypatch.setattr(sentinel_control, "overseer_url", lambda: "http://127.0.0.1:9/")
        monkeypatch.setattr(win, "_ensure_view", lambda: None)
        win.refresh()
        qt_app.processEvents()

        assert win.isVisible() is True
        assert owner._overseer_chat_suspend is not None
        assert owner.conversation.isEnabled() is False
        assert owner.voice_controller.calls == ["stop_all"]
        owner._on_submit("hello", "chat")
    finally:
        teardown_sentinel_window(owner)
        owner.deleteLater()
        qt_app.processEvents()
