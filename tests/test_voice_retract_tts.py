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


def _long_sentence(name: str) -> str:
    # Over the 160-char pack target so each sentence is its own clip.
    return (
        f"{name} is a fascinating icy moon with a long scientific story that "
        f"people keep telling because the details are actually worth hearing "
        f"out loud before anything else changes."
    )


class _FastTTS:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    def problem(self) -> None:
        return None

    async def synthesize(self, text: str, out: Path, language: str = "") -> Path:
        self.spoken.append(text)
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"RIFF")
        return path


async def _wait_clips(played: list[str], count: int) -> None:
    for _ in range(200):
        if len(played) >= count:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"expected {count} clips, have {played!r}")


def _chunks(text: str, size: int = 20) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


async def _setup() -> tuple[EventBus, object, _FastTTS, list[str], asyncio.Task[None]]:
    from arelis.voice import VoiceService

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
    fake = _FastTTS()
    voice.tts = fake  # type: ignore[assignment]
    task = asyncio.create_task(bus.run())
    return bus, voice, fake, played, task


@pytest.mark.asyncio
async def test_replacement_skips_sentences_already_heard() -> None:
    """#294: a restated replacement must not replay sentences already heard.

    Retract still drops the live buffer so withdrawn text is not glued on.
    A token-streamed restatement is checked on every queue, not only the
    first sentence. A dead turn (error or cancel) drops the heard prefix
    so the next turn that starts with the same sentence still speaks it.
    """
    first = _long_sentence("Titan")
    second = _long_sentence("Europa")
    third = _long_sentence("Enceladus")
    xenon = _long_sentence("Xenon")
    prefix = f"{first} {second}"
    full = f"{first} {second} {third}"
    mid = f"{first} {xenon} {third}"
    first_changed = f"{xenon} {second} {third}"
    next_pair = f"{first} {third}"

    bus, _voice, fake, played, task = await _setup()

    # Path: speak two sentences, withdraw, stream the restatement in chunks.
    bus.publish_nowait(Event(EventType.ASSISTANT_DELTA, {"text": prefix}))
    await _wait_clips(played, 2)
    assert played == [first, second]
    bus.publish_nowait(Event(EventType.ASSISTANT_RETRACT, {}))
    for piece in _chunks(full):
        bus.publish_nowait(Event(EventType.ASSISTANT_DELTA, {"text": piece}))
    bus.publish_nowait(Event(EventType.VOICE_SPEAK, {"text": full}))
    await bus.drain()
    assert played == [first, second, third]
    assert fake.spoken == [first, second, third]

    # Path: retract, then VOICE_SPEAK with no new delta. Same skip, other entry.
    played.clear()
    fake.spoken.clear()
    bus.publish_nowait(Event(EventType.ASSISTANT_DELTA, {"text": prefix}))
    await _wait_clips(played, 2)
    bus.publish_nowait(Event(EventType.ASSISTANT_RETRACT, {}))
    await bus.drain()
    bus.publish_nowait(Event(EventType.VOICE_SPEAK, {"text": full}))
    await bus.drain()
    assert played == [first, second, third]
    assert fake.spoken == [first, second, third]

    # Path: stream reset after speak. The next turn still says the first line.
    played.clear()
    fake.spoken.clear()
    bus.publish_nowait(Event(EventType.ASSISTANT_DELTA, {"text": first}))
    bus.publish_nowait(Event(EventType.VOICE_SPEAK, {"text": first}))
    await bus.drain()
    assert played == [first]

    # Path: ERROR retract must not silence the next turn's first sentence.
    played.clear()
    fake.spoken.clear()
    bus.publish_nowait(Event(EventType.ASSISTANT_DELTA, {"text": prefix}))
    await _wait_clips(played, 2)
    bus.publish_nowait(Event(EventType.ERROR, {"message": "the model failed"}))
    await bus.drain()
    played.clear()
    fake.spoken.clear()
    bus.publish_nowait(Event(EventType.ASSISTANT_DELTA, {"text": first}))
    bus.publish_nowait(Event(EventType.VOICE_SPEAK, {"text": first}))
    await bus.drain()
    assert played == [first]

    # mid_change: A B heard, replacement A X C continues from the new middle.
    played.clear()
    fake.spoken.clear()
    bus.publish_nowait(Event(EventType.ASSISTANT_DELTA, {"text": prefix}))
    await _wait_clips(played, 2)
    bus.publish_nowait(Event(EventType.ASSISTANT_RETRACT, {}))
    for piece in _chunks(mid):
        bus.publish_nowait(Event(EventType.ASSISTANT_DELTA, {"text": piece}))
    bus.publish_nowait(Event(EventType.VOICE_SPEAK, {"text": mid}))
    await bus.drain()
    assert played == [first, second, xenon, third]

    # first_change: A B heard, replacement X B C is new from the start.
    played.clear()
    fake.spoken.clear()
    bus.publish_nowait(Event(EventType.ASSISTANT_DELTA, {"text": prefix}))
    await _wait_clips(played, 2)
    bus.publish_nowait(Event(EventType.ASSISTANT_RETRACT, {}))
    for piece in _chunks(first_changed):
        bus.publish_nowait(Event(EventType.ASSISTANT_DELTA, {"text": piece}))
    bus.publish_nowait(Event(EventType.VOICE_SPEAK, {"text": first_changed}))
    await bus.drain()
    assert played == [first, second, xenon, second, third]

    # two_turns_same_start: A B, then a new turn A C speaks both.
    played.clear()
    fake.spoken.clear()
    bus.publish_nowait(Event(EventType.ASSISTANT_DELTA, {"text": prefix}))
    await _wait_clips(played, 2)
    bus.publish_nowait(Event(EventType.VOICE_SPEAK, {"text": prefix}))
    await bus.drain()
    played.clear()
    fake.spoken.clear()
    for piece in _chunks(next_pair):
        bus.publish_nowait(Event(EventType.ASSISTANT_DELTA, {"text": piece}))
    bus.publish_nowait(Event(EventType.VOICE_SPEAK, {"text": next_pair}))
    await bus.drain()
    assert played == [first, third]

    # draft_then_cancel_next_turn: withdrawn draft, then cancel, then A B.
    played.clear()
    fake.spoken.clear()
    bus.publish_nowait(Event(EventType.ASSISTANT_DELTA, {"text": f"{first} "}))
    await _wait_clips(played, 1)
    bus.publish_nowait(
        Event(EventType.TOOL_START, {"draft_speech": True, "name": "x"})
    )
    await bus.drain()
    bus.publish_nowait(Event(EventType.TURN_CANCEL, {}))
    await bus.drain()
    played.clear()
    fake.spoken.clear()
    for piece in _chunks(prefix):
        bus.publish_nowait(Event(EventType.ASSISTANT_DELTA, {"text": piece}))
    bus.publish_nowait(Event(EventType.VOICE_SPEAK, {"text": prefix}))
    await bus.drain()
    assert played == [first, second]

    # draft_then_cancel_repeat_speak: retract, cancel, VOICE_SPEAK A B.
    played.clear()
    fake.spoken.clear()
    bus.publish_nowait(Event(EventType.ASSISTANT_DELTA, {"text": f"{first} "}))
    await _wait_clips(played, 1)
    bus.publish_nowait(Event(EventType.ASSISTANT_RETRACT, {}))
    await bus.drain()
    bus.publish_nowait(Event(EventType.TURN_CANCEL, {}))
    await bus.drain()
    played.clear()
    fake.spoken.clear()
    bus.publish_nowait(Event(EventType.VOICE_SPEAK, {"text": prefix}))
    await bus.drain()
    assert played == [first, second]

    bus.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
