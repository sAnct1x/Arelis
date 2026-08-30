"""History lamp follows the click; same-list refresh does not rebuild."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from PySide6.QtCore import Qt

from arelis.ui.panels.history import HistoryPanel, _format_when


def _row(sid: str, title: str, started_at: str) -> dict[str, str]:
    return {"id": sid, "title": title, "started_at": started_at}


def test_click_moves_the_lamp(qt_app) -> None:
    panel = HistoryPanel()
    panel.set_sessions(
        [
            _row("a", "first", "2026-08-29T00:00:00+00:00"),
            _row("b", "second", "2026-08-28T00:00:00+00:00"),
        ]
    )
    panel.set_active("a")
    assert panel.list.currentItem().data(Qt.ItemDataRole.UserRole) == "a"

    fired: list[str] = []
    panel.session_selected.connect(fired.append)
    panel._on_activated(panel.list.item(1))
    assert panel._active_id == "b"
    assert panel.list.currentItem().data(Qt.ItemDataRole.UserRole) == "b"
    assert fired == ["b"]
    panel.deleteLater()


def test_same_list_refresh_keeps_the_rows(qt_app) -> None:
    panel = HistoryPanel()
    sessions = [
        _row("a", "first", "2026-08-29T00:00:00+00:00"),
        _row("b", "second", "2026-08-28T00:00:00+00:00"),
    ]
    panel.set_sessions(sessions)
    panel.set_active("a")
    first = panel.list.item(0)
    panel.set_sessions(list(sessions))
    assert panel.list.item(0) is first
    assert panel.list.currentItem() is first
    panel.deleteLater()


def test_recent_dates_read_as_today_and_yesterday() -> None:
    now = datetime.now(UTC)
    assert _format_when(now.isoformat()) == "today"
    assert _format_when((now - timedelta(days=1)).isoformat()) == "yesterday"
    assert _format_when("") == "no date"
