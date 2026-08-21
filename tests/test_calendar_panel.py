"""Calendar tile: month grid, furniture height, due chips."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from arelis.calendar.layout import event_spans_day, month_cells, parse_task_due
from arelis.calendar.models import CachedEvent
from arelis.ui.panels.calendar import CalendarPanel
from arelis.ui.theme import METRICS


def _ev(day: date, *, summary: str = "Dentist", hour: int = 10) -> CachedEvent:
    start = datetime(day.year, day.month, day.day, hour, 0, tzinfo=UTC)
    return CachedEvent(
        id="google:den",
        provider="google",
        calendar_id="primary",
        summary=summary,
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        all_day=False,
        raw_id="den",
    )


def test_month_cells_are_six_weeks() -> None:
    cells = month_cells(2026, 8)
    assert len(cells) == 42
    assert cells[0].weekday() == 6  # Sunday lead, matching Google US


def test_all_day_end_is_exclusive() -> None:
    start = datetime(2026, 8, 19, tzinfo=UTC)
    ev = CachedEvent(
        id="google:ad",
        provider="google",
        calendar_id="primary",
        summary="Away",
        starts_at=start,
        ends_at=start + timedelta(days=1),
        all_day=True,
        raw_id="ad",
    )
    assert event_spans_day(ev, date(2026, 8, 19))
    assert not event_spans_day(ev, date(2026, 8, 20))


def test_parse_task_due_iso() -> None:
    assert parse_task_due("2026-08-19") == date(2026, 8, 19)
    assert parse_task_due("Friday") is None


def test_calendar_furniture_is_one_height(qt_app) -> None:
    panel = CalendarPanel()
    try:
        row = METRICS["row"]
        for widget in (
            panel.prev_btn,
            panel.today_btn,
            panel.next_btn,
            panel.sync_btn,
            panel.new_btn,
            panel.tasks_page.add_btn,
            panel.jobs_page.save_btn,
            panel.jobs_page.new_btn,
        ):
            assert widget.minimumHeight() == row, widget.objectName()
            assert widget.maximumHeight() == row, widget.objectName()
    finally:
        panel.deleteLater()


def test_month_grid_paints_an_event(qt_app) -> None:
    panel = CalendarPanel()
    try:
        day = date(2026, 8, 19)
        panel._anchor = day
        panel.month_view.set_anchor(day)
        panel.set_events([_ev(day)])
        panel.month_view.resize(900, 640)
        from PySide6.QtGui import QPaintEvent

        panel.month_view.paintEvent(QPaintEvent(panel.month_view.rect()))
        kinds = [hit.kind for hit in panel.month_view._hits]
        assert "event" in kinds
        assert "cell" in kinds
        titles = [
            hit.payload.summary
            for hit in panel.month_view._hits
            if hit.kind == "event"
        ]
        assert "Dentist" in titles
    finally:
        panel.hide()
        panel.deleteLater()


def test_due_task_chip_lands_on_the_day(qt_app) -> None:
    panel = CalendarPanel()
    try:
        day = date(2026, 8, 19)
        panel._anchor = day
        panel.month_view.set_anchor(day)
        panel._tasks = [{"id": 1, "title": "Call Robin", "due": "2026-08-19", "status": "open"}]
        panel._events = []
        panel._paint()
        panel.month_view.resize(900, 640)
        from PySide6.QtGui import QPaintEvent

        panel.month_view.paintEvent(QPaintEvent(panel.month_view.rect()))
        chips = [hit for hit in panel.month_view._hits if hit.kind == "task"]
        assert chips
        assert chips[0].payload["title"] == "Call Robin"
    finally:
        panel.hide()
        panel.deleteLater()


def test_calendar_opens_as_a_chrome_sized_window(arelis_window, qt_app) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDockWidget

    from arelis.ui.glass import GlassFrame
    from arelis.ui.panels.calendar import CHROME_TILE_SIZE

    window = arelis_window()
    win = window.calendar_window
    assert win.isHidden()
    window._toggle_calendar(True)
    assert not win.isHidden()
    assert win.width() >= CHROME_TILE_SIZE[0]
    assert win.height() >= CHROME_TILE_SIZE[1]
    assert not isinstance(win, QDockWidget)
    named = [
        dock
        for dock in window.findChildren(QDockWidget)
        if dock.objectName() == "CalendarDock"
    ]
    assert named == []
    assert not win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    plates = win.findChildren(GlassFrame)
    assert plates and plates[0]._round_cutout

    window._toggle_calendar(False)
    assert win.isHidden()
    window._toggle_calendar(True)
    assert not win.isHidden()


def test_calendar_close_unchecks_view_action(arelis_window, qt_app) -> None:
    window = arelis_window()
    window._toggle_calendar(True)
    window._sync_view_checks()
    assert window.act_calendar.isChecked()
    window.calendar_window.close()
    qt_app.processEvents()
    assert window.calendar_window.isHidden()
    assert not window.act_calendar.isChecked()


def test_agenda_open_tool_result_shows_the_calendar_window(
    arelis_window, qt_app
) -> None:
    from arelis.core.events import Event, EventType

    window = arelis_window()
    assert window.calendar_window.isHidden()
    window._on_event(
        Event(
            EventType.TOOL_RESULT,
            {
                "tool": "agenda",
                "ok": True,
                "output": "Opened the Arelis calendar.",
                "data": {"open": True},
            },
        )
    )
    qt_app.processEvents()
    assert not window.calendar_window.isHidden()
    assert window.act_calendar.isChecked()


def test_agenda_close_tool_result_hides_the_calendar_window(
    arelis_window, qt_app
) -> None:
    from arelis.core.events import Event, EventType

    window = arelis_window()
    window._toggle_calendar(True)
    qt_app.processEvents()
    assert not window.calendar_window.isHidden()
    window._on_event(
        Event(
            EventType.TOOL_RESULT,
            {
                "tool": "agenda",
                "ok": True,
                "output": "Closed the Arelis calendar.",
                "data": {"close": True},
            },
        )
    )
    qt_app.processEvents()
    assert window.calendar_window.isHidden()
    assert not window.act_calendar.isChecked()


def test_jobs_tab_lists_a_saved_job(qt_app, tmp_path, monkeypatch) -> None:
    from arelis.jobs import store as store_mod
    from arelis.jobs.store import Job, upsert_job

    path = tmp_path / "jobs.yaml"
    monkeypatch.setattr(store_mod, "JOBS_PATH", path)
    upsert_job(
        Job(
            id="morning-weather-email",
            name="Morning weather email",
            prompt="Weather for Springfield IL and Metropolis IL.",
            times=["09:00"],
            recipient="you@example.com",
        )
    )
    panel = CalendarPanel()
    try:
        panel.reload_jobs()
        panel.show_jobs_tab()
        assert panel.tabs.currentWidget() is panel.jobs_page
        assert panel.tabs.widget(1) is panel.tasks_page
        assert panel.tabs.widget(2) is panel.jobs_page
        assert panel.jobs_page.list.count() == 1
        assert "Morning weather email" in panel.jobs_page.list.item(0).text()
        assert panel.jobs_page.current_id() == "morning-weather-email"
        assert "you@example.com" in panel.jobs_page.recipient_edit.text()
    finally:
        panel.hide()
        panel.deleteLater()


def test_schedule_tool_result_opens_the_jobs_tab(arelis_window, qt_app) -> None:
    from arelis.core.events import Event, EventType

    window = arelis_window()
    assert window.calendar_window.isHidden()
    window._on_event(
        Event(
            EventType.TOOL_RESULT,
            {
                "tool": "schedule",
                "ok": True,
                "output": "Scheduled 'Morning weather email'",
                "data": {"id": "morning-weather-email", "registered": True},
            },
        )
    )
    qt_app.processEvents()
    assert not window.calendar_window.isHidden()
    assert window.act_calendar.isChecked()
    assert window.calendar.tabs.currentWidget() is window.calendar.jobs_page


def test_hung_calendar_sync_clears_inflight(arelis_window, qt_app) -> None:
    from PySide6.QtTest import QTest

    window = arelis_window()
    window._toggle_calendar(True)
    window._calendar_sync_timeout_ms = 50
    window._calendar_sync_inflight = True
    window.calendar.set_status("syncing…")
    window._calendar_sync_watchdog.start(50)
    QTest.qWait(120)
    assert window._calendar_sync_inflight is False
    assert window.calendar.status.text() == "sync failed"
    assert "syncing" not in window.calendar.status.text().lower()


def test_opening_a_dock_does_not_leave_an_opacity_effect(arelis_window) -> None:
    window = arelis_window()
    window._toggle_thinking(True)
    assert window.think_dock.graphicsEffect() is None
    shell = window.think_dock.widget()
    assert shell is None or shell.graphicsEffect() is None
    assert window.conversation.graphicsEffect() is None
