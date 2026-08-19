"""Confirm card copy, speech yes/no, and browser grants."""

from __future__ import annotations

import asyncio

import pytest

from arelis.config import PROJECT_ROOT
from arelis.core.bus import EventBus
from arelis.core.confirm_speech import classify_confirm_utterance
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
    assert "`" not in confirm_headline("send_email", {"to": "me", "subject": "Hi"})


def test_yes_no_lists() -> None:
    assert classify_confirm_utterance("allow") == "allow"
    assert classify_confirm_utterance("yes") == "allow"
    assert classify_confirm_utterance("go ahead") == "allow"
    assert classify_confirm_utterance("deny") == "skip"
    assert classify_confirm_utterance("no") == "skip"
    assert classify_confirm_utterance("don't") == "skip"
    assert classify_confirm_utterance("") is None
    assert classify_confirm_utterance("I don't know") is None
    assert classify_confirm_utterance("text wife I'm late") is None


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
