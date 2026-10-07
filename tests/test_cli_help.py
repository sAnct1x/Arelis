"""The CLI banner says to type /help. That has to be answered here."""

from __future__ import annotations

import pytest

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType


class _RecordingBus(EventBus):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[Event] = []

    async def publish(self, event: Event) -> None:
        self.sent.append(event)
        await super().publish(event)


class _Router:
    def arm_warmup(self) -> None:
        return None

    def mark_warmup_done(self) -> None:
        return None

    async def close(self) -> None:
        return None


class _Orchestrator:
    async def resume_last_room(self) -> None:
        return None


class _Seat:
    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.router = _Router()
        self.tools = None
        self.orchestrator = _Orchestrator()


@pytest.mark.asyncio
async def test_cli_help_is_printed_locally(monkeypatch, capsys) -> None:
    """/help lists the commands and is not sent on as chat.

    The banner tells the user to type /help. Before this, the loop only
    caught /exit and /quit, so /help was published like any other line.
    """
    answers = iter(["/help", "/exit"])

    def fake_input(prompt: str = "") -> str:
        try:
            return next(answers)
        except StopIteration as exc:
            raise EOFError from exc

    monkeypatch.setattr("builtins.input", fake_input)

    bus = _RecordingBus()
    monkeypatch.setattr(
        "arelis.core.seat.build_seat",
        lambda config, profile="cli": _Seat(bus),
    )
    monkeypatch.setattr("arelis.cli.VoiceService", lambda *args, **kwargs: None)

    async def ready(*args, **kwargs):
        class _Snap:
            def status_line(self) -> str:
                return "ready"

        return _Snap()

    async def quiet(*args, **kwargs):
        return None

    monkeypatch.setattr("arelis.presence.readiness.probe_readiness", ready)
    monkeypatch.setattr("arelis.cli.run_model_preflight", quiet)
    monkeypatch.setattr("arelis.cli.run_model_warmup", quiet)
    monkeypatch.setattr("arelis.cli.run_auto_lessons", quiet)
    monkeypatch.setattr("arelis.cli.prefix_warmup_for", lambda *args, **kwargs: None)

    from arelis.cli import run_cli_async

    # A truthy config. An empty dict is falsy and would load the real one.
    code = await run_cli_async({"voice": {"enabled": False}})
    assert code == 0
    out = capsys.readouterr().out
    assert "show this list" in out
    assert "/exit" in out
    assert "/quit" in out
    sent_help = [
        event
        for event in bus.sent
        if event.type == EventType.USER_MESSAGE and event.payload.get("text") == "/help"
    ]
    assert sent_help == []
