"""Bus event audit → logs/events.log."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.core.bus import EventBus
from arelis.core.event_audit import (
    attach_event_audit,
    event_telemetry_enabled,
    log_side_effect,
)
from arelis.core.events import Event, EventType


def test_event_telemetry_defaults_on() -> None:
    assert event_telemetry_enabled({}) is True
    assert event_telemetry_enabled({"agent": {"event_telemetry": False}}) is False


@pytest.mark.asyncio
async def test_attach_writes_audited_events(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    import arelis.core.event_audit as mod

    mod._attached = False
    mod.log.handlers.clear()

    bus = EventBus()
    assert attach_event_audit(bus, {"agent": {"event_telemetry": True}})
    bus_task = __import__("asyncio").create_task(bus.run())
    await bus.publish(
        Event(
            EventType.TOOL_CONFIRM,
            {"id": "c1", "tool": "send_sms", "summary": "to=brian"},
        )
    )
    await bus.publish(
        Event(EventType.ASSISTANT_DELTA, {"text": "should not appear"})
    )
    await bus.drain()
    bus.stop()
    bus_task.cancel()
    with pytest.raises(__import__("asyncio").CancelledError):
        await bus_task

    text = (tmp_path / "logs" / "events.log").read_text(encoding="utf-8")
    assert "tool_confirm" in text
    assert "send_sms" in text
    assert "should not appear" not in text


def test_log_side_effect_writes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    import arelis.core.event_audit as mod

    mod._attached = False
    mod.log.handlers.clear()
    log_side_effect(
        "restored_send",
        tool="send_sms",
        ok=True,
        confirm_id="abc",
        detail="queued",
    )
    text = (tmp_path / "logs" / "events.log").read_text(encoding="utf-8")
    assert "restored_send" in text
    assert "send_sms" in text
    assert "ok=1" in text
