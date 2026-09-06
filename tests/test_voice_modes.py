"""Conversation / dictate / wake modes, hotkeys, and listen gates."""
from __future__ import annotations

import asyncio

import pytest

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.ui.voice_host import on_capture_failed, on_voice_mode
from arelis.voice import VoiceService
from tests.voice_helpers import (
    _chord,
    _controller,
    _FakeRecorder,
    _hotkey_window,
    _silence,
    _tone,
)


def test_a_pause_sends_the_utterance_hands_free(qt_app) -> None:
    controller, recorder = _controller(qt_app)
    sent: list[tuple[bytes, str]] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append((pcm, deliver)))

    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    assert len(sent) == 1
    assert sent[0][1] == "turn"
    assert len(sent[0][0]) > 0

def test_dictation_keeps_listening_through_a_pause(qt_app) -> None:
    """The whole reason dictation exists: pauses are thinking, not the end."""
    controller, recorder = _controller(qt_app)
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))

    controller.set_dictate(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    recorder.push(_tone(1.0) + _silence(1.4))
    assert sent == ["dictate", "dictate"]
    assert controller.mode() == "dictate"
    assert recorder.is_recording()

def test_a_second_utterance_is_not_stacked_on_a_running_turn(qt_app) -> None:
    """One turn at a time is an orchestrator invariant. Queueing speech the
    user has already forgotten saying is worse than dropping it. Mid-turn
    speech is control so stop can land; it is not a second ask.
    """
    controller, recorder = _controller(qt_app)
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))

    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    controller.notify_turn_started()
    recorder.push(_tone(1.0) + _silence(1.4))
    assert sent == ["turn", "control"]

def test_a_misclick_is_not_sent(qt_app) -> None:
    """A fraction of a second of noise makes Whisper hallucinate "thank you",
    which then costs a model turn."""
    controller, recorder = _controller(qt_app)
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))

    controller.set_dictate(True)
    recorder.push(_tone(0.1))
    controller.set_dictate(False)
    assert sent == []

def test_turning_dictation_off_flushes_what_was_said(qt_app) -> None:
    from PySide6.QtCore import QCoreApplication

    controller, recorder = _controller(qt_app)
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))

    controller.set_dictate(True)
    recorder.push(_tone(1.0))
    controller.set_dictate(False)
    assert sent == ["dictate"]
    # Leaving dictate resumes always-listen wake mode.
    QCoreApplication.processEvents()
    assert controller.mode() == "wake"

def test_switching_modes_closes_the_previous_one(qt_app) -> None:
    controller, recorder = _controller(qt_app)
    controller.set_dictate(True)
    assert controller.mode() == "dictate"
    controller.set_conversation(True)
    assert controller.mode() == "conversation"
    controller.stop_all()
    assert controller.mode() == "off"
    assert not recorder.is_recording()


# --------------------------------------------------------------------------
# The window: spoken words have to appear as a message
# --------------------------------------------------------------------------

def test_conversation_keeps_listening_when_nothing_was_heard(qt_app) -> None:
    """An utterance that never becomes a turn produces no terminal event. The
    controller used to wait for one anyway, dropping every later pause as
    "still working on the last one" until voice was toggled off and on."""
    controller, recorder = _controller(qt_app)
    listening: list[bool] = []
    sent: list[str] = []
    controller.listening_changed.connect(listening.append)
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))

    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    assert len(sent) == 1
    assert listening[-1] is False

    # Transcription came back empty: no turn, so nothing else will report in.
    controller.notify_utterance_dropped()
    assert listening[-1] is True

    recorder.push(_tone(1.0) + _silence(1.4))
    assert len(sent) == 2, "the next thing said must still be heard"

def test_a_spoken_physics_verb_does_not_deafen_conversation(qt_app) -> None:
    """Closed verbs skip USER_MESSAGE. Conversation must listen again, not wait."""
    from arelis.ui.app import ArelisWindow, BusBridge

    controller, recorder = _controller(qt_app)
    listening: list[bool] = []
    controller.listening_changed.connect(listening.append)

    config = {
        "ui": {"window_title": "Arelis", "default_width": 800, "default_height": 600},
        "router": {"default_role": "fast"},
        "models": {"fast": "mock"},
        "voice": {"enabled": False},
    }
    window = ArelisWindow(config, BusBridge(), asyncio.new_event_loop(), EventBus())
    try:
        window.voice_controller = controller
        window.conversation.room.set_room("physics", name="Reality")
        controller.set_conversation(True)
        recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
        assert listening[-1] is False
        assert controller.debug_state()["awaiting"] is True

        window._on_event(Event(EventType.PHYSICS_VERB, {"verb": "pause"}))
        assert listening[-1] is True
        assert controller.debug_state()["awaiting"] is False
    finally:
        window.dispose()
        window.hide()
        window.loop.close()

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

def test_voice_hotkeys_allowed_when_world_is_the_active_window(qt_app, monkeypatch) -> None:
    """World is a native Tool window; conversation chords still belong to Arelis."""
    from PySide6.QtWidgets import QApplication

    from arelis.ui.app import ArelisWindow, BusBridge

    config = {
        "ui": {"window_title": "Arelis", "default_width": 800, "default_height": 600},
        "router": {"default_role": "fast"},
        "voice": {"enabled": False},
    }
    window = ArelisWindow(config, BusBridge(), asyncio.new_event_loop(), EventBus())
    try:
        monkeypatch.setattr(
            QApplication, "activeWindow", lambda *a, **k: window.world_window
        )
        assert window._voice_hotkeys_allowed() is True
        monkeypatch.setattr(QApplication, "activeWindow", lambda *a, **k: None)
        assert window._voice_hotkeys_allowed() is False
    finally:
        window.dispose()
        window.hide()
        window.loop.close()

def test_spoken_goodbye_unlatches_conversation(qt_app) -> None:
    """Hangup is a closed act: the two-arcs toggle drops, wake can listen."""
    from arelis.ui.app import ArelisWindow, BusBridge

    controller, recorder = _controller(qt_app)
    listening: list[bool] = []
    controller.listening_changed.connect(listening.append)

    config = {
        "ui": {"window_title": "Arelis", "default_width": 800, "default_height": 600},
        "router": {"default_role": "fast"},
        "models": {"fast": "mock"},
        "voice": {"enabled": False},
    }
    window = ArelisWindow(config, BusBridge(), asyncio.new_event_loop(), EventBus())
    try:
        window.voice_controller = controller
        controller.set_conversation(True)
        window.conversation.set_conversing(True)
        recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
        assert controller.debug_state()["awaiting"] is True

        window._on_event(Event(EventType.CONVERSATION_END, {"reason": "voice"}))
        assert not window.conversation.conversation_btn.isChecked()
        assert controller.debug_state()["awaiting"] is False
        assert controller.mode != "conversation"
    finally:
        window.dispose()
        window.hide()
        window.loop.close()

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

def test_a_capture_failure_actually_leaves_the_mode(qt_app) -> None:
    """Unchecking the buttons without stopping the controller showed voice as
    off while the microphone was still held open."""
    from arelis.ui.app import ArelisWindow, BusBridge

    config = {
        "ui": {},
        "router": {"default_role": "fast"},
        "voice": {"enabled": True, "stt": {}, "tts": {"enabled": False}, "conversation": {}},
    }
    bus = EventBus()
    window = ArelisWindow(
        config, BusBridge(), asyncio.new_event_loop(), bus, VoiceService(bus, config)
    )
    try:
        if window.voice_controller is None:
            pytest.skip("no input device on this machine")
        # Nothing here reaches the async side, and the loop is not running.
        window.voice = None
        recorder = _FakeRecorder(window.voice_controller)
        window.voice_controller.recorder = recorder
        window.voice_controller.set_conversation(True)
        assert recorder.is_recording()

        on_capture_failed(window, "The microphone was unplugged.")
        assert not recorder.is_recording()
        assert window.voice_controller.mode() == "off"
        assert not window.conversation.conversation_btn.isChecked()
    finally:
        window.loop.close()

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

def test_the_shift_chord_does_not_start_dictation(qt_app) -> None:
    """Ctrl+M and Ctrl+Shift+M are different modes and both are exclusive."""
    from PySide6.QtCore import QEvent

    window = _hotkey_window()
    try:
        dictate: list[bool] = []
        talk: list[bool] = []
        window.conversation.dictate_toggled.connect(dictate.append)
        window.conversation.conversation_toggled.connect(talk.append)

        window.eventFilter(window, _chord(QEvent.Type.KeyPress, shift=True))
        assert talk == [True]
        assert dictate == []

        window._voice_hotkey_at = 0.0
        window.eventFilter(window, _chord(QEvent.Type.KeyPress, shift=False))
        assert dictate == [True]
        # Entering dictation drops conversation: one mic, one owner.
        assert talk == [True, False]
        assert window.conversation.mic_btn.isChecked()
        assert not window.conversation.conversation_btn.isChecked()
    finally:
        window.loop.close()

def test_the_latched_mode_is_readable_on_the_empty_orbit(qt_app) -> None:
    """The orbit is the whole UI in idle. A latched mode with no visible mark
    is indistinguishable from a dead hotkey, which is how two hours went."""
    window = _hotkey_window()
    try:
        window._reset_layout()
        idle = window.chat.empty
        off = idle.listen_word.text()

        on_voice_mode(window, "conversation")
        talking = idle.listen_word.text()
        assert talking != off
        assert "talking" in talking.lower()
        assert idle.listen_word.property("live") == "true"

        on_voice_mode(window, "dictate")
        assert idle.listen_word.text() not in {off, talking}
        assert idle.listen_word.property("live") == "true"

        # Wake is always on in idle, so it reads the same as nothing latched.
        on_voice_mode(window, "wake")
        assert idle.listen_word.text() == off
        assert idle.listen_word.property("live") == "false"
    finally:
        window.hide()
        window.loop.close()


# --------------------------------------------------------------------------
# Wake word
# --------------------------------------------------------------------------

def test_wake_listen_emits_wake_deliver(qt_app) -> None:
    controller, recorder = _controller(qt_app)
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))

    controller.start_wake()
    assert controller.mode() == "wake"
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    assert sent == ["wake"]

def test_conversation_stays_on_when_mic_resume_fails(qt_app) -> None:
    """A blipped mic after Stop must not drop conversation into whisper wake."""
    controller, recorder = _controller(qt_app)
    controller.set_conversation(True)
    assert controller.mode() == "conversation"
    controller.notify_turn_started()
    recorder._recording = False
    recorder.start = lambda: False  # type: ignore[method-assign]
    controller.notify_turn_finished()
    assert controller.mode() == "conversation"

def test_leaving_conversation_resumes_wake_listen(qt_app) -> None:
    from PySide6.QtCore import QCoreApplication

    controller, _recorder = _controller(qt_app)
    controller.set_conversation(True)
    assert controller.mode() == "conversation"
    controller.set_conversation(False)
    # start_wake is deferred on a zero timer
    QCoreApplication.processEvents()
    assert controller.mode() == "wake"

def test_wake_is_paused_during_dictate(qt_app) -> None:
    controller, recorder = _controller(qt_app)
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))
    controller.start_wake()
    controller.set_dictate(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    assert sent == ["dictate"]
    assert controller.mode() == "dictate"

def test_a_lost_utterance_callback_does_not_deafen_conversation(qt_app) -> None:
    """Nothing in the hand-off path is unbounded, but a callback that never
    arrives used to cost the rest of the session rather than a pause."""
    controller, recorder = _controller(qt_app)
    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    assert not controller.listening()

    controller._on_turn_watchdog()  # what the timer does thirty seconds later
    assert controller.listening()

def test_voice_debug_records_the_state_that_stuck(qt_app, tmp_path) -> None:
    """The point of the trace: reading the last line has to say which of the
    three flags is holding the microphone shut."""
    from arelis.voice.telemetry import VoiceTrace

    controller, recorder = _controller(qt_app)
    controller.trace = VoiceTrace(True, log_dir=tmp_path)

    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    controller.notify_turn_started()
    controller.notify_speaking(True)

    lines = controller.trace.recent()
    assert any("speech_end" in line for line in lines)
    # The last line alone says which flag is holding the microphone shut.
    assert "mode=conversation" in lines[-1]
    assert "listening=0" in lines[-1]
    assert "turn_busy=1" in lines[-1]
    assert "speaking=1" in lines[-1]

def test_a_pause_that_captured_nothing_leaves_the_listening_alone(qt_app) -> None:
    """Nothing was said, so there is no turn to wait for. Going deaf here used
    to need a deferred timer to undo it."""
    controller, _recorder = _controller(qt_app)
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))

    controller.set_conversation(True)
    assert controller.listening()
    controller._on_speech_ended(timed_out=False)  # the buffer is empty
    assert sent == []
    assert controller.listening()

def test_smart_turn_incomplete_pause_does_not_end_the_turn(qt_app) -> None:
    class _StubSmartTurn:
        def __init__(self) -> None:
            self.complete_value = False
            self.calls = 0

        def predict(self, pcm, sample_rate=16000, channels=1):
            self.calls += 1
            return {
                "complete": self.complete_value,
                "probability": 0.9 if self.complete_value else 0.1,
            }

    controller, recorder = _controller(qt_app)
    stub = _StubSmartTurn()
    controller._smart_turn = stub
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))
    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    assert sent == []
    assert stub.calls >= 1
    stub.complete_value = True
    recorder.push(_tone(0.6) + _silence(1.4))
    assert sent == ["turn"]

def test_missing_smart_turn_uses_silence_ms(qt_app) -> None:
    controller, recorder = _controller(qt_app)
    assert controller._smart_turn is None
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))
    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    assert sent == ["turn"]

def test_conversation_onset_emits_live_started(qt_app) -> None:
    controller, recorder = _controller(qt_app)
    hits: list[int] = []
    controller.live_started.connect(lambda: hits.append(1))
    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    assert hits == [1]

def test_wake_to_conversation_keeps_the_buffer(qt_app) -> None:
    controller, recorder = _controller(qt_app)
    hits: list[int] = []
    controller.live_started.connect(lambda: hits.append(1))
    controller.start_wake()
    recorder.push(_tone(0.8))
    kept = len(recorder.peek())
    assert kept > 0
    controller.set_conversation(True)
    assert len(recorder.peek()) == kept
    assert hits == [1]
    assert controller.debug_state()["vad"] is True
