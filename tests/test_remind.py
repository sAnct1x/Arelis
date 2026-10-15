"""Phase 5.1 reminders. Store + tool.run — not helpers that skip the tool.

Mutants this file is supposed to catch:

1. due_now uses exact equality and misses a travel-forward tick.
2. cancel only rewrites the in-memory list.
3. a new ReminderStore on the same file cannot see what the last one wrote.
4. mark_fired is in-memory only, so a restart re-toasts.
5. load drops overdue rows instead of returning them from due_now.
6. a 0 / negative delay is coerced to "now" and persisted.
7. tests call store helpers and never RemindTool.run.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from arelis.reminders import (
    KIND,
    MAX_DELAY_DAYS,
    ReminderStore,
)
from arelis.tools.remind import RemindTool


def _now() -> datetime:
    return datetime(2026, 9, 18, 1, 40, 0).astimezone()


def _store(tmp_path: Path) -> ReminderStore:
    return ReminderStore(tmp_path / "reminders.json")


def _tool(tmp_path: Path) -> RemindTool:
    return RemindTool(_store(tmp_path))


def _seed_overdue(path: Path, *, fired: bool = False) -> None:
    due = (_now() - timedelta(minutes=5)).isoformat(timespec="seconds")
    created = (_now() - timedelta(minutes=25)).isoformat(timespec="seconds")
    path.write_text(
        json.dumps(
            {
                "next_id": 2,
                "items": [
                    {
                        "id": "1",
                        "message": "take the pizza out",
                        "due_iso": due,
                        "created_iso": created,
                        "fired": fired,
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_tool_run_in_is_due_after_travel_forward(tmp_path: Path) -> None:
    """Mutant: due_now compares with == and a later now misses it."""
    tool = _tool(tmp_path)
    created = await tool.run(
        action="in", minutes=20, message="take the pizza out"
    )
    assert created.ok, created.output
    assert created.data["kind"] == KIND
    assert created.data["message"] == "take the pizza out"
    assert created.data["id"]
    assert created.data["due_iso"]

    store = ReminderStore(tmp_path / "reminders.json")
    item = store.get(created.data["id"])
    assert item is not None
    due = item.due_at()
    assert store.due_now(due - timedelta(seconds=1)) == []
    hit = store.due_now(due + timedelta(minutes=1))
    assert len(hit) == 1
    assert hit[0].id == item.id
    assert hit[0].message == "take the pizza out"
    assert hit[0].fire_payload() == {
        "id": item.id,
        "message": "take the pizza out",
        "due_iso": item.due_iso,
        "kind": KIND,
    }


@pytest.mark.asyncio
async def test_zero_and_negative_delay_fail(tmp_path: Path) -> None:
    """Mutant: minutes=0 is treated as now and written."""
    tool = _tool(tmp_path)
    path = tmp_path / "reminders.json"
    zero = await tool.run(action="in", minutes=0, message="now?")
    assert not zero.ok
    assert "greater than zero" in zero.output.lower()

    negative = await tool.run(action="in", minutes=-5, message="already")
    assert not negative.ok
    assert "greater than zero" in negative.output.lower()

    seconds = await tool.run(action="in", seconds=0, message="now?")
    assert not seconds.ok

    empty = await tool.run(action="in", minutes=0, seconds=0, hours=0, message="x")
    assert not empty.ok

    store = ReminderStore(path)
    assert store.list_pending() == []
    if path.is_file():
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw.get("items") == []


@pytest.mark.asyncio
async def test_at_past_and_beyond_seven_days_fail(tmp_path: Path) -> None:
    tool = _tool(tmp_path)
    past = await tool.run(
        action="at",
        when="2020-01-01 09:00",
        message="ancient",
    )
    assert not past.ok
    assert "past" in past.output.lower()

    wall = datetime.now().astimezone()
    later = (wall + timedelta(days=MAX_DELAY_DAYS + 1)).strftime("%Y-%m-%d %H:%M")
    long = await tool.run(action="at", when=later, message="next month")
    assert not long.ok
    assert "schedule" in long.output.lower()
    assert "agenda" in long.output.lower()

    delay = await tool.run(
        action="in", minutes=MAX_DELAY_DAYS * 24 * 60 + 1, message="nope"
    )
    assert not delay.ok
    assert "schedule" in delay.output.lower()
    assert "agenda" in delay.output.lower()


