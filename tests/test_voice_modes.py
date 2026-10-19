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


async def test_speech_during_a_busy_turn_reaches_the_model(qt_app) -> None:
    """A pause ends the turn. The next non-control line, while that turn is busy, is kept.

    On main the second clip is deliver "control" and the orchestrator returns
    without a model call. With the fix the model sees both halves in one prompt
    (he resumed before any token) or, once the model has answered, as the next turn.
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
            if any(
                "porch light" in line and "steps are icy" in line
                for turn in router.user_turns
                for line in turn
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
        f"deliver={second!r} never put both halves in one model prompt; "
        f"user turns={router.user_turns!r}"
    )
    remembered = [m.content for m in orch.memory.messages if m.role == "user"]
    assert remembered == ["the porch light is out and the steps are icy"], remembered
    answered = [m.content for m in orch.memory.messages if m.role == "assistant"]
    assert answered and "Stopped" not in answered[-1], answered
    assert orch._turn_task is None or orch._turn_task.done()
