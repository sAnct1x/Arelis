"""Confirm card copy, speech yes/no, and browser grants."""

from __future__ import annotations

import asyncio

import pytest

from arelis.config import PROJECT_ROOT
from arelis.core.bus import EventBus
from arelis.core.confirm_speech import (
    apply_confirm_edit,
    classify_confirm_utterance,
    classify_hangup,
    classify_voice_act,
    stopped_ask_note,
)
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.core.preflight import user_asked_for_browser
from arelis.tools.base import ToolRegistry
from arelis.tools.confirm_copy import confirm_headline


def test_headlines_are_human() -> None:
    assert confirm_headline("send_sms", {"to": "wife", "body": "On my way"}) == "text wife"
    assert confirm_headline("workspace", {"action": "write", "path": "data/note.txt"}) == (
        "write note.txt"
    )
    assert confirm_headline("browser", {"action": "open", "url": "youtube"}) == "open youtube"
    assert confirm_headline("plot", {}) == "write a plot"
    assert confirm_headline("plot", {"out": "residuals.png"}) == "write residuals.png"
    assert confirm_headline("solar", {"action": "dump"}) == "dump solar state"
    assert confirm_headline("document", {"format": "pdf"}) == "write a pdf"
    assert confirm_headline("document", {"filename": "dirac.pdf"}) == "write dirac.pdf"
    assert "`" not in confirm_headline("send_email", {"to": "me", "subject": "Hi"})


def test_yes_no_lists() -> None:
    assert classify_confirm_utterance("allow") == "allow"
    assert classify_confirm_utterance("yes") == "allow"
    assert classify_confirm_utterance("go ahead") == "allow"
    assert classify_confirm_utterance("deny") == "skip"
    assert classify_confirm_utterance("no") == "skip"
    assert classify_confirm_utterance("don't") == "skip"
    assert classify_confirm_utterance("stop") == "stop"
    assert classify_confirm_utterance("rest of this ask") == "allow_turn"
    assert classify_confirm_utterance("") is None
    assert classify_confirm_utterance("I don't know") is None
    assert classify_confirm_utterance("text wife I'm late") is None
    assert classify_voice_act("keep going") == "allow"
    assert classify_voice_act("continue") == "allow"
    assert classify_voice_act("I wasn't talking to you") is None
    assert classify_voice_act("not you Arelis") is None
    assert classify_voice_act("quit") is None
    assert classify_voice_act("I don't know") is None
    assert classify_voice_act("be quiet") == "stop"
    assert classify_voice_act("shut up") == "stop"
    assert classify_voice_act("stop talking") == "stop"
    assert classify_voice_act("goodbye") is None
    assert classify_hangup("goodbye")
    assert classify_hangup("bye")
    assert classify_hangup("that's all")
    assert classify_hangup("stop listening")
    assert classify_hangup("go to sleep")
    assert classify_hangup("we're done")
    assert not classify_hangup("stop")
    assert not classify_hangup("stop talking")
    assert not classify_hangup("tell her goodbye")
    assert not classify_hangup("that's all I needed")


def test_stopped_ask_note_is_one_fact() -> None:
    note = stopped_ask_note("text wife I'm late")
    assert "text wife I'm late" in note
    assert "stopped" in note.lower()
    assert stopped_ask_note("  ") == ""


def test_spoken_draft_edit_changes_sms_body() -> None:
    args = {"to": "wife", "body": "On my way"}
    assert apply_confirm_edit("send_sms", args, "No, tell her I'll be late")
    assert args["to"] == "wife"
    assert args["body"] == "I'll be late"


def test_a_clock_ask_is_not_a_draft_edit() -> None:
    args = {"to": "wife", "body": "On my way"}
    assert not apply_confirm_edit("send_sms", args, "what time is it")
    assert args["body"] == "On my way"


def test_spoken_draft_edit_changes_email_body() -> None:
    args = {"to": "me", "subject": "Hi", "body": "Old"}
    assert apply_confirm_edit("send_email", args, "make it running late")
    assert args["body"] == "running late"
    assert args["subject"] == "Hi"


def test_a_commanded_drive_is_the_grant() -> None:
    assert user_asked_for_browser("open youtube")
    assert user_asked_for_browser("go to github.com")
    assert user_asked_for_browser("click sign in")
    assert not user_asked_for_browser(
        "Summarize the article at https://spa.example/app"
    )


def test_card_says_deny_not_skip(qt_app) -> None:
    from arelis.ui.panels.confirm import ConfirmCard

    card = ConfirmCard()
    try:
        card.ask(
            "c1",
            "send_sms",
            "send_sms(to=wife)",
            detail="To: wife\n\nOn my way",
            headline="text wife",
        )
        assert card.allow_btn.text() == "allow"
        assert card.skip_btn.text() == "deny"
        assert card.summary.text() == "text wife"
        assert "send_sms" not in card.summary.text()
        assert "allow `" not in card.summary.text()
    finally:
        card.deleteLater()


def test_typed_no_denies_the_card(qt_app) -> None:
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    decided: list[str] = []
    try:
        stage.confirm_decided.connect(
            lambda _id, decision, _batch: decided.append(decision)
        )
        stage.ask_confirm("c1", "send_sms", "send_sms()", headline="text wife")
        stage.input.setText("no")
        stage._submit()
        assert decided == ["skip"]
        assert not stage.confirm_open()
        assert stage.input.text() == ""
    finally:
        stage.deleteLater()


def test_empty_enter_still_allows(qt_app) -> None:
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    decided: list[str] = []
    try:
        stage.confirm_decided.connect(
            lambda _id, decision, _batch: decided.append(decision)
        )
        stage.ask_confirm("c1", "workspace", "workspace()", headline="write note.txt")
        stage._submit()
        assert decided == ["allow"]
    finally:
        stage.deleteLater()


class _StubRouter:
    default_role = "fast"
    active_model = None
    models = {"fast": "mock"}

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
        if False:
            yield ("token", "")
        return

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_spoken_allow_resolves_the_waiter() -> None:
    bus = EventBus()
    seen: list[Event] = []

    async def capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(None, capture)
    orch = Orchestrator(
        bus,
        _StubRouter(),  # type: ignore[arg-type]
        ToolRegistry(),
        {
            "agent": {"confirm_timeout_s": 30},
            "workspace": {"roots": ["."]},
            "_persona_path": str(PROJECT_ROOT / "arelis" / "persona" / "arelis.md"),
            "_speak_replies": True,
        },
        SessionMemory(),
    )
    fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
    orch._confirm_waiters["c-voice"] = fut
    bus_task = asyncio.create_task(bus.run())
    try:
        await bus.publish(Event(EventType.VOICE_TRANSCRIPT, {"text": "allow"}))
        await bus.drain()
        decision = await asyncio.wait_for(fut, timeout=2)
    finally:
        bus.stop()
        bus_task.cancel()
    assert decision == "allow"
    assert not any(e.type == EventType.USER_MESSAGE for e in seen)
    assert any(
        e.type == EventType.TOOL_CONFIRM_REPLY
        and e.payload.get("reason") == "voice"
        for e in seen
    )


@pytest.mark.asyncio
async def test_spoken_other_is_not_a_turn_while_the_card_is_open() -> None:
    bus = EventBus()
    seen: list[Event] = []

    async def capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(None, capture)
    orch = Orchestrator(
        bus,
        _StubRouter(),  # type: ignore[arg-type]
        ToolRegistry(),
        {
            "agent": {"confirm_timeout_s": 30},
            "workspace": {"roots": ["."]},
            "_persona_path": str(PROJECT_ROOT / "arelis" / "persona" / "arelis.md"),
            "_speak_replies": True,
        },
        SessionMemory(),
    )
    fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
    orch._confirm_waiters["c-voice"] = fut
    bus_task = asyncio.create_task(bus.run())
    try:
        await bus.publish(
            Event(EventType.VOICE_TRANSCRIPT, {"text": "what time is it"})
        )
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
    assert not fut.done()
    assert not any(e.type == EventType.USER_MESSAGE for e in seen)


def _voice_orch(bus: EventBus) -> Orchestrator:
    return Orchestrator(
        bus,
        _StubRouter(),  # type: ignore[arg-type]
        ToolRegistry(),
        {
            "agent": {"confirm_timeout_s": 30},
            "workspace": {"roots": ["."]},
            "_persona_path": str(PROJECT_ROOT / "arelis" / "persona" / "arelis.md"),
            "_speak_replies": True,
        },
        SessionMemory(),
    )


@pytest.mark.asyncio
async def test_spoken_stop_cancels_and_is_not_a_turn() -> None:
    bus = EventBus()
    seen: list[Event] = []

    async def capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(None, capture)
    orch = _voice_orch(bus)
    bus_task = asyncio.create_task(bus.run())
    try:
        assert orch.config.get("_speak_replies")
        await bus.publish(Event(EventType.VOICE_TRANSCRIPT, {"text": "stop"}))
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
    assert any(e.type == EventType.TURN_CANCEL for e in seen)
    assert not any(e.type == EventType.USER_MESSAGE for e in seen)


@pytest.mark.asyncio
async def test_keep_going_after_stop_is_ordinary_talk() -> None:
    bus = EventBus()
    seen: list[Event] = []

    async def capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(None, capture)
    orch = _voice_orch(bus)
    orch._stopped_ask = {"text": "text wife I'm late", "role": "fast", "source": "voice"}

    async def _no_turn(*_a, **_k):
        return None

    orch._run_turn = _no_turn  # type: ignore[method-assign]
    bus_task = asyncio.create_task(bus.run())
    try:
        await bus.publish(Event(EventType.VOICE_TRANSCRIPT, {"text": "keep going"}))
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
    messages = [e for e in seen if e.type == EventType.USER_MESSAGE]
    assert messages
    assert messages[0].payload.get("text") == "keep going"


@pytest.mark.asyncio
async def test_wasnt_talking_to_you_is_ordinary_talk() -> None:
    bus = EventBus()
    seen: list[Event] = []

    async def capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(None, capture)
    orch = _voice_orch(bus)
    orch._stopped_ask = {"text": "search the weather", "source": "voice"}

    async def _no_turn(*_a, **_k):
        return None

    orch._run_turn = _no_turn  # type: ignore[method-assign]
    bus_task = asyncio.create_task(bus.run())
    try:
        await bus.publish(
            Event(EventType.VOICE_TRANSCRIPT, {"text": "I wasn't talking to you"})
        )
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
    messages = [e for e in seen if e.type == EventType.USER_MESSAGE]
    assert messages
    assert messages[0].payload.get("text") == "I wasn't talking to you"


@pytest.mark.asyncio
async def test_spoken_sms_edit_refreshes_the_card() -> None:
    bus = EventBus()
    seen: list[Event] = []

    async def capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(None, capture)
    orch = _voice_orch(bus)
    args = {"to": "wife", "body": "On my way"}
    fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
    orch._confirm_waiters["c-edit"] = fut
    orch._confirm_live["c-edit"] = {
        "tool": "send_sms",
        "args": args,
        "summary": "send_sms()",
    }
    bus_task = asyncio.create_task(bus.run())
    try:
        await bus.publish(
            Event(EventType.VOICE_TRANSCRIPT, {"text": "tell her I'll be late"})
        )
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
    assert args["body"] == "I'll be late"
    assert not fut.done()
    assert not any(e.type == EventType.USER_MESSAGE for e in seen)
    assert any(
        e.type == EventType.TOOL_CONFIRM and e.payload.get("reason") == "voice_edit"
        for e in seen
    )


@pytest.mark.asyncio
async def test_control_soup_is_not_a_turn() -> None:
    bus = EventBus()
    seen: list[Event] = []

    async def capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(None, capture)
    orch = _voice_orch(bus)
    bus_task = asyncio.create_task(bus.run())
    try:
        await bus.publish(
            Event(
                EventType.VOICE_TRANSCRIPT,
                {"text": "thank you for watching", "deliver": "control"},
            )
        )
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
    assert not any(e.type == EventType.USER_MESSAGE for e in seen)
    assert not any(e.type == EventType.TURN_CANCEL for e in seen)


@pytest.mark.asyncio
async def test_control_stop_cancels() -> None:
    bus = EventBus()
    seen: list[Event] = []

    async def capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(None, capture)
    orch = _voice_orch(bus)
    bus_task = asyncio.create_task(bus.run())
    try:
        await bus.publish(
            Event(EventType.VOICE_TRANSCRIPT, {"text": "stop", "deliver": "control"})
        )
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
    assert any(e.type == EventType.TURN_CANCEL for e in seen)


@pytest.mark.asyncio
async def test_spoken_goodbye_hangs_up_and_is_not_a_turn() -> None:
    bus = EventBus()
    seen: list[Event] = []

    async def capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(None, capture)
    _voice_orch(bus)
    bus_task = asyncio.create_task(bus.run())
    try:
        await bus.publish(Event(EventType.VOICE_TRANSCRIPT, {"text": "goodbye"}))
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
    assert any(e.type == EventType.CONVERSATION_END for e in seen)
    assert not any(e.type == EventType.USER_MESSAGE for e in seen)
    assert not any(e.type == EventType.TURN_CANCEL for e in seen)


@pytest.mark.asyncio
async def test_goodbye_on_a_confirm_card_is_not_hangup() -> None:
    bus = EventBus()
    seen: list[Event] = []

    async def capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(None, capture)
    orch = _voice_orch(bus)
    fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
    orch._confirm_waiters["c-bye"] = fut
    bus_task = asyncio.create_task(bus.run())
    try:
        await bus.publish(Event(EventType.VOICE_TRANSCRIPT, {"text": "goodbye"}))
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
    assert not any(e.type == EventType.CONVERSATION_END for e in seen)
    assert not any(e.type == EventType.USER_MESSAGE for e in seen)
    assert not fut.done()


def test_typed_stop_on_a_card_requests_stop(qt_app) -> None:
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    stops: list[int] = []
    try:
        stage.stop_requested.connect(lambda: stops.append(1))
        stage.ask_confirm("c1", "send_sms", "send_sms()", headline="text wife")
        stage.input.setText("stop")
        stage._submit()
        assert stops == [1]
        assert stage.input.text() == ""
    finally:
        stage.deleteLater()


def test_wake_yes_without_hey_is_not_a_decision() -> None:
    from arelis.voice.wake import classify_wake

    miss = classify_wake("yes")
    assert miss.matched is False
