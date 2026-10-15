"""Typed personal text must not land in events.log or turns.jsonl.

One fake turn, the real audit and turn-log writers. The chat events still
carry the words. The files on disk keep a character count.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import ModuleType

import pytest

from arelis.core import event_audit, turn_telemetry
from arelis.core.bus import EventBus
from arelis.core.event_audit import attach_event_audit
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.tools.base import ToolRegistry, ToolResult
from tests.hardening_helpers import _collect, _config, _ScriptedRouter

ADDRESS = "123 Fakeplace Street 99999"
PHONE = "555-123-4567"
MESSAGE = f"{ADDRESS} {PHONE}"
_REPLY = "I could not complete that request."


class _LeakyTool:
    """Returns the typed text inside a tool error. Chat may show that. Logs may not."""

    name = "probe"
    description = "Look something up."
    risk = "read"
    parameters_schema = {
        "type": "object",
        "properties": {"q": {"type": "string"}},
    }

    async def run(self, **kwargs: object) -> ToolResult:
        del kwargs
        try:
            raise ValueError(MESSAGE)
        except ValueError as exc:
            return ToolResult(
                ok=False,
                output=f"{type(exc).__name__}: {exc}",
                data={"error_type": type(exc).__name__},
            )


def _detach(module: ModuleType, logger_name: str) -> None:
    lg = logging.getLogger(logger_name)
    tag = module._HANDLER_TAG
    for handler in list(lg.handlers):
        if getattr(handler, "_arelis_tag", "") == tag:
            handler.flush()
            handler.close()
            lg.removeHandler(handler)
    module._attached = False


def _flush(logger_name: str) -> None:
    for handler in logging.getLogger(logger_name).handlers:
        handler.flush()


@pytest.mark.asyncio
async def test_turn_logs_omit_typed_personal_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typed address and phone stay out of events.log and turns.jsonl."""
    monkeypatch.setattr(turn_telemetry, "logs_dir", lambda: tmp_path)
    monkeypatch.setattr(event_audit, "logs_dir", lambda: tmp_path)
    _detach(event_audit, "arelis.event.audit")
    _detach(turn_telemetry, "arelis.turn.trace")
    try:
        bus = EventBus()
        cfg = _config()
        cfg["agent"]["chat_fast_path"] = False
        cfg["agent"]["turn_telemetry"] = True
        cfg["agent"]["event_telemetry"] = True
        assert attach_event_audit(bus, cfg) is True
        tools = ToolRegistry()
        tools.register(_LeakyTool())  # type: ignore[arg-type]
        router = _ScriptedRouter(
            [
                [
                    (
                        "tool_calls",
                        [
                            {
                                "type": "function",
                                "function": {
                                    "name": "probe",
                                    "arguments": {"q": "lookup"},
                                },
                            }
                        ],
                    )
                ],
                [("token", _REPLY)],
            ]
        )
        Orchestrator(bus, router, tools, cfg, SessionMemory())  # type: ignore[arg-type]
        events = await _collect(
            bus,
            bus.publish(
                Event(
                    EventType.USER_MESSAGE,
                    {"text": MESSAGE, "source": "chat"},
                )
            ),
        )
        _flush("arelis.event.audit")
        _flush("arelis.turn.trace")

        events_log = (tmp_path / "events.log").read_text(encoding="utf-8")
        turns = (tmp_path / "turns.jsonl").read_text(encoding="utf-8")
        for secret in (ADDRESS, PHONE, "Fakeplace", "99999", "5551234567"):
            assert secret not in events_log, secret
            assert secret not in turns, secret
        assert "sha=" not in events_log
        assert "user_sha" not in turns

        row = json.loads(turns.strip().splitlines()[-1])
        assert row["user_chars"] == len(MESSAGE)
        assert "user_sha" not in row
        assert "user_preview" not in row

        assert any(
            event.type == EventType.USER_MESSAGE and event.payload.get("text") == MESSAGE
            for event in events
        )
        assert any(
            event.type == EventType.TOOL_RESULT
            and MESSAGE in str(event.payload.get("output") or "")
            for event in events
        )
    finally:
        _detach(event_audit, "arelis.event.audit")
        _detach(turn_telemetry, "arelis.turn.trace")
