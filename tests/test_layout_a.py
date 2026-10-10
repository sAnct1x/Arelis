"""Layout A: her face in the right dock, thinking inline in the chat."""

from __future__ import annotations

import time

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtWidgets import QDockWidget, QMainWindow, QWidget

from arelis.core.events import Event, EventType
from arelis.location import UserLocation
from arelis.location.privacy import install
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


def test_a_turn_reveals_her_and_a_hand_close_sticks(arelis_window, qt_app) -> None:
    """A turn opens her dock. Closing it by hand keeps it closed until Ctrl+1."""
    window = arelis_window()
    window.show()
    qt_app.processEvents()
    assert not window.persona_dock.isHidden()
    dispatch_event(window, Event(EventType.THINKING, {"text": "the moon pulls the water"}))
    qt_app.processEvents()
    assert not window.persona_dock.isHidden()
    window.persona_dock.close()
    qt_app.processEvents()
    assert window.persona_dock.isHidden()
    dispatch_event(window, Event(EventType.THINKING, {"text": "still pulling"}))
    qt_app.processEvents()
    assert window.persona_dock.isHidden()
    window.act_persona.trigger()
    qt_app.processEvents()
    assert not window.persona_dock.isHidden()
    dispatch_event(window, Event(EventType.THINKING, {"text": "open again"}))
    window.persona_dock.close()
    qt_app.processEvents()
    window.act_persona.trigger()
    qt_app.processEvents()
    dispatch_event(window, Event(EventType.TOOL_START, {"tool": "weather", "args": {}}))
    qt_app.processEvents()
    assert not window.persona_dock.isHidden()


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


def test_an_older_thought_can_toggle_while_a_new_answer_streams(arelis_window, qt_app) -> None:
    """Opening an older turn does not eat the answer that is still streaming."""
    window = arelis_window()
    window.show()
    qt_app.processEvents()
    window._set_busy(True)
    dispatch_event(window, Event(EventType.THINKING, {"text": "because the moon pulls"}))
    window.chat.append_delta("Tides are the rise and fall of the sea.")
    window._set_busy(False)
    window.chat.finish_assistant("Tides are the rise and fall of the sea.")
    window.chat.add_user("shorter please")
    window._set_busy(True)
    window.chat.append_delta("Short version: the moon tugs the ocean.")
    older = window.chat._thoughts[0]
    window.chat._on_anchor(QUrl(f"arelis-act://thought/{older.id}"))
    window.chat._on_anchor(QUrl(f"arelis-act://thought/{older.id}"))
    window.chat.append_delta(" That is the whole idea.")
    qt_app.processEvents()
    shown = _plain(window)
    assert "Tides are the rise and fall of the sea." in shown
    assert "Short version: the moon tugs the ocean. That is the whole idea." in shown
    assert "because the moon pulls" not in shown


def test_the_status_line_opens_the_current_thought(arelis_window, qt_app) -> None:
    """Clicking the line above the composer expands this turn's thinking."""
    window = arelis_window()
    window.show()
    qt_app.processEvents()
    assert window.chat.progress.toolTip() == "show thinking"
    assert window.chat.progress.accessibleName() == "show thinking"
    window._set_busy(True)
    dispatch_event(window, Event(EventType.THINKING, {"text": "because the moon pulls"}))
    window.chat.append_delta("Tides are the rise and fall of the sea.")
    window.chat.progress.clicked.emit()
    qt_app.processEvents()
    assert "because the moon pulls" in _plain(window)
    assert "Tides are the rise and fall of the sea." in _plain(window)


def test_every_status_kind_lands_somewhere_visible(arelis_window, qt_app) -> None:
    """Trace, tool, status and model lines stay visible with the dock open, shut, or idle."""
    window = arelis_window()
    window.show()
    qt_app.processEvents()
    window.persona_dock.show()
    qt_app.processEvents()
    window._set_busy(True)
    window.thinking.append("trace line about the tide", kind="trace")
    window.thinking.append("checking the tide table", kind="tool")
    window.thinking.append("model swapped to the fast one", kind="model")
    window.thinking.append("status while she works", kind="status")
    window.thinking.extend_stream(" and a little more reasoning")
    window.chat.expand_thinking()
    qt_app.processEvents()
    shown = _plain(window)
    assert "trace line about the tide" in shown
    assert "and a little more reasoning" in shown
    assert "checking the tide table" in shown
    assert "model swapped to the fast one" in shown
    assert "status while she works" in shown
    assert window.persona_panel.status_text() == ""

    window._set_busy(False)
    window.persona_dock.hide()
    qt_app.processEvents()
    window.thinking.append("status while she rests", kind="status")
    qt_app.processEvents()
    assert "status while she rests" in window.chat.empty.phone_note.text()
    assert window.chat._idle_note_timer.interval() == 6000


def test_thinking_still_scrubs_a_home_address_and_coordinates(arelis_window, qt_app) -> None:
    """A line with the saved place or its coordinates is scrubbed before it is shown."""
    window = arelis_window()
    window.show()
    qt_app.processEvents()
    try:
        install({"_location": PLACE})
        window._set_busy(True)
        window.thinking.append(
            "near Exampleville at 39.7817, -89.6501",
            kind="trace",
        )
        window.chat.expand_thinking()
        shown = _plain(window)
        assert "Exampleville" not in shown
        assert "39.7817" not in shown
        assert "-89.6501" not in shown
        assert "[location]" in shown
    finally:
        install({"location": {"privacy": {"redact_display": False}}})


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


def test_old_thinking_layouts_open_on_her_dock(
    arelis_window, qt_app, tmp_path, monkeypatch
) -> None:
    """A saved Thinking dock, wherever it was, comes back as her dock on the right."""
    for mode in ("visible", "hidden", "floating", "bottom"):
        ini = tmp_path / f"{mode}.ini"
        _save_old_layout(qt_app, str(ini), mode)
        monkeypatch.setattr(
            "arelis.ui.layout_store._settings_path",
            lambda p=ini: p,
        )
        window = arelis_window()
        window.resize(1440, 900)
        window.show()
        qt_app.processEvents()
        names = [item.objectName() for item in window.findChildren(QDockWidget)]
        assert "ThinkingDock" not in names
        assert names.count("PersonaDock") == 1
        dock = window.persona_dock
        assert dock.widget() is not None
        assert not dock.isFloating()
        assert window.dockWidgetArea(dock) == Qt.DockWidgetArea.RightDockWidgetArea
        assert 330 <= dock.width() <= 420
        assert not dock.isHidden()
        for item in window.findChildren(QDockWidget):
            assert item.widget() is not None
        window.hide()


def test_the_corner_orbit_shows_only_while_her_dock_is_hidden(arelis_window, qt_app) -> None:
    """Once a thread exists, the small orbit stays only while her dock is closed."""
    window = arelis_window()
    window.show()
    qt_app.processEvents()
    window.chat.add_user("hello")
    from arelis.ui.idle_host import sync_idle_mode

    sync_idle_mode(window)
    qt_app.processEvents()
    assert not window.persona_dock.isHidden()
    assert window.conversation._parked_orbit.isHidden()
    window.persona_dock.hide()
    qt_app.processEvents()
    assert not window.conversation._parked_orbit.isHidden()
    window.persona_dock.show()
    qt_app.processEvents()
    assert window.conversation._parked_orbit.isHidden()


def test_speaking_follows_playback_and_a_click_stops_it(arelis_window, qt_app, monkeypatch) -> None:
    """Playback opens her mouth. Clicking her asks the voice path to stop."""
    window = arelis_window()
    window.show()
    qt_app.processEvents()
    stopped = []
    monkeypatch.setattr(
        "arelis.ui.voice_host.stop_speech",
        lambda win: stopped.append(win),
    )
    window._speech_expected = True
    from arelis.ui.voice_host import update_speaking

    update_speaking(window)
    qt_app.processEvents()
    assert window.persona_panel.caption_text() == "speaking"
    window.persona_panel._pressed()
    assert stopped == [window]
    window._speech_expected = False
    window._speech_playing = False
    update_speaking(window)
    qt_app.processEvents()
    assert window.persona_panel.caption_text() != "speaking"


def test_three_themes_keep_the_thought_line_and_caption_readable(arelis_window, qt_app) -> None:
    """Sodium, night and filament each colour the thought line and her caption from that theme."""
    from PySide6.QtGui import QColor, QPixmap, QTextCursor

    from arelis.ui.settings_host import apply_window_theme
    from arelis.ui.theme import COLORS, color

    window = arelis_window()
    window.resize(1440, 900)
    window.show()
    qt_app.processEvents()
    window._set_busy(True)
    window.thinking.append("because the moon pulls", kind="trace")
    window._set_busy(False)
    window.chat.seal_thought()
    for theme in ("sodium", "night", "filament"):
        apply_window_theme(window, theme, persist=False)
        qt_app.processEvents()
        window.persona_dock.show()
        qt_app.processEvents()
        window.persona_panel.set_state("speaking")
        window.persona_panel.repaint()
        dim = QColor(COLORS["text_dim"])
        cursor = window.chat.view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        window.chat.view.setTextCursor(cursor)
        found = window.chat.view.find("Thought for")
        assert found
        picked = window.chat.view.textCursor().charFormat().foreground().color()
        assert abs(picked.red() - dim.red()) < 30
        assert abs(picked.green() - dim.green()) < 30
        assert abs(picked.blue() - dim.blue()) < 30
        pix = QPixmap(window.persona_panel.size())
        pix.fill(QColor(12, 10, 18))
        window.persona_panel.render(pix)
        image = pix.toImage()
        muted = color("text_muted")
        best = None
        for y in range(max(0, image.height() - 140), image.height()):
            for x in range(image.width()):
                pixel = image.pixelColor(x, y)
                if pixel.alpha() < 20:
                    continue
                if (
                    abs(pixel.red() - 12) < 8
                    and abs(pixel.green() - 10) < 8
                    and abs(pixel.blue() - 18) < 8
                ):
                    continue
                score = pixel.red() + pixel.green() + pixel.blue()
                if best is None or score > best[0]:
                    best = (score, pixel)
        assert best is not None
        pixel = best[1]
        toward = (
            (pixel.red() - 12) * (muted.red() - 12)
            + (pixel.green() - 10) * (muted.green() - 10)
            + (pixel.blue() - 18) * (muted.blue() - 18)
        )
        assert toward > 0
        assert pixel.red() + pixel.green() + pixel.blue() > 80
    apply_window_theme(window, "sodium", persist=False)
