"""Confirm card copy, speech yes/no, and browser grants."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from arelis.config import PROJECT_ROOT
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.tools.base import ToolRegistry
from arelis.workspace import WorkspaceRoots


def test_send_card_hides_persist_and_batch(qt_app) -> None:
    from arelis.ui.panels.confirm import ConfirmCard

    card = ConfirmCard()
    try:
        card.ask(
            "c1",
            "send_sms",
            "send_sms(to=wife)",
            detail="To: wife\n\nOn my way",
            headline="text wife",
            batch_ok=False,
            persist_ok=False,
        )
        assert not card.allow_always.isVisible()
        assert not card.allow_turn.isVisible()
    finally:
        card.deleteLater()


def test_wander_image_offers_persist(qt_app) -> None:
    from arelis.ui.panels.confirm import ConfirmCard

    card = ConfirmCard()
    decided: list[tuple[str, bool]] = []
    try:
        card.decided.connect(lambda _id, decision, batch: decided.append((decision, batch)))
        card.ask(
            "c1",
            "image",
            "image(prompt=jellyfish)",
            headline="draw a jellyfish",
            batch_ok=True,
            persist_ok=True,
            persist_label="don't ask again about pictures",
        )
        assert card.allow_always.isVisible()
        assert card.allow_always.text() == "don't ask again about pictures"
        assert card.allow_turn.isVisible()
        card.allow_always.setChecked(True)
        card.allow_turn.setChecked(True)
        card._allow()
        assert decided == [("allow_always", False)]
    finally:
        card.deleteLater()


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
async def test_spoken_allow_resolves_the_newer_card() -> None:
    """Two pending cards: spoken allow hits the one on screen."""
    bus = EventBus()
    seen: list[Event] = []

    async def capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(None, capture)
    orch = _voice_orch(bus)
    older: asyncio.Task[str] | None = None
    newer: asyncio.Task[str] | None = None
    bus_task = asyncio.create_task(bus.run())
    try:
        older = asyncio.create_task(orch._request_confirm("c-old", "plot", {}, "older"))
        newer = asyncio.create_task(orch._request_confirm("c-new", "plot", {}, "newer"))
        for _ in range(50):
            if "c-old" in orch._confirm_waiters and "c-new" in orch._confirm_waiters:
                break
            await asyncio.sleep(0)
        else:
            raise AssertionError("both confirm waiters did not register")
        old_fut = orch._confirm_waiters["c-old"]
        await bus.publish(Event(EventType.VOICE_TRANSCRIPT, {"text": "allow"}))
        await bus.drain()
        decision = await asyncio.wait_for(newer, timeout=2)
        assert decision == "allow"
        assert not old_fut.done()
        assert any(
            e.type == EventType.TOOL_CONFIRM_REPLY
            and e.payload.get("id") == "c-new"
            and e.payload.get("reason") == "voice"
            for e in seen
        )
        assert not any(
            e.type == EventType.TOOL_CONFIRM_REPLY and e.payload.get("id") == "c-old"
            for e in seen
        )
    finally:
        pending = [task for task in (older, newer) if task is not None and not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        bus.stop()
        bus_task.cancel()


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


def _silent_orch(bus: EventBus) -> Orchestrator:
    return Orchestrator(
        bus,
        _StubRouter(),  # type: ignore[arg-type]
        ToolRegistry(),
        {
            "agent": {"confirm_timeout_s": 30},
            "workspace": {"roots": ["."]},
            "_persona_path": str(PROJECT_ROOT / "arelis" / "persona" / "arelis.md"),
        },
        SessionMemory(),
    )


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


@pytest.mark.asyncio
async def test_second_message_waits_out_the_external_allow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Message 2 must not paint an Allow while message 1 is parked on one."""
    root = tmp_path / "proj"
    root.mkdir()
    outside_a = tmp_path / "one.txt"
    outside_b = tmp_path / "two.txt"
    outside_a.write_text("one", encoding="utf-8")
    outside_b.write_text("two", encoding="utf-8")
    workspace = WorkspaceRoots.from_paths([str(root)])

    async def _quiet_run(self, *args, **kwargs):
        self.terminal_sent = True

    monkeypatch.setattr(AgentLoop, "run", _quiet_run)

    bus = EventBus()
    orch = Orchestrator(
        bus,
        _StubRouter(),  # type: ignore[arg-type]
        ToolRegistry(),
        {
            "agent": {"confirm_timeout_s": 30},
            "workspace": {"roots": [str(root)]},
            "_persona_path": str(PROJECT_ROOT / "arelis" / "persona" / "arelis.md"),
        },
        SessionMemory(),
        workspace=workspace,
    )
    first: asyncio.Task[None] | None = None
    second: asyncio.Task[None] | None = None
    try:
        first = asyncio.create_task(
            orch.on_user_message(
                Event(EventType.USER_MESSAGE, {"text": f"Read {outside_a}"})
            )
        )
        for _ in range(100):
            if orch._confirm_live:
                break
            await asyncio.sleep(0)
        assert len(orch._confirm_live) == 1
        assert Path(next(iter(orch._confirm_live.values()))["args"]["path"]) == outside_a.resolve()

        second = asyncio.create_task(
            orch.on_user_message(
                Event(EventType.USER_MESSAGE, {"text": f"Read {outside_b}"})
            )
        )
        for _ in range(100):
            if orch._turn_lock._waiters:
                break
            await asyncio.sleep(0)
        # Queued on the turn lock, still inside message 1's Allow.
        assert orch._turn_lock.locked()
        assert orch._turn_lock._waiters
        assert len(orch._confirm_live) == 1
        assert not orch.workspace.has_external_read(outside_b)

        next(iter(orch._confirm_waiters.values())).set_result("allow")
        await asyncio.wait_for(first, timeout=2)
        assert orch.workspace.has_external_read(outside_a)

        for _ in range(100):
            if orch._confirm_live and not second.done():
                break
            await asyncio.sleep(0)
        assert len(orch._confirm_live) == 1
        assert not second.done()
        assert Path(next(iter(orch._confirm_live.values()))["args"]["path"]) == outside_b.resolve()
        next(iter(orch._confirm_waiters.values())).set_result("skip")
        await asyncio.wait_for(second, timeout=2)
        assert not orch.workspace.has_external_read(outside_b)
    finally:
        pending = [task for task in (first, second) if task is not None and not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
