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
    MAX_MESSAGE_CHARS,
    MAX_PENDING,
    ReminderError,
    ReminderStore,
    default_reminders_path,
)
from arelis.tools.remind import REMIND_WRITE_ACTIONS, WRITE_ACTIONS, RemindTool


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
    created = await tool.run(action="in", minutes=20, message="take the pizza out")
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
async def test_tool_run_cancel_removes_it(tmp_path: Path) -> None:
    """Mutant: cancel prints ok and leaves the row on disk."""
    tool = _tool(tmp_path)
    created = await tool.run(action="in", seconds=90, message="check the stove")
    assert created.ok, created.output
    reminder_id = created.data["id"]

    cancelled = await tool.run(action="cancel", id=reminder_id)
    assert cancelled.ok, cancelled.output
    assert cancelled.data["id"] == reminder_id

    store = ReminderStore(tmp_path / "reminders.json")
    assert store.get(reminder_id) is None
    assert store.list_pending() == []
    later = _now() + timedelta(hours=1)
    assert store.due_now(later) == []

    listed = await tool.run(action="list")
    assert listed.ok
    assert listed.data["reminders"] == []


@pytest.mark.asyncio
async def test_restart_new_store_on_same_file_still_sees_it(tmp_path: Path) -> None:
    """Mutant: persist is skipped; only the live object holds the row."""
    first = _store(tmp_path)
    item = first.add_in("call the bank", minutes=15, now=_now())
    path = tmp_path / "reminders.json"
    assert path.is_file()

    restarted = ReminderStore(path)
    found = restarted.get(item.id)
    assert found is not None
    assert found.message == "call the bank"
    assert found.due_iso == item.due_iso
    assert not found.fired
    pending = restarted.list_pending()
    assert len(pending) == 1
    assert pending[0].id == item.id


@pytest.mark.asyncio
async def test_fired_items_do_not_return_again(tmp_path: Path) -> None:
    """Mutant: mark_fired is a no-op, or it does not persist."""
    store = _store(tmp_path)
    item = store.add_in("stand up", seconds=30, now=_now())
    later = item.due_at() + timedelta(seconds=1)
    assert store.due_now(later)
    assert store.mark_fired(item.id)
    assert store.due_now(later) == []
    assert store.due_now(later + timedelta(hours=2)) == []

    restarted = ReminderStore(tmp_path / "reminders.json")
    assert restarted.due_now(later + timedelta(hours=2)) == []
    loaded = restarted.get(item.id)
    assert loaded is not None
    assert loaded.fired


@pytest.mark.asyncio
async def test_overdue_on_load_is_due(tmp_path: Path) -> None:
    """Mutant: load drops due < now so a downtime swallows the toast."""
    path = tmp_path / "reminders.json"
    _seed_overdue(path, fired=False)
    store = ReminderStore(path)
    due = store.due_now(_now())
    assert len(due) == 1
    assert due[0].id == "1"
    assert due[0].message == "take the pizza out"
    assert store.seconds_until_next(_now()) == 0.0


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
async def test_tool_run_is_actually_called(tmp_path: Path) -> None:
    """Mutant: the suite only hits ReminderStore and run() is a stub."""
    tool = _tool(tmp_path)
    created = await tool.run(action="in", hours=1, text="walk the dog")
    assert created.ok, created.output
    assert "walk the dog" in created.output
    assert created.data["kind"] == KIND

    listed = await tool.run(action="list")
    assert listed.ok
    assert listed.data["reminders"]
    assert listed.data["reminders"][0]["message"] == "walk the dog"
    assert listed.data["reminders"][0]["id"] == created.data["id"]
    assert created.data["id"] in listed.output
    assert "walk the dog" in listed.output

    wall = datetime.now().astimezone()
    when = (wall + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
    at = await tool.run(action="at", when=when, message="dinner")
    assert at.ok, at.output
    assert at.data["kind"] == KIND
    assert "dinner" in at.output

    iso = (wall + timedelta(hours=3)).isoformat(timespec="minutes")
    again = await tool.run(action="at", at=iso, text="tea")
    assert again.ok, again.output

    unknown = await tool.run(action="snooze")
    assert not unknown.ok
    assert "list" in unknown.output


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

    delay = await tool.run(action="in", minutes=MAX_DELAY_DAYS * 24 * 60 + 1, message="nope")
    assert not delay.ok
    assert "schedule" in delay.output.lower()
    assert "agenda" in delay.output.lower()


@pytest.mark.asyncio
async def test_message_required_and_capped(tmp_path: Path) -> None:
    tool = _tool(tmp_path)
    missing = await tool.run(action="in", minutes=5)
    assert not missing.ok
    assert "message" in missing.output.lower()

    long = await tool.run(action="in", minutes=5, message="x" * (MAX_MESSAGE_CHARS + 1))
    assert not long.ok
    assert str(MAX_MESSAGE_CHARS) in long.output


@pytest.mark.asyncio
async def test_max_pending(tmp_path: Path) -> None:
    store = _store(tmp_path)
    stamp = _now()
    for i in range(MAX_PENDING):
        store.add_in(f"item {i}", seconds=30 + i, now=stamp)
    with pytest.raises(ReminderError, match="Too many pending"):
        store.add_in("one more", seconds=90, now=stamp)
    assert len(store.list_pending()) == MAX_PENDING


@pytest.mark.asyncio
async def test_seconds_until_next(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.seconds_until_next(_now()) is None
    store.add_in("soon", minutes=20, now=_now())
    wait = store.seconds_until_next(_now())
    assert wait is not None
    assert wait == pytest.approx(20 * 60, abs=1.0)
    overdue = store.seconds_until_next(_now() + timedelta(hours=1))
    assert overdue == 0.0


@pytest.mark.asyncio
async def test_write_actions_are_in_at_cancel() -> None:
    assert WRITE_ACTIONS == {"in", "at", "cancel"}
    assert REMIND_WRITE_ACTIONS == WRITE_ACTIONS
    assert "list" not in WRITE_ACTIONS


@pytest.mark.asyncio
async def test_default_path_is_under_user_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    path = default_reminders_path()
    assert path == tmp_path / "data" / "reminders.json"
    assert path.name == "reminders.json"
