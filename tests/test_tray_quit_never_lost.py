"""A tray Quit is never lost: not to a dropped close event, nor to a refused app.quit()."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QApplication


def _record_exit(monkeypatch) -> list[str]:
    calls: list[str] = []
    app = QApplication.instance()
    monkeypatch.setattr(app, "exit", lambda code=0: calls.append(f"exit {code}"))
    monkeypatch.setattr(app, "quit", lambda: calls.append("quit"))
    return calls


def test_quit_tears_down_even_when_the_close_event_never_comes(
    arelis_window, monkeypatch, caplog
) -> None:
    """Qt dropping the close event (Atria 534pr7 Q5) no longer leaves the app running."""
    window = arelis_window()
    _record_exit(monkeypatch)
    monkeypatch.setattr(window, "close", lambda: False)
    with caplog.at_level(logging.INFO, logger="arelis.ui.window_lifetime"):
        window.quit_from_tray()
    assert "quit_begin force=True" in caplog.text


def test_quit_leaves_the_loop_with_exit_which_no_window_can_refuse(
    arelis_window, monkeypatch
) -> None:
    window = arelis_window()
    calls = _record_exit(monkeypatch)
    window.quit_from_tray()
    assert calls == ["exit 0"]
