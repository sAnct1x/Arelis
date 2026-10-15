"""Calendar creates land on the Arelis calendar when nothing else is signed in.

The live miss: "add lunch with Sam tomorrow at noon" called Google, then
Outlook, both refused with not authorized, and the reply still said the
lunch was added. An unnamed calendar is the local one. A named cloud that
is not signed in may land locally only if the reply says so. A reply may
not say the event was added when every create failed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from arelis.calendar.secrets import CalendarSecrets
from arelis.calendar.store import CalendarStore
from arelis.core.agenda_complete import (
    draft_agenda_create_args,
    fill_agenda_args,
    parse_agenda_utterance,
)
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory
from arelis.tools.agenda import AgendaTool, _parse_dt
from arelis.tools.base import ToolRegistry, ToolResult
from arelis.tools.policy import action_is_write
from tests.hardening_helpers import _collect, _config, _deny, _ScriptedRouter

_LUNCH = "Add lunch with Sam tomorrow at noon to my calendar."


def _isolated_store(tmp_path, monkeypatch) -> None:
    db = tmp_path / "cal.db"

    def factory(path=None):
        return CalendarStore(path or db)

    monkeypatch.setattr("arelis.tools.agenda.CalendarStore", factory)
    monkeypatch.setattr("arelis.calendar.service.CalendarStore", factory)
    empty = CalendarSecrets(google=None, outlook=None)
    monkeypatch.setattr(
        "arelis.calendar.service.load_calendar_secrets",
        lambda path=None: empty,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["google", "outlook"])
async def test_unauthorized_cloud_create_lands_on_the_local_calendar(
    tmp_path, monkeypatch, provider: str
) -> None:
    """Google or Outlook with no sign-in still creates the event locally."""
    _isolated_store(tmp_path, monkeypatch)
    tool = AgendaTool({})
    result = await tool.run(
        action="create",
        summary="Lunch with Sam",
        start="2026-10-13T12:00:00",
        provider=provider,
    )
    assert result.ok, result.output
    event = result.data["event"]
    assert event["provider"] == "local"
    assert "Arelis calendar" in result.output
    cloud = "Google" if provider == "google" else "Outlook"
    assert cloud in result.output
    assert f"your {cloud} calendar" not in result.output
    assert "not authorized" not in result.output.lower()


def test_an_unnamed_calendar_create_uses_the_local_calendar() -> None:
    """No Google or Outlook in the ask means the Arelis calendar."""
    draft = parse_agenda_utterance(_LUNCH)
    assert draft is not None and draft.complete
    assert draft.provider == "local"
    args = draft_agenda_create_args(draft)
    assert args["provider"] == "local"
    # The model still sends Google and midnight and the whole sentence.
    # The draft is what the confirm card and the call actually use.
    locked = fill_agenda_args(
        {
            "action": "create",
            "provider": "google",
            "summary": _LUNCH,
            "start": "2026-10-13T00:00:00-04:00",
        },
        draft,
    )
    assert locked["provider"] == "local"
    assert locked["summary"].casefold() == "lunch with sam"
    parsed = _parse_dt(locked["start"], field="start")
    assert parsed.hour == 12
    assert parsed.minute == 0
    tomorrow = datetime.now().astimezone().date().toordinal() + 1
    assert parsed.date().toordinal() == tomorrow


def test_a_local_create_still_needs_a_confirm_card() -> None:
    assert action_is_write("agenda", {"action": "create", "provider": "local"})
    assert action_is_write("agenda", {"action": "create", "provider": "google"})


class _FailingAgenda:
    name = "agenda"
    description = "calendar"
    risk = "write"
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "provider": {"type": "string"},
            "summary": {"type": "string"},
            "start": {"type": "string"},
        },
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        return ToolResult(
            ok=False,
            output=(
                "create failed: Google Calendar not authorized. "
                "Sign in on the calendar tile."
            ),
        )


@pytest.mark.asyncio
async def test_a_reply_cannot_say_added_when_every_create_failed() -> None:
    """The lie from the live run: every create failed, the reply said added."""
    bus = EventBus()
    router = _ScriptedRouter(
        [
            [
                (
                    "tool_calls",
                    [
                        {
                            "type": "function",
                            "function": {
                                "name": "agenda",
                                "arguments": {
                                    "action": "create",
                                    "provider": "google",
                                    "summary": _LUNCH,
                                    "start": "2026-10-13T00:00:00-04:00",
                                },
                            },
                        }
                    ],
                )
            ],
            [
                (
                    "token",
                    "Got it, lunch with Sam tomorrow at noon is added to your calendar.",
                )
            ],
        ]
    )
    tools = ToolRegistry()
    tools.register(_FailingAgenda())
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["confirm_writes"] = False
    cfg["agent"]["native_tool_calling"] = True
    cfg["agent"]["agenda_force_call"] = False
    cfg["agent"]["json_fallback"] = False
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "persona",
        cfg,
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )
    events = await _collect(bus, loop.run(_LUNCH, "fast"))
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    text = str(done.payload.get("text") or "")
    assert "added" not in text.casefold()
    assert "not on your calendar" in text.casefold()


def test_a_successful_create_may_still_say_added() -> None:
    from arelis.core.claims import guard_false_calendar_add

    reply = "Got it, lunch with Sam tomorrow at noon is added to your calendar."
    assert guard_false_calendar_add(reply, created=True, failed=True) == reply
    assert guard_false_calendar_add(reply, created=False, failed=False) == reply


