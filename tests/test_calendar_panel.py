"""Calendar tile: month grid, furniture height, due chips."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from arelis.calendar.models import CachedEvent
from arelis.ui.panels.calendar import (
    CalendarPanel,
    EventSheet,
    TasksPage,
    leftover_label,
    sync_chip_mark,
)
from arelis.ui.theme import METRICS, SPACE, space_box


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


def test_month_overflow_and_sync_marks() -> None:
    assert leftover_label(2) == "+2 more"
    assert sync_chip_mark("pending") == " · queued"
    assert sync_chip_mark("failed") == " · failed"
    assert sync_chip_mark("synced") == ""


def test_event_sheet_notes_are_a_textarea_with_a_date_popup(qt_app) -> None:
    from PySide6.QtWidgets import QPlainTextEdit

    sheet = EventSheet()
    try:
        assert isinstance(sheet.notes_edit, QPlainTextEdit)
        assert sheet.date_edit.calendarPopup() is True
        ev = CachedEvent(
            id="local:1",
            provider="google",
            calendar_id="primary",
            summary="Dentist",
            starts_at=datetime(2026, 8, 19, 10, 0, tzinfo=UTC),
            ends_at=datetime(2026, 8, 19, 11, 0, tzinfo=UTC),
            all_day=False,
            description="bring x-rays",
            raw_id="1",
        )
        sheet.open_event(ev)
        assert sheet.notes_edit.toPlainText() == "bring x-rays"
        captured: list[dict] = []
        sheet.save_requested.connect(captured.append)
        sheet.notes_edit.setPlainText("bring x-rays\nand insurance")
        sheet._on_save()
        assert captured
        assert captured[0]["description"] == "bring x-rays\nand insurance"
    finally:
        sheet.hide()
        sheet.deleteLater()


def test_task_rows_leave_air_around_remove(qt_app) -> None:
    page = TasksPage()
    try:
        page.set_tasks(
            [
                {"id": 1, "title": "live-pass check", "status": "open"},
                {
                    "id": 2,
                    "title": "live-pass check",
                    "due": "2026-08-30",
                    "status": "open",
                },
            ]
        )
        page.resize(720, 400)
        page.show()
        qt_app.processEvents()
        margins = page.layout().contentsMargins()
        assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == space_box(
            "gap"
        )
        assert page.list.spacing() == SPACE["gap"]
        item = page.list.item(0)
        widget = page.list.itemWidget(item)
        assert widget is not None
        row = widget.layout().contentsMargins()
        assert (row.left(), row.top(), row.right(), row.bottom()) == space_box("gap", "micro")
        assert item.sizeHint().height() >= METRICS["row"] + SPACE["micro"] * 2
        first = page.list.visualItemRect(item)
        second = page.list.visualItemRect(page.list.item(1))
        assert second.top() >= first.bottom()
    finally:
        page.hide()
        page.deleteLater()


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
        panel.show_tasks_tab()
        assert panel.tabs.currentWidget() is panel.tasks_page
        panel.show_day(date(2026, 9, 8))
        assert panel.tabs.currentIndex() == 0
        assert panel._anchor == date(2026, 9, 8)
        assert panel._view == "day"
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


