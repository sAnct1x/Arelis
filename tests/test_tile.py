"""Open and close every View-menu tile from speech."""

from __future__ import annotations

import pytest

from arelis.core.events import Event, EventType
from arelis.core.plan_nudge import select_plan
from arelis.core.preflight import detect_intents
from arelis.core.skills import select_skill_ids
from arelis.core.tile_complete import match_tile_intent, tile_tool_args
from arelis.tools.tile import TileTool


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("open my notifications", ("open", "notifications")),
        ("close my notifications", ("close", "notifications")),
        ("open history", ("open", "history")),
        ("close history", ("close", "history")),
        ("open the workspace", ("open", "workspace")),
        ("close the workspace", ("close", "workspace")),
        ("open thinking", ("open", "thinking")),
        ("close thinking", ("close", "thinking")),
        ("open the camera", ("open", "camera")),
        ("close the camera", ("close", "camera")),
        ("open contacts", ("open", "contacts")),
        ("close contacts", ("close", "contacts")),
        ("open world", ("open", "world")),
        ("open the world", ("open", "world")),
        ("close world", ("close", "world")),
        ("open the solar lab", ("open", "world")),
        ("pull up notifications", ("open", "notifications")),
        ("hide the alerts", ("close", "notifications")),
        ("close them", ("close", "")),
        ("hide it", ("close", "")),
    ],
)
def test_tile_phrases_match(text: str, want: tuple[str, str]) -> None:
    assert match_tile_intent(text) == want


@pytest.mark.parametrize(
    "text",
    [
        "open youtube",
        "open that file",
        "close the file",
        "close the room",
        "git history",
        "open calendar.google.com",
        "open my calendar in chrome",
        "What's on my calendar?",
        "show me my calendar for today",
        "close the calendar event",
        "open settings",
    ],
)
def test_tile_phrases_do_not_steal_other_intents(text: str) -> None:
    assert match_tile_intent(text) is None


def test_open_my_calendar_is_still_a_tile_fallback() -> None:
    """Agenda handles this when Google is connected; tile is the local window."""
    assert match_tile_intent("open my calendar") == ("open", "calendar")
    assert match_tile_intent("close my calendar") == ("close", "calendar")


def test_close_them_reuses_the_last_tile() -> None:
    TileTool.last_name = "notifications"
    try:
        assert tile_tool_args("close them", last_name=TileTool.last_name) == {
            "action": "close",
            "name": "notifications",
        }
    finally:
        TileTool.last_name = ""


@pytest.mark.asyncio
async def test_tile_tool_open_and_close() -> None:
    TileTool.last_name = ""
    tool = TileTool()
    opened = await tool.run(action="open", name="history")
    assert opened.ok
    assert opened.data == {"open": True, "close": False, "name": "history"}
    assert TileTool.last_name == "history"
    closed = await tool.run(action="close")
    assert closed.ok
    assert closed.data["close"] is True
    assert closed.data["name"] == "history"


def test_notifications_preflight_and_plan() -> None:
    hints = detect_intents("open my notifications")
    assert any(h.kind == "tile_open" for h in hints)
    assert not any(h.kind == "browser" for h in hints)
    kinds = [h.kind for h in hints]
    plan = select_plan("open my notifications", preflight_kinds=kinds)
    assert plan is not None
    assert plan.id == "tile"
    assert "tile" in select_skill_ids(
        "open my notifications", available_tools={"tile", "browser", "agenda"}
    )


def test_notifications_subset_offers_tile() -> None:
    from arelis.core.tool_subset import filter_tool_names

    visible = filter_tool_names(
        {"tile", "browser", "agenda", "calculator", "cas", "units"},
        role="fast",
        text="open my notifications",
        enabled=True,
        skill_subset=True,
    )
    assert "tile" in visible


def test_open_world_is_a_tile_intent() -> None:
    hints = detect_intents("open world")
    assert any(h.kind == "tile_open" for h in hints)
    assert "tile" in select_skill_ids(
        "open world", available_tools={"tile", "browser", "rooms"}
    )
    assert tile_tool_args("open world") == {"action": "open", "name": "world"}


def test_calendar_open_is_still_agenda_not_tile_preflight() -> None:
    hints = detect_intents("open my calendar")
    assert any(h.kind == "agenda_open" for h in hints)
    assert not any(h.kind == "tile_open" for h in hints)
    assert not any(h.kind == "browser" for h in hints)


def test_tile_tool_result_opens_and_closes_history(arelis_window, qt_app) -> None:
    window = arelis_window()
    window.history_dock.hide()
    qt_app.processEvents()
    window._on_event(
        Event(
            EventType.TOOL_RESULT,
            {
                "tool": "tile",
                "ok": True,
                "output": "Opened history.",
                "data": {"open": True, "close": False, "name": "history"},
            },
        )
    )
    qt_app.processEvents()
    assert not window.history_dock.isHidden()
    assert window.act_history.isChecked()
    window._on_event(
        Event(
            EventType.TOOL_RESULT,
            {
                "tool": "tile",
                "ok": True,
                "output": "Closed history.",
                "data": {"open": False, "close": True, "name": "history"},
            },
        )
    )
    qt_app.processEvents()
    assert window.history_dock.isHidden()
    assert not window.act_history.isChecked()


def test_tile_tool_result_opens_and_closes_notifications(
    arelis_window, qt_app
) -> None:
    window = arelis_window()
    window.notify_inbox.hide()
    qt_app.processEvents()
    window._on_event(
        Event(
            EventType.TOOL_RESULT,
            {
                "tool": "tile",
                "ok": True,
                "output": "Opened notifications.",
                "data": {"open": True, "close": False, "name": "notifications"},
            },
        )
    )
    qt_app.processEvents()
    assert not window.notify_inbox.isHidden()
    window._on_event(
        Event(
            EventType.TOOL_RESULT,
            {
                "tool": "tile",
                "ok": True,
                "output": "Closed notifications.",
                "data": {"open": False, "close": True, "name": "notifications"},
            },
        )
    )
    qt_app.processEvents()
    assert window.notify_inbox.isHidden()


def test_tile_tool_result_opens_world_in_physics(arelis_window, qt_app) -> None:
    window = arelis_window()
    window._on_event(
        Event(
            EventType.ROOM_CHANGED,
            {"room_id": "physics", "name": "Physics"},
        )
    )
    qt_app.processEvents()
    window._on_event(
        Event(
            EventType.TOOL_RESULT,
            {
                "tool": "tile",
                "ok": True,
                "output": "Opened world.",
                "data": {"open": True, "close": False, "name": "world"},
            },
        )
    )
    qt_app.processEvents()
    assert not window.world_window.isHidden()
    assert window.act_world.isChecked()
    window._on_event(
        Event(
            EventType.TOOL_RESULT,
            {
                "tool": "tile",
                "ok": True,
                "output": "Closed world.",
                "data": {"open": False, "close": True, "name": "world"},
            },
        )
    )
    qt_app.processEvents()
    assert window.world_window.isHidden()
    assert not window.act_world.isChecked()


def test_tile_tool_result_does_not_open_world_in_orbit(arelis_window, qt_app) -> None:
    window = arelis_window()
    window._on_event(
        Event(
            EventType.TOOL_RESULT,
            {
                "tool": "tile",
                "ok": True,
                "output": "Opened world.",
                "data": {"open": True, "close": False, "name": "world"},
            },
        )
    )
    qt_app.processEvents()
    assert window.world_window.isHidden()
    assert not window.act_world.isChecked()
