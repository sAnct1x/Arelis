"""Layout A: she lives in the stage, thinking inline in the chat."""

from __future__ import annotations

import time

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QDockWidget

from arelis.core.events import Event, EventType
from arelis.location import UserLocation
from arelis.ui.event_host import dispatch_event

PLACE = UserLocation(
    city="Exampleville",
    region="EX",
    country="US",
    postal_code="62701",
    timezone="America/Example",
    latitude=39.7817,
    longitude=-89.6501,
)


def _plain(window) -> str:
    return window.chat.view.toPlainText()


def _thought_open(window) -> bool:
    text = _plain(window)
    return "because the moon" in text or "checking the tide table" in text


def test_she_is_not_a_dock_and_has_no_toggle(arelis_window, qt_app) -> None:
    """No persona dock, no Ctrl+1, nothing in the saved layout: she lives in the stage."""
    from PySide6.QtGui import QKeySequence

    window = arelis_window()
    window.show()
    qt_app.processEvents()
    names = [item.objectName() for item in window.findChildren(QDockWidget)]
    assert "PersonaDock" not in names and "ThinkingDock" not in names
    assert not hasattr(window, "persona_dock") and not hasattr(window, "act_persona")
    keys = {a.shortcut() for a in window.actions()}
    assert QKeySequence("Ctrl+1") not in keys
    blob = bytes(window.saveState()).decode("latin1").replace("\x00", "")
    assert "PersonaDock" not in blob
    assert window.persona_panel.parentWidget() is window.persona_stage


def test_reasoning_collapses_above_the_answer_and_click_toggles_it(arelis_window, qt_app) -> None:
    """A turn with reasoning shows Thought for above the answer. Click opens and closes it."""
    window = arelis_window()
    window.show()
    qt_app.processEvents()
    window._set_busy(True)
    dispatch_event(
        window,
        Event(EventType.THINKING, {"text": "because the moon pulls", "stream": True}),
    )
    window.chat._thoughts[-1].started = time.monotonic() - 12
    window.chat.append_delta("Tides are the rise and fall of the sea.")
    window._set_busy(False)
    window.chat.finish_assistant("Tides are the rise and fall of the sea.")
    qt_app.processEvents()
    shown = _plain(window)
    assert "Thought for 12s" in shown
    assert "Tides are the rise and fall of the sea." in shown
    assert "because the moon pulls" not in shown
    thought = window.chat._thoughts[-1]
    window.chat._on_anchor(QUrl(f"arelis-act://thought/{thought.id}"))
    qt_app.processEvents()
    opened = _plain(window)
    assert "because the moon pulls" in opened
    assert opened.count("Tides are the rise and fall of the sea.") == 1
    window.chat._on_anchor(QUrl(f"arelis-act://thought/{thought.id}"))
    qt_app.processEvents()
    closed = _plain(window)
    assert "because the moon pulls" not in closed
    assert "Tides are the rise and fall of the sea." in closed
