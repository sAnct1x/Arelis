"""Thinking dock: model thought is one wrapping paragraph, not a word per line."""

from __future__ import annotations

import asyncio

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.ui.panels.thinking import ThinkingPanel


def test_streamed_think_tokens_join_into_prose(qt_app) -> None:
    panel = ThinkingPanel()
    panel.append("round 0/8  model step", kind="trace")
    panel.extend_stream("I")
    panel.extend_stream(" love")
    panel.extend_stream(" you.")
    panel.append("Listening again.", kind="status")
    text = panel.view.toPlainText()
    assert "trace  round 0/8  model step" in text
    assert "think  I love you." in text
    assert "status  Listening again." in text
    assert "trace  I" not in text
    panel.deleteLater()


def test_window_stream_flag_uses_think_paragraph(qt_app) -> None:
    from arelis.ui.app import ArelisWindow, BusBridge

    window = ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
    )
    try:
        window._on_event(Event(EventType.THINKING, {"text": "round 1/8  model step"}))
        window._on_event(Event(EventType.THINKING, {"text": "The", "stream": True}))
        window._on_event(Event(EventType.THINKING, {"text": " user", "stream": True}))
        window._on_event(
            Event(EventType.THINKING, {"text": " asked about mail.", "stream": True})
        )
        text = window.thinking.view.toPlainText()
        assert "trace  round 1/8  model step" in text
        assert "think  The user asked about mail." in text
    finally:
        window.hide()
        window.loop.close()
