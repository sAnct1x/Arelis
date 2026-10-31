"""Layout A: her face in the right dock, thinking inline in the chat."""

from __future__ import annotations

import time

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtWidgets import QDockWidget, QMainWindow, QWidget

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


def test_her_dock_sits_on_the_right(arelis_window, qt_app) -> None:
    """The right dock is her face, about 370 px wide, and Thinking is gone."""
    window = arelis_window()
    window.resize(1440, 900)
    window.show()
    qt_app.processEvents()
    dock = window.persona_dock
    assert dock.objectName() == "PersonaDock"
    assert window.dockWidgetArea(dock) == Qt.DockWidgetArea.RightDockWidgetArea
    assert 330 <= dock.width() <= 420
    names = [item.objectName() for item in window.findChildren(QDockWidget)]
    assert "ThinkingDock" not in names
    assert window.act_persona.text() == "arelis"
    assert window.act_persona.shortcut().toString() == "Ctrl+1"


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


def _save_old_layout(qt_app, ini: str, mode: str) -> None:
    host = QMainWindow()
    host.setCentralWidget(QWidget())
    host.resize(1440, 900)
    made = {}
    for name, area in (
        ("ThinkingDock", Qt.DockWidgetArea.RightDockWidgetArea),
        ("WorkspaceDock", Qt.DockWidgetArea.BottomDockWidgetArea),
        ("HistoryDock", Qt.DockWidgetArea.LeftDockWidgetArea),
        ("CameraDock", Qt.DockWidgetArea.LeftDockWidgetArea),
    ):
        dock = QDockWidget(host)
        dock.setObjectName(name)
        body = QWidget()
        body.setMinimumSize(220, 160)
        dock.setWidget(body)
        host.addDockWidget(area, dock)
        made[name] = dock
    thinking = made["ThinkingDock"]
    if mode == "hidden":
        thinking.hide()
    elif mode == "floating":
        thinking.setFloating(True)
        thinking.resize(400, 500)
    elif mode == "bottom":
        host.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, thinking)
    host.show()
    qt_app.processEvents()
    store = QSettings(ini, QSettings.Format.IniFormat)
    store.setValue("geometry", host.saveGeometry())
    store.setValue("state", host.saveState())
    store.setValue("size", host.size())
    store.sync()
    blob = bytes(host.saveState())
    assert "ThinkingDock" in blob.decode("latin1").replace("\x00", "")
    host.close()
    host.deleteLater()
    qt_app.processEvents()
