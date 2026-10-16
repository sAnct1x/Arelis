"""A late glass retract must not cancel the replacement utterance."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType


class _SlowTTS:
    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    def problem(self) -> None:
        return None

    async def synthesize(self, text: str, out: Path, language: str = "") -> Path:
        self.spoken.append(text)
        if not self.entered.is_set():
            self.entered.set()
            await self.release.wait()
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"RIFF")
        return path


class _Player:
    def __init__(self) -> None:
        self.stopped = 0

    def stop(self) -> None:
        self.stopped += 1

    def has_work(self) -> bool:
        return False


class _Chat:
    def discard_stream(self) -> None:
        return None


class _Conversation:
    def set_speaking(self, speaking: bool) -> None:
        return None


class _Watchdog:
    def start(self, ms: int) -> None:
        return None

    def stop(self) -> None:
        return None


class _Window:
    def __init__(self, voice: object) -> None:
        self.voice = voice
        self.chat = _Chat()
        self.conversation = _Conversation()
        self.speech_player = _Player()
        self._speech_watchdog = _Watchdog()
        self._mobile_foreign = False
        self._assistant_streaming = True
        self._speech_expected = True
        self._speech_playing = False
        self._held_inbound: list[object] = []
        self.voice_controller = None
        self.persona_panel = None
        self._hung_watchdog = None


@pytest.mark.asyncio
async def test_late_ui_retract_still_speaks_the_replacement() -> None:
    """#280: Qt retract lands after the replacement has the next speak id.

    VoiceService.on_retract cancels the withdrawn utterance. The glass used
    to call cancel_speech again from the queued Qt handler, which stamps
    _speak_cancelled at the new id and the drain drops the reply.
    """
    from arelis.ui.event_host import dispatch_event
    from arelis.voice import VoiceService

    withdrawn = "72 Fahrenheit is 22 degrees."
    reply = "That works out to 27.22."
    bus = EventBus()
    played: list[str] = []

    async def _capture(event: Event) -> None:
        if event.type == EventType.VOICE_AUDIO_READY:
            played.append(str(event.payload.get("text") or ""))

    bus.subscribe(None, _capture)
    voice = VoiceService(
        bus, {"voice": {"enabled": True, "tts": {"enabled": True, "backend": "piper"}}}
    )
    voice.speak_enabled = True
    fake = _SlowTTS()
    voice.tts = fake  # type: ignore[assignment]
    window = _Window(voice)
    task = asyncio.create_task(bus.run())
    bus.publish_nowait(Event(EventType.ASSISTANT_DELTA, {"text": withdrawn}))
    await fake.entered.wait()
    bus.publish_nowait(Event(EventType.ASSISTANT_RETRACT, {}))
    bus.publish_nowait(Event(EventType.ASSISTANT_DELTA, {"text": reply}))
    queued = False
    for _ in range(100):
        if any(sentence == reply for sentence, _final in voice._pending):
            queued = True
            break
        await asyncio.sleep(0)
    assert queued, "replacement was not queued before the late glass retract"
    replacement_id = voice._stream_utterance
    assert replacement_id > voice._speak_cancelled
    dispatch_event(window, Event(EventType.ASSISTANT_RETRACT, {}))
    assert window.speech_player.stopped == 1
    assert voice._speak_cancelled < replacement_id
    fake.release.set()
    await bus.drain()
    bus.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert reply in fake.spoken
    assert played == [reply]
