"""Conversation / dictate / wake modes, hotkeys, and listen gates."""
from __future__ import annotations

from tests.voice_helpers import (
    _chord,
    _controller,
    _hotkey_window,
    _silence,
    _tone,
)

# --------------------------------------------------------------------------
# The window: spoken words have to appear as a message
# --------------------------------------------------------------------------


def test_conversation_listen_gate_does_not_depend_on_world_focus(qt_app) -> None:
    """The mic gate is turn/speech/awaiting — not which plate is active."""
    controller, _recorder = _controller(qt_app)
    controller.set_conversation(True)
    assert controller._wants_listening() is True
    assert "focus" not in controller.debug_state()
    controller.notify_turn_started()
    assert controller._wants_listening() is False
    controller.notify_turn_finished()
    assert controller._wants_listening() is True


def test_confirm_card_keeps_conversation_listening(qt_app) -> None:
    """Conversation mode hears allow / deny. The mic stays on for the card."""
    controller, _recorder = _controller(qt_app)
    listening: list[bool] = []
    controller.listening_changed.connect(listening.append)

    controller.set_conversation(True)
    assert listening[-1] is True

    controller.notify_turn_started()
    controller.notify_confirm_pending(True)
    assert listening[-1] is True

    controller.notify_confirm_pending(False)
    controller.notify_turn_finished()
    assert listening[-1] is True


def test_one_held_chord_latches_conversation_on(qt_app) -> None:
    """Held Ctrl+Shift+M must latch ON and stay there.

    One physical press arrives as ShortcutOverride and then KeyPress, and
    Windows repeats a held chord every few tens of milliseconds once the repeat
    delay expires. Toggling on every delivery meant the mode turned on and
    straight back off, so the orbit looked dead and the mic never opened.
    """
    from PySide6.QtCore import QEvent

    window = _hotkey_window()
    try:
        toggles: list[bool] = []
        window.conversation.conversation_toggled.connect(toggles.append)

        override = _chord(QEvent.Type.ShortcutOverride, shift=True)
        assert window.eventFilter(window, override) is True
        assert override.isAccepted(), "the composer must not receive the m"
        assert toggles == [], "ShortcutOverride must not toggle anything"

        assert window.eventFilter(window, _chord(QEvent.Type.KeyPress, shift=True)) is True
        assert toggles == [True]

        for _ in range(6):
            window.eventFilter(
                window, _chord(QEvent.Type.KeyPress, shift=True, autorep=True)
            )
        assert toggles == [True], "auto-repeat is one press, not seven"
        assert window.conversation.conversation_btn.isChecked()

        # A deliberate second chord, after the echo window, releases the latch.
        window._voice_hotkey_at = 0.0
        window.eventFilter(window, _chord(QEvent.Type.KeyPress, shift=True))
        assert toggles == [True, False]
    finally:
        window.loop.close()


# --------------------------------------------------------------------------
# Wake word
# --------------------------------------------------------------------------




def test_conversation_turn_survives_two_second_pause_and_ends_at_end_silence(qt_app) -> None:
    """#260 (a): a 2 s mid-thought pause stays one turn; 2.5 s of silence ends it."""
    controller, recorder = _controller(qt_app)
    turns: list[float] = []
    controller.utterance.connect(
        lambda pcm, rate, channels, deliver: turns.append(len(pcm) / (2 * rate))
        if deliver == "turn"
        else None
    )
    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(2.0) + _tone(1.0) + _silence(2.3))
    assert turns == []
    recorder.push(_silence(0.4))
    assert len(turns) == 1
