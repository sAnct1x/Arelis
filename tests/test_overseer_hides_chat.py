"""Chat is hidden and disabled while the Overseer is open, then restored."""

from __future__ import annotations

from PySide6.QtGui import QAccessible


def test_chat_is_disabled_while_the_overseer_is_open(
    arelis_window, qt_app, monkeypatch
) -> None:
    """Opening Sentinels hides the composer and parks the transcript.

    The 10:28 PM decision disables chat while the Overseer is open so the
    window is free for it. The composer stayed enabled, so a Send could
    still go through and painted every token against the live scene.
    """
    from arelis import sentinel_control

    monkeypatch.setattr(sentinel_control, "_process", None)
    monkeypatch.setattr(sentinel_control, "_token", None)
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

    window.act_sentinels.trigger()
    qt_app.processEvents()
    assert window.sentinel_window is not None and window.sentinel_window.isVisible()

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
