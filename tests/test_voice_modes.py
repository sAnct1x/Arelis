"""Conversation / dictate / wake modes, hotkeys, and listen gates."""
from __future__ import annotations

from tests.voice_helpers import (
    _chord,
    _config,
    _controller,
    _FakeRecorder,
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




def test_end_silence_default_is_1400_ms_and_a_user_override_still_applies(qt_app) -> None:
    """The shipped hard ceiling is 1400 ms; a config override is honored."""
    import yaml

    from arelis.config import DEFAULT_CONFIG_PATH
    from arelis.ui.voice_control import DEFAULT_END_SILENCE_MS, VoiceController

    shipped = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    assert shipped["voice"]["conversation"]["end_silence_ms"] == 1400
    assert DEFAULT_END_SILENCE_MS == 1400

    controller = VoiceController(_config())
    assert controller._end_silence_ms == 1400

    overridden = VoiceController(_config(conversation={"end_silence_ms": 2500}))
    assert overridden._end_silence_ms == 2500


def test_conversation_turn_survives_two_second_pause_and_ends_at_end_silence(qt_app) -> None:
    """#260 (a): with a 2500 ms ceiling, a 2 s mid-thought pause stays one turn."""
    from arelis.ui.voice_control import VoiceController

    controller = VoiceController(_config(conversation={"end_silence_ms": 2500}))
    recorder = _FakeRecorder(controller)
    controller.recorder = recorder
    recorder.frames.connect(controller._on_frames)
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


async def test_speech_during_a_busy_turn_reaches_the_model(qt_app) -> None:
    """A pause ends the turn. The next non-control line, while that turn is busy, is kept.

    On main the second clip is deliver "control" and the orchestrator returns
    without a model call. With the fix the unanswered call restarts, the
    fragment row stays, and the model sees both user lines in order.
    """
    import asyncio
    from types import SimpleNamespace

    from arelis.config import PROJECT_ROOT
    from arelis.core.bus import EventBus
    from arelis.core.memory import SessionMemory
    from arelis.core.orchestrator import Orchestrator
    from arelis.tools.base import ToolRegistry
    from arelis.voice import VoiceService

    controller, recorder = _controller(qt_app)
    delivered: list[str] = []
    controller.utterance.connect(
        lambda _pcm, _rate, _channels, deliver: delivered.append(deliver)
    )
    controller.set_conversation(True)
    recorder.push(_tone(0.6) + _silence(3.0))
    assert delivered == ["turn"]
    controller.notify_turn_started()
    assert controller._wants_listening() is False
    recorder.push(_tone(0.6) + _silence(3.0))
    assert len(delivered) == 2
    second = delivered[1]

    class _HoldRouter:
        def __init__(self) -> None:
            self.user_turns: list[list[str]] = []
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.default_role = "fast"
            self.active_model = "mock"
            self.models = {"fast": "mock", "research": "mock", "code": "mock"}

        def model_for(self, role=None):
            return "mock"

        async def ensure_role(self, role, *, force: bool = False):
            del force
            return "mock"

        def mark_sticky(self, role) -> None:
            return None

        def apply_sticky(self, wanted, reason: str):
            return wanted, reason

        def clear_sticky(self) -> None:
            return None

        async def stream(self, role, messages, **kwargs):
            lines = [
                str(item.get("content") or "")
                for item in messages
                if isinstance(item, dict) and item.get("role") == "user"
            ]
            self.user_turns.append(lines)
            self.started.set()
            await self.release.wait()
            yield ("token", "Noted.")

    bus = EventBus()
    router = _HoldRouter()
    orch = Orchestrator(
        bus,
        router,  # type: ignore[arg-type]
        ToolRegistry(),
        {
            "agent": {"max_rounds": 2, "confirm_timeout_s": 5},
            "workspace": {"roots": ["."]},
            "_persona_path": str(PROJECT_ROOT / "arelis" / "persona" / "arelis.md"),
            "_speak_replies": True,
        },
        SessionMemory(),
    )
    publisher = SimpleNamespace(bus=bus)
    bus_task = asyncio.create_task(bus.run())
    try:
        await VoiceService._publish_transcript(
            publisher, "the porch light is out", deliver="turn"
        )
        await asyncio.wait_for(router.started.wait(), timeout=15)
        await VoiceService._publish_transcript(
            publisher, "and the steps are icy", deliver=second
        )
        merged = False
        for _ in range(160):
            last = router.user_turns[-1] if router.user_turns else []
            if any("porch light" in line for line in last) and any(
                "steps are icy" in line for line in last
            ):
                merged = True
                break
            await asyncio.sleep(0.05)
        router.release.set()
        await asyncio.wait_for(bus.drain(), timeout=20)
    finally:
        router.release.set()
        bus.stop()
        bus_task.cancel()
        await asyncio.gather(bus_task, return_exceptions=True)
    assert merged, (
        f"deliver={second!r} never put both lines in one model prompt; "
        f"user turns={router.user_turns!r}"
    )
    last = router.user_turns[-1]
    porch = [line for line in last if "porch light" in line]
    icy = [line for line in last if "steps are icy" in line]
    assert porch == ["the porch light is out"], porch
    assert icy == ["and the steps are icy"], icy
    assert last.index(porch[0]) < last.index(icy[0])
    user_rows = [m for m in orch.memory.messages if m.role == "user"]
    assert [m.content for m in user_rows] == [
        "the porch light is out",
        "and the steps are icy",
    ], user_rows
    assert [m.cancelled for m in user_rows] == [False, False]
    answered = [m.content for m in orch.memory.messages if m.role == "assistant"]
    assert answered and "Stopped" not in answered[-1], answered
    assert orch._turn_task is None or orch._turn_task.done()


def test_smart_turn_ends_complete_utterance_fast_and_holds_incomplete_up_to_ceiling(
    qt_app,
) -> None:
    from arelis.ui.voice_control import VoiceController
    from tests.voice_helpers import _config, _FakeRecorder

    state = {"complete": True}

    class _FakeSmartTurn:
        def predict(self, pcm: bytes, *, sample_rate: int = 16000, channels: int = 1):
            del pcm, sample_rate, channels
            return {"complete": state["complete"], "probability": 0.9 if state["complete"] else 0.1}

    cfg = _config(conversation={"smart_turn": False, "silence_ms": 550, "short_silence_ms": 450, "end_silence_ms": 2500})
    controller = VoiceController(cfg)
    controller._smart_turn = _FakeSmartTurn()
    controller._detector_defaults["silence_ms"] = 550
    controller._detector_defaults["short_silence_ms"] = 450
    recorder = _FakeRecorder(controller)
    controller.recorder = recorder
    recorder.frames.connect(controller._on_frames)

    turns: list[bytes] = []
    controller.utterance.connect(
        lambda pcm, _r, _c, kind: turns.append(pcm) if kind == "turn" else None
    )
    controller.set_conversation(True)

    # 1) When Smart Turn says complete=True, the turn ends after ~0.6s of silence
    # without waiting for the 2.5s end_silence_ms ceiling.
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(0.6))
    assert len(turns) == 1

    # 2) When Smart Turn says complete=False (mid-thought pause), a 1.5s pause
    # holds the turn open, and if silence reaches end_silence_ms (2.5s), it caps.
    controller.notify_turn_started()
    controller.notify_speaking(True)
    controller.notify_turn_finished()
    controller.notify_speaking(False)
    turns.clear()
    state["complete"] = False

    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.5))
    assert turns == []
    recorder.push(_silence(1.2))
    assert len(turns) == 1


def test_conversation_speech_start_trims_pre_onset_ambient_buffer(qt_app) -> None:
    controller, recorder = _controller(qt_app)
    turns: list[bytes] = []
    controller.utterance.connect(
        lambda pcm, _r, _c, kind: turns.append(pcm) if kind == "turn" else None
    )
    controller.set_conversation(True)

    # 12 seconds of quiet room wait before speaking 1 second of voice.
    recorder.push(_silence(12.0) + _tone(1.0) + _silence(2.7))
    assert len(turns) == 1
    duration_s = len(turns[0]) / (16000 * 2)
    assert duration_s < 2.5, f"Expected pre-onset silence trimmed, got {duration_s:.2f}s"




def test_barge_in_keeps_stop_and_the_question_as_one_turn(qt_app) -> None:
    """A short pause after barge-in 'Stop.' stays in the same clip as the ask.

    The 2026-11-09 headset interrupt was "Stop. What's two plus two?" with
    1.16 s of silence after Stop. Smart Turn is skipped on the first barge
    pause, so 450 ms of silence used to end the clip there. "Stop." was
    then consumed as a control word and only the question was heard.
    """
    from arelis.ui.voice_control import VoiceController
    from tests.voice_helpers import _config, _FakeRecorder

    class _FakeSmartTurn:
        def predict(self, pcm: bytes, *, sample_rate: int = 16000, channels: int = 1):
            del pcm, sample_rate, channels
            return {"complete": True, "probability": 0.98}

    cfg = _config(
        conversation={
            "smart_turn": False,
            "silence_ms": 550,
            "short_silence_ms": 450,
            "end_silence_ms": 2500,
            "barge_in": True,
            "barge_in_as_turn": True,
        }
    )
    controller = VoiceController(cfg)
    controller._smart_turn = _FakeSmartTurn()
    controller._detector_defaults["silence_ms"] = 550
    controller._detector_defaults["short_silence_ms"] = 450
    recorder = _FakeRecorder(controller)
    controller.recorder = recorder
    recorder.frames.connect(controller._on_frames)
    # The window cuts playback on barge_in, which clears speaking. Without
    # that, the first clip is thrown away as echo.
    controller.barge_in.connect(lambda: controller.notify_speaking(False))

    turns: list[tuple[str, float]] = []
    controller.utterance.connect(
        lambda pcm, rate, channels, kind: turns.append(
            (kind, len(pcm) / (2 * rate))
        )
    )
    controller.set_conversation(True)
    controller.notify_turn_started()
    controller.notify_speaking(True)

    # "Stop." then the 1.16 s gap must not end the barge clip on its own.
    recorder.push(_tone(0.4) + _silence(1.16))
    assert turns == [], f"mid-gap ended the barge clip early: {turns!r}"
    # The question plus a short final pause close the same clip.
    recorder.push(_tone(1.0) + _silence(0.7))
    assert len(turns) == 1, turns
    kind, seconds = turns[0]
    assert kind == "turn", kind
    # Both tones plus the 1.16 s gap must be in the same clip (minus a little
    # trailing-silence trim). A split after Stop. is only ~0.4-1.0 s.
    assert seconds > 2.2, f"expected the joined interrupt, got {seconds:.2f}s"
