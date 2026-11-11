"""Chat is hidden and disabled while the Overseer is open, then restored."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible, QKeySequence, QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog


def _open_overseer(window, qt_app, monkeypatch) -> None:
    from arelis import sentinel_control

    monkeypatch.setattr(sentinel_control, "_process", None)
    monkeypatch.setattr(sentinel_control, "_token", None)
    window.act_sentinels.trigger()
    qt_app.processEvents()
    assert window.sentinel_window is not None and window.sentinel_window.isVisible()


def _attach_shortcut(conv) -> QShortcut:
    want = QKeySequence("Ctrl+Shift+A")
    for shortcut in conv.findChildren(QShortcut):
        if shortcut.key() == want:
            return shortcut
    raise AssertionError("missing Ctrl+Shift+A attach shortcut")


def test_chat_is_disabled_while_the_overseer_is_open(
    arelis_window, qt_app, monkeypatch
) -> None:
    """Opening Sentinels hides the composer and parks the transcript.

    The 10:28 PM decision disables chat while the Overseer is open so the
    window is free for it. The composer stayed enabled, so a Send could
    still go through and painted every token against the live scene.
    """
    window = arelis_window()
    window.show()
    qt_app.processEvents()

    conv = window.conversation
    input_box = conv.input
    send = conv.send_btn
    assert input_box.isEnabled() and not input_box.isHidden()
    assert send.isEnabled()
    assert conv.chat._view_parked is False
    before = QAccessible.queryAccessibleInterface(input_box)
    assert before is not None
    assert not before.state().disabled
    assert not before.state().invisible

    _open_overseer(window, qt_app, monkeypatch)

    assert input_box.isHidden()
    assert not input_box.isEnabled()
    assert send.isHidden() or not send.isEnabled()
    assert conv.chat._view_parked is True
    during = QAccessible.queryAccessibleInterface(input_box)
    assert during is not None
    state = during.state()
    assert state.disabled or state.invisible

    window.sentinel_window.close()
    qt_app.processEvents()

    assert not input_box.isHidden()
    assert input_box.isEnabled()
    assert send.isEnabled()
    assert conv.chat._view_parked is False
    after = QAccessible.queryAccessibleInterface(input_box)
    assert after is not None
    assert not after.state().disabled
    assert not after.state().invisible


def test_a_reply_streamed_from_the_empty_face_is_visible_after_the_overseer_closes(
    arelis_window, qt_app, monkeypatch
) -> None:
    """A first reply that arrives while the Overseer is open must show after close.

    Restore used to put widgets back to the empty-face snapshot, and unparking
    did not show the transcript, so the words stayed hidden behind the empty
    state even though they were already in the document.
    """
    window = arelis_window()
    window.show()
    qt_app.processEvents()

    chat = window.conversation.chat
    assert not chat.has_messages
    assert chat.view.isHidden()
    assert not chat.empty.isHidden()

    _open_overseer(window, qt_app, monkeypatch)
    chat.begin_assistant()
    chat.append_delta("Secret number 42")
    chat.finish_assistant("Secret number 42")
    qt_app.processEvents()

    assert chat.has_messages
    assert "Secret number 42" in chat.view.toPlainText()

    window.sentinel_window.close()
    qt_app.processEvents()

    assert chat._view_parked is False
    assert not chat.view.isHidden()
    assert chat.empty.isHidden()
    assert "Secret number 42" in chat.view.toPlainText()
    assert chat.view.isVisible()


def test_a_theme_switch_while_the_overseer_is_open_restores_the_current_theme(
    arelis_window, qt_app, monkeypatch
) -> None:
    """Closing after a theme switch must follow the theme in use, not the old snapshot.

    Sodium, open the Overseer, switch to Filament, close: the pre-open
    snapshot used to leave the transcript unparked on the field with the
    chat tile still closed.
    """
    from arelis.ui.settings_host import apply_window_theme
    from arelis.ui.theme import active_theme

    window = arelis_window(
        {
            "ui": {
                "default_width": 900,
                "default_height": 650,
                "theme": "sodium",
                "filament_ack": True,
            }
        }
    )
    window.show()
    qt_app.processEvents()

    chat = window.conversation.chat
    chat.add_user("hello")
    chat.begin_assistant()
    chat.finish_assistant("already on screen")
    qt_app.processEvents()
    assert not chat.view.isHidden()
    assert chat._view_parked is False

    _open_overseer(window, qt_app, monkeypatch)
    apply_window_theme(window, "filament", persist=False)
    qt_app.processEvents()
    QTest.qWait(200)
    assert active_theme() == "filament"
    assert window.conversation._filament_desk is True
    assert window.conversation.chat._view_parked is True

    window.sentinel_window.close()
    qt_app.processEvents()
    QTest.qWait(200)

    assert active_theme() == "filament"
    assert window.conversation._filament_desk is True
    assert not window._filament_chat_open
    assert window._filament_chat_tile.isHidden()
    assert chat._view_parked is True
    assert chat.view.isHidden()
    assert not chat.view.isVisible()


def test_chat_shortcuts_and_dictation_do_nothing_while_the_overseer_is_open(
    arelis_window, qt_app, monkeypatch
) -> None:
    """Ctrl+Shift+A and dictation must not reach the hidden composer."""
    picked: list[object] = []

    def _fake_dialog(*_args, **_kwargs):
        picked.append(True)
        return [], ""

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", _fake_dialog)

    window = arelis_window()
    window.show()
    qt_app.processEvents()

    conv = window.conversation
    attach = _attach_shortcut(conv)
    assert attach.isEnabled()
    conv.insert_dictation("before open")
    assert conv.input.text() == "before open"
    conv.input.clear()

    _open_overseer(window, qt_app, monkeypatch)

    assert not attach.isEnabled()
    attach.activated.emit()
    qt_app.processEvents()
    assert picked == []
    conv._pick_files()
    qt_app.processEvents()
    assert picked == []
    conv.insert_dictation("voice words")
    qt_app.processEvents()
    assert conv.input.text() == ""

    window.sentinel_window.close()
    qt_app.processEvents()

    assert attach.isEnabled()
    conv.insert_dictation("after close")
    assert conv.input.text() == "after close"
    conv._pick_files()
    assert picked == [True]


def test_a_pending_card_stays_answerable_after_an_esc_close(
    arelis_window, qt_app, monkeypatch
) -> None:
    """Esc on the Overseer must close it without answering a pending Allow card."""
    window = arelis_window()
    window.show()
    qt_app.processEvents()

    conv = window.conversation
    decided: list[tuple] = []
    conv.confirm_decided.connect(lambda cid, dec, allow: decided.append((cid, dec, allow)))
    conv.ask_confirm("c-esc", "write", "Write notes.txt", detail="hello")
    qt_app.processEvents()
    assert conv.confirm_open()

    _open_overseer(window, qt_app, monkeypatch)
    QTest.keyClick(window.sentinel_window, Qt.Key.Key_Escape)
    qt_app.processEvents()

    assert window.sentinel_window is None or not window.sentinel_window.isVisible()
    assert conv.confirm_open()
    assert decided == []
    assert conv.confirm.allow_btn.isEnabled()
    assert conv.confirm.allow_btn.isVisible()

    conv.confirm.allow_btn.click()
    qt_app.processEvents()
    assert decided == [("c-esc", "allow", False)]
    assert not conv.confirm_open()


def test_opening_the_overseer_does_not_cancel_a_busy_turn(
    arelis_window, qt_app, monkeypatch
) -> None:
    """A running turn and its Allow card must stay live across an Esc close."""
    window = arelis_window()
    window.show()
    qt_app.processEvents()

    conv = window.conversation
    conv.ask_confirm("c-busy", "write", "Write notes.txt", detail="hello")
    qt_app.processEvents()
    assert conv.confirm_open()

    cancelled: list[dict] = []
    window._cancel_turn = lambda *, schedule_next, reason="stop": cancelled.append(
        {"schedule_next": schedule_next, "reason": reason}
    )
    window._turn_busy = True

    _open_overseer(window, qt_app, monkeypatch)
    QTest.keyClick(window.sentinel_window, Qt.Key.Key_Escape)
    qt_app.processEvents()

    assert window.sentinel_window is None or not window.sentinel_window.isVisible()
    assert cancelled == []
    assert conv.confirm_open()
    assert conv.confirm.allow_btn.isEnabled()
    assert conv.confirm.allow_btn.isVisible()

