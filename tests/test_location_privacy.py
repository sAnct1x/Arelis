"""The saved place stays out of the model's prompt and out of visible reasoning."""

from __future__ import annotations

import logging

from arelis.core.world_state import world_state_prompt_line
from arelis.location import UserLocation
from arelis.location.privacy import (
    LocationLogFilter,
    LocationRedactor,
    StreamRedactor,
    install,
    prompt_detail,
)

PLACE = UserLocation(
    city="Exampleville",
    region="EX",
    country="US",
    postal_code="62701",
    timezone="America/Example",
)


def test_prompt_line_hides_the_place_by_default() -> None:
    line = PLACE.prompt_line("off") or ""
    assert "Exampleville" not in line
    assert "62701" not in line
    assert "America/Example" in line
    assert "user_location" in line
    # city keeps the city but never the postal code; full is the old line.
    city = PLACE.prompt_line("city") or ""
    assert "Exampleville" in city and "62701" not in city
    assert "62701" in (PLACE.prompt_line() or "")


def test_prompt_detail_defaults_off_and_world_state_follows() -> None:
    assert prompt_detail({}) == "off"
    assert prompt_detail({"location": {"privacy": {"prompt_detail": "bogus"}}}) == "off"
    off = world_state_prompt_line({"_location": PLACE}, role="fast", model="m")
    assert "Exampleville" not in off
    full_cfg = {"_location": PLACE, "location": {"privacy": {"prompt_detail": "full"}}}
    full = world_state_prompt_line(full_cfg, role="fast", model="m")
    assert "place Exampleville, EX 62701, US" in full


def test_stream_redactor_catches_a_city_split_across_chunks() -> None:
    redactor = LocationRedactor(lambda: PLACE)
    stream = StreamRedactor(redactor)
    chunks = ["Weather in Exam", "pleville for 62", "701 today, ", "then Exam"]
    out = "".join(stream.feed(c) for c in chunks) + stream.flush()
    assert out == "Weather in [location] for [location] today, then Exam"


def test_log_filter_scrubs_records_and_install_can_switch_off() -> None:
    install({"_location": PLACE})
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "near %s", ("Exampleville",), None)
    assert LocationLogFilter().filter(record)
    assert record.getMessage() == "near [location]"
    assert install({"_location": PLACE, "location": {"privacy": {"redact_display": False}}}) is None
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "near Exampleville", None, None)
    LocationLogFilter().filter(record)
    assert record.getMessage() == "near Exampleville"


def _dock_window(panel):
    """Enough of a window for the Thinking-dock branches of dispatch_event."""
    from types import SimpleNamespace

    return SimpleNamespace(
        thinking=panel,
        think_dock=object(),
        act_thinking=object(),
        _turn_busy=False,
        _mobile_foreign=False,
        _workspace_tool_args={},
        _reveal_dock=lambda *_a, **_k: None,
        chat=SimpleNamespace(
            show_progress=lambda *_a, **_k: None,
            add_system=lambda *_a, **_k: None,
        ),
        conversation=SimpleNamespace(set_turn_visible=lambda *_a, **_k: None),
        workspace=SimpleNamespace(append_output=lambda *_a, **_k: None),
    )


def _dock_text(panel) -> str:
    return f"{panel.view.toPlainText()}\n{panel.footer.text()}"


def test_thinking_dock_redacts_status_lines_and_tool_text(qt_app, tmp_path) -> None:
    """Plain THINKING lines and tool args/results painted in the dock.

    Streamed reasoning is already scrubbed before publish. These three
    strings are the ones that still landed whole, with the city in them.
    """
    from arelis.core.events import Event, EventType
    from arelis.ui.event_host import dispatch_event
    from arelis.ui.panels.thinking import ThinkingPanel

    panel = ThinkingPanel()
    window = _dock_window(panel)
    # The read-back line paints this path. It has to carry the placeholder
    # city or the result branch never shows the thing we are trying to hide.
    missing = tmp_path / "Exampleville" / "notes.md"
    try:
        install({"_location": PLACE})
        dispatch_event(
            window,
            Event(EventType.THINKING, {"text": "phase=model near Exampleville"}),
        )
        dispatch_event(
            window,
            Event(
                EventType.TOOL_START,
                {
                    "tool": "run_task",
                    "args": {"action": "run", "name": "Exampleville digest"},
                },
            ),
        )
        dispatch_event(
            window,
            Event(
                EventType.TOOL_RESULT,
                {
                    "tool": "workspace",
                    "ok": True,
                    "output": "Wrote notes in Exampleville",
                    "args": {"action": "write", "path": "Exampleville/notes.md"},
                    "data": {
                        "path": "Exampleville/notes.md",
                        "abs_path": str(missing),
                    },
                },
            ),
        )
        shown = _dock_text(panel)
        assert "Exampleville" not in shown
        assert "phase=model near [location]" in shown
        assert "running [location] digest" in shown
        assert "[location]/notes.md" in shown
        # A whole term in one stream chunk is the same scrub, in case publish
        # did not already catch it.
        panel.extend_stream("weather in Exampleville")
        assert "Exampleville" not in panel.view.toPlainText()
        assert "weather in [location]" in panel.view.toPlainText()
        # A different city is not the saved place, so it stays.
        panel.clear()
        dispatch_event(
            window,
            Event(EventType.THINKING, {"text": "phase=model near Otherburg"}),
        )
        assert "Otherburg" in panel.view.toPlainText()
        assert "[location]" not in panel.view.toPlainText()

        assert (
            install({"_location": PLACE, "location": {"privacy": {"redact_display": False}}})
            is None
        )
        panel.clear()
        dispatch_event(
            window,
            Event(EventType.THINKING, {"text": "phase=model near Exampleville"}),
        )
        assert "Exampleville" in panel.view.toPlainText()
    finally:
        install({"location": {"privacy": {"redact_display": False}}})
        panel.deleteLater()
