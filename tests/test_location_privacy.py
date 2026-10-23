"""The saved place stays out of the model's prompt and out of visible reasoning."""

from __future__ import annotations

import logging

from arelis.location import UserLocation
from arelis.location.privacy import (
    install,
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


def _dock_window(panel):
    """Enough of a window for the thinking-line branches of dispatch_event."""
    from types import SimpleNamespace

    dock = SimpleNamespace(isHidden=lambda: True)
    action = object()
    return SimpleNamespace(
        thinking=panel,
        think_dock=dock,
        persona_dock=dock,
        act_thinking=action,
        act_persona=action,
        _turn_busy=True,
        _busy_status_line=lambda: "working",
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


def _dock_text(window) -> str:
    window.chat.expand_thinking()
    parts: list[str] = []
    for thought in window.chat._thoughts:
        parts.extend(thought.lines)
        if thought.stream:
            parts.append(thought.stream)
    return "\n".join(parts)


def test_thinking_dock_redacts_status_lines_and_tool_text(qt_app, tmp_path, caplog) -> None:
    """Tool text and streamed reasoning painted in the dock.

    Streamed reasoning is already scrubbed before publish. Tool args and
    results still land whole, with the city swapped. Timing lines such as
    phase=model are logged only, and the city in that log line is swapped too.
    """
    from arelis.core.events import Event, EventType
    from arelis.ui.event_host import dispatch_event
    from arelis.ui.panels.chat import ChatPanel
    from arelis.ui.panels.thinking import ThinkingPanel

    panel = ThinkingPanel()
    chat = ChatPanel()
    window = _dock_window(panel)
    window.chat = chat
    panel.bind(window)
    # The read-back line paints this path. It has to carry the placeholder
    # city or the result branch never shows the thing we are trying to hide.
    missing = tmp_path / "Exampleville" / "notes.md"
    try:
        install({"_location": PLACE})
        with caplog.at_level(logging.INFO, logger="arelis.ui.panels.thinking"):
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
        shown = _dock_text(window).replace("\\", "/")
        assert "Exampleville" not in shown
        assert "phase=model" not in shown
        assert "phase=model near [location]" not in shown
        assert "running [location] digest" in shown
        logged = "\n".join(
            record.getMessage()
            for record in caplog.records
            if record.name == "arelis.ui.panels.thinking"
        )
        assert "phase=model near [location]" in logged
        assert "Exampleville" not in logged
        # A whole term in one stream chunk is the same scrub, in case publish
        # did not already catch it.
        panel.extend_stream("weather in Exampleville")
        streamed = _dock_text(window)
        assert "Exampleville" not in streamed
        assert "weather in [location]" in streamed
        # A different city is not the saved place, so a line that is shown
        # keeps it. The timing line stays in the log, still with that city.
        panel.clear()
        window.chat.clear()
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="arelis.ui.panels.thinking"):
            dispatch_event(
                window,
                Event(EventType.THINKING, {"text": "phase=model near Otherburg"}),
            )
        dispatch_event(
            window,
            Event(EventType.THINKING, {"text": "notes near Otherburg"}),
        )
        other = _dock_text(window)
        other_logged = "\n".join(
            record.getMessage()
            for record in caplog.records
            if record.name == "arelis.ui.panels.thinking"
        )
        assert "phase=model" not in other
        assert "Otherburg" in other
        assert "[location]" not in other
        assert "phase=model near Otherburg" in other_logged
        assert "[location]" not in other_logged

        assert (
            install({"_location": PLACE, "location": {"privacy": {"redact_display": False}}})
            is None
        )
        panel.clear()
        window.chat.clear()
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="arelis.ui.panels.thinking"):
            dispatch_event(
                window,
                Event(EventType.THINKING, {"text": "phase=model near Exampleville"}),
            )
        dispatch_event(
            window,
            Event(EventType.THINKING, {"text": "notes near Exampleville"}),
        )
        opened = _dock_text(window)
        opened_logged = "\n".join(
            record.getMessage()
            for record in caplog.records
            if record.name == "arelis.ui.panels.thinking"
        )
        assert "phase=model" not in opened
        assert "Exampleville" in opened
        assert "phase=model near Exampleville" in opened_logged
    finally:
        install({"location": {"privacy": {"redact_display": False}}})
        chat.deleteLater()
        panel.deleteLater()
