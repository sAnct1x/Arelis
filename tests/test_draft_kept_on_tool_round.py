"""A painted draft stays in the chat when a tool round starts.

Issue 372. dispatch_calls used to retract streamed prose as soon as the
round had tool calls. The bubble disappeared, and TOOL_START only added
the errand to the collapsed thought, so the chat was empty until the
tool finished. The draft has to still be on screen after TOOL_START and
before TOOL_RESULT.

QT_QPA_PLATFORM=offscreen. The wait is QTest.qWaitFor from the qt_app
fixture, which pumps events until the paint lands.
"""

from __future__ import annotations

import asyncio
import os
import threading
from types import SimpleNamespace
from typing import Any

from PySide6.QtTest import QTest

from arelis.core.agent_loop import AgentLoop
from arelis.core.events import Event, EventType
from arelis.core.turn_dispatch import dispatch_calls
from tests.test_no_call_path import _ctx, _FakeLoop, _scratch
from tests.test_round_scratch import _augment

_CHUNK = "The harbor light stays on while this tool runs. "
_TOKEN = "draft-stays-372"


def _draft() -> str:
    text = _CHUNK * 8 + _TOKEN
    assert len(text) >= 300
    return text


def _thought_lines(window: Any) -> str:
    lines: list[str] = []
    for thought in window.chat._thoughts:
        lines.extend(thought.lines)
    return "\n".join(lines)


def _start_bus(window: Any) -> threading.Thread:
    thread = threading.Thread(
        target=window.loop.run_forever,
        name="draft-kept-bus",
        daemon=True,
    )
    thread.start()
    for _ in range(100):
        if window.loop.is_running():
            break
        thread.join(0.01)
    if not window.loop.is_running():
        raise RuntimeError("event loop did not start")

    async def _boot() -> None:
        asyncio.get_running_loop().create_task(window.bus.run())

    asyncio.run_coroutine_threadsafe(_boot(), window.loop).result(timeout=2)
    return thread


def _stop_bus(window: Any, thread: threading.Thread) -> None:
    loop = window.loop
    if thread.ident is None:
        return
    if loop.is_running():

        async def _halt() -> None:
            current = asyncio.current_task()
            pending = [task for task in asyncio.all_tasks() if task is not current]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        try:
            asyncio.run_coroutine_threadsafe(_halt(), loop).result(timeout=5)
        except Exception:
            pass
        loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)


def test_draft_stays_in_the_chat_through_tool_start(arelis_window, qt_app) -> None:
    """Paint a few hundred characters, run the tool round, and keep the draft.

    The tool call blocks until this assertion, so TOOL_RESULT has not been
    published yet. Restoring the retract in dispatch_calls fails this test.
    """
    assert os.environ.get("QT_QPA_PLATFORM") == "offscreen"
    draft = _draft()
    token = _TOKEN
    window = arelis_window()
    window.show()
    qt_app.processEvents()
    window._set_busy(True)

    seen: list[EventType] = []
    tool_starts: list[dict[str, Any]] = []

    async def _mirror(event: Event) -> None:
        seen.append(event.type)
        if event.type == EventType.TOOL_START:
            tool_starts.append(dict(event.payload))
        window.bridge.feed(event)

    window.bus.subscribe(None, _mirror)
    thread = _start_bus(window)
    release = asyncio.Event()
    holder: dict[str, Any] = {}
    fut = None
    body_ok = False
    try:
        window.bridge.event_arrived.emit(
            Event(EventType.ASSISTANT_DELTA, {"text": draft})
        )
        assert QTest.qWaitFor(
            lambda: token in window.chat.view.toPlainText(),
            3000,
        ), "draft never painted"

        loop = _augment(_FakeLoop())
        loop.bus = window.bus
        # The glass painted the delta. The loop only retracts when it
        # believes that same text is on screen.
        loop._painted = draft

        async def _retract() -> None:
            await AgentLoop._retract(loop)

        loop._retract = _retract

        async def _call(name: str, **kwargs: Any) -> Any:
            del name, kwargs
            await release.wait()
            return SimpleNamespace(ok=True, output="Boston is clear.", data={})

        loop.tools.call = _call
        r = _scratch(
            text="what is the weather in Boston",
            calls=[("weather", {"place": "Boston"})],
            content=draft,
            streamed=draft,
            tool_names={"weather"},
            available={"weather"},
            visible={"weather"},
            available_all={"weather"},
            calls_from_text=False,
        )
        r.agent_cfg["read_fanout"] = False
        ctx = _ctx(text=r.text)
        ctx.tool_names = r.tool_names

        async def _go() -> None:
            try:
                holder["result"] = await dispatch_calls(loop, ctx, r, 1)
            except Exception as exc:
                holder["error"] = exc
                release.set()
                raise

        fut = asyncio.run_coroutine_threadsafe(_go(), window.loop)

        def _kept() -> bool:
            if token not in window.chat.view.toPlainText():
                return False
            return "checking the weather" in _thought_lines(window)

        stayed = QTest.qWaitFor(_kept, 5000)
        assert stayed, (
            "draft left the chat before the tool result, or the tool never started; "
            f"token_in_chat={token in window.chat.view.toPlainText()} "
            f"stream_open={window.chat._stream_open} "
            f"thoughts={_thought_lines(window)!r} "
            f"events={[item.value for item in list(seen)]} "
            f"error={holder.get('error')!r}"
        )
        assert EventType.TOOL_RESULT not in list(seen)
        assert EventType.ASSISTANT_RETRACT not in list(seen)
        assert window.chat._stream_open
        assert token in "".join(window.chat._stream_text)
        progress = window.chat.progress.text().lower()
        assert "checking the weather" not in progress
        assert window.chat.progress.isHidden()
        assert tool_starts and tool_starts[0].get("draft_speech") is True

        # The next round's text must not glue onto the kept draft.
        loop._round_gap = True

        async def _publish_delta(text: str) -> None:
            await AgentLoop._publish_delta(loop, text)

        loop._publish_delta = _publish_delta

        async def _gap() -> None:
            await AgentLoop._publish_round_text(loop, "Boston is clear.")

        gap_fut = asyncio.run_coroutine_threadsafe(_gap(), window.loop)
        gap_fut.result(timeout=5)
        gap = f"{token}\n\nBoston is clear."
        assert QTest.qWaitFor(
            lambda: gap in "".join(window.chat._stream_text),
            3000,
        ), "".join(window.chat._stream_text)

        # A call parsed from the text still retracts. The flag is the
        # source. Release the native call first so the two rounds do not
        # share one blocked tool.
        if window.loop.is_running():
            window.loop.call_soon_threadsafe(release.set)
        if fut is not None:
            fut.result(timeout=15)
        fut = None

        text_mark = len(seen)
        release2 = asyncio.Event()

        async def _call_text(name: str, **kwargs: Any) -> Any:
            del name, kwargs
            await release2.wait()
            return SimpleNamespace(ok=True, output="still blocked", data={})

        loop.tools.call = _call_text
        loop._painted = draft
        r.calls_from_text = True
        r.calls = [("weather", {"place": "Austin"})]
        r.streamed = draft
        release = release2

        async def _go_text() -> None:
            try:
                holder["text_result"] = await dispatch_calls(loop, ctx, r, 2)
            except Exception as exc:
                holder["error"] = exc
                release2.set()
                raise

        fut = asyncio.run_coroutine_threadsafe(_go_text(), window.loop)

        def _retracted() -> bool:
            if token in window.chat.view.toPlainText():
                return False
            return EventType.ASSISTANT_RETRACT in seen[text_mark:]

        went = QTest.qWaitFor(_retracted, 5000)
        assert went, (
            "text-parsed call left the draft up; "
            f"token_in_chat={token in window.chat.view.toPlainText()} "
            f"events={[item.value for item in seen[text_mark:]]} "
            f"error={holder.get('error')!r}"
        )
        assert EventType.TOOL_RESULT not in seen[text_mark:]

        from arelis.voice import VoiceService

        async def _voice_scope() -> None:
            voice = VoiceService(
                window.bus,
                {
                    "voice": {
                        "enabled": True,
                        "stt": {"enabled": False},
                        "tts": {
                            "enabled": True,
                            "backend": "piper",
                            "allow_download": False,
                        },
                    }
                },
            )
            voice.speak_enabled = True
            voice._stream_open = True
            voice._stream_raw = "earlier reply still talking"
            voice._speak_seq = 4
            await voice.on_tool_start(
                Event(EventType.TOOL_START, {"tool": "sms", "args": {}})
            )
            assert voice._stream_open
            assert voice._stream_raw == "earlier reply still talking"
            voice.config["_phone_turn"] = True
            await voice.on_tool_start(
                Event(
                    EventType.TOOL_START,
                    {"tool": "weather", "args": {}, "draft_speech": True},
                )
            )
            assert voice._stream_open
            voice.config["_phone_turn"] = False
            await voice.on_tool_start(
                Event(
                    EventType.TOOL_START,
                    {
                        "tool": "weather",
                        "args": {"place": "Boston"},
                        "draft_speech": True,
                    },
                )
            )
            assert voice._stream_open is False
            assert voice._stream_raw == ""
            assert voice._speak_cancelled == 4

        voice_fut = asyncio.run_coroutine_threadsafe(_voice_scope(), window.loop)
        voice_fut.result(timeout=5)
        body_ok = True
    finally:
        if window.loop.is_running():
            window.loop.call_soon_threadsafe(release.set)
        if fut is not None:
            try:
                fut.result(timeout=15)
            except Exception:
                if body_ok:
                    raise
        _stop_bus(window, thread)
        window._set_busy(False)
