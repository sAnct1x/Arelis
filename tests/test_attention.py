"""Attention scan — measured watchers/proactivity v1 (offline, frozen clock)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from arelis.briefing.attention import collect_attention, format_attention_section
from arelis.briefing.calendar import CalendarEvent
from arelis.core.claims import detect_attention_ask, detect_exactness_need
from arelis.core.preflight import detect_intents
from arelis.memory import MemoryStore

_TZ = ZoneInfo("America/New_York")
_NOW = datetime(2026, 8, 9, 10, 0, tzinfo=_TZ)


def test_collect_overdue_and_due_soon_and_horizon() -> None:
    tasks = [
        {"id": 1, "title": "Pay rent", "status": "open", "due": "2026-08-01"},
        {"id": 2, "title": "Buy milk", "status": "open", "due": "2026-08-10"},
        {
            "id": 3,
            "title": "Ancient chore",
            "status": "open",
            "due": "",
            "created_at": "2026-07-01T12:00:00+00:00",
        },
    ]
    goals = [
        {
            "id": 9,
            "title": "Ship watchers",
            "kind": "goal",
            "status": "active",
            "horizon": "this week",
        },
        {
            "id": 10,
            "title": "Long arc",
            "kind": "goal",
            "status": "active",
            "horizon": "2027-01-01",
        },
    ]
    events = [
        CalendarEvent(
            starts_at=datetime(2026, 8, 9, 15, 0, tzinfo=_TZ),
            summary="Dentist",
            all_day=False,
        )
    ]
    items = collect_attention(
        now=_NOW,
        tasks=tasks,
        goals=goals,
        events=events,
        due_soon_days=2,
        soon_hours=24,
        stale_task_days=7,
        limit=12,
    )
    kinds = {i.kind for i in items}
    assert "overdue_task" in kinds
    assert "due_soon_task" in kinds
    assert "horizon_goal" in kinds
    assert "soon_event" in kinds
    assert "stale_task" in kinds
    text = format_attention_section(items)
    assert "Pay rent" in text
    assert "Ship watchers" in text
    assert "Dentist" in text
    # Far horizon must not fire.
    assert "Long arc" not in text


def test_empty_attention_omits_section() -> None:
    items = collect_attention(now=_NOW, tasks=[], goals=[], events=[])
    assert items == []
    assert format_attention_section(items) == ""


def test_inbox_and_file_rules() -> None:
    from arelis.briefing.attention import FileSnapshot

    mail = [
        {
            "from": "Billing <billing@example.com>",
            "subject": "Invoice due",
            "date": "2026-08-09",
        },
        {
            "from": "Friend <friend@example.com>",
            "subject": "Hi",
            "date": "2026-08-09",
        },
    ]
    snaps = {
        "data/drops/taxes.pdf": FileSnapshot(
            path="data/drops/taxes.pdf", exists=False
        ),
        "data/drops/old.csv": FileSnapshot(
            path="data/drops/old.csv",
            exists=True,
            mtime=datetime(2026, 7, 1, tzinfo=_TZ),
        ),
    }
    items = collect_attention(
        now=_NOW,
        tasks=[],
        goals=[],
        events=[],
        mail=mail,
        inbox_rules=[
            {"id": "bills", "sender_contains": "billing@"},
        ],
        file_rules=[
            {"id": "tax_packet", "path": "data/drops/taxes.pdf", "missing": True},
            {
                "id": "stale_drop",
                "path": "data/drops/old.csv",
                "older_than_days": 14,
            },
        ],
        file_snapshots=snaps,
        limit=12,
    )
    kinds = {i.kind for i in items}
    assert "inbox_match" in kinds
    assert "file_missing" in kinds
    assert "file_stale" in kinds
    text = format_attention_section(items)
    assert "Invoice due" in text
    assert "taxes.pdf" in text
    assert "old.csv" in text
    assert "Friend" not in text


@pytest.mark.asyncio
async def test_briefing_attention_inbox_rule(tmp_path) -> None:
    from arelis.briefing import build_briefing
    from arelis.tools.base import ToolResult

    store = MemoryStore(tmp_path / "memory.db")

    class _FakeInbox:
        async def run(self, **kwargs):
            return ToolResult(
                ok=True,
                output="1 unread",
                data={
                    "messages": [
                        {
                            "from": "billing@acme.test",
                            "subject": "Your bill",
                            "date": "Sun",
                        }
                    ],
                    "matched": 1,
                    "unread": 1,
                    "total": 1,
                },
            )

    text = await build_briefing(
        {
            "tools": {
                "briefing": {
                    "attention": {
                        "enabled": True,
                        "limit": 12,
                        "inbox_rules": [
                            {"id": "bills", "sender_contains": "billing@"}
                        ],
                        "file_rules": [],
                    },
                }
            },
            "location": {"enabled": False},
        },
        store=store,
        inbox=_FakeInbox(),
    )
    assert "## Attention" in text
    assert "Inbox match" in text
    assert "Your bill" in text
    store.close()


@pytest.mark.asyncio
async def test_briefing_includes_attention(tmp_path) -> None:
    from arelis.briefing import build_briefing
    from arelis.tools.base import ToolResult

    store = MemoryStore(tmp_path / "memory.db")
    store.add_task("Overdue paperwork", due="2026-08-01")
    store.add_goal("Ship watchers", kind="goal", horizon="this week")

    class _FakeInbox:
        async def run(self, **kwargs):
            return ToolResult(ok=True, output="No unread mail.", data={"messages": []})

    text = await build_briefing(
        {
            "tools": {
                "briefing": {
                    "attention": {"enabled": True, "limit": 12, "due_soon_days": 2},
                    "task_limit": 12,
                    "goal_limit": 8,
                }
            },
            "location": {"enabled": False},
        },
        store=store,
        inbox=_FakeInbox(),
    )
    assert "## Attention" in text
    assert "Overdue" in text or "paperwork" in text.lower()
    store.close()


def test_attention_exactness_and_preflight() -> None:
    assert detect_attention_ask("What needs my attention?")
    assert detect_attention_ask("What's urgent right now?")
    need = detect_exactness_need("What needs my attention?")
    assert need.needs_attention
    hints = detect_intents("What needs my attention?")
    assert any(h.kind == "attention" for h in hints)


def test_an_urgency_ask_now_expects_the_stores_it_reads_from() -> None:
    """The attention tool is gone; the question it answered is not.

    It only ever aggregated tasks, goals and the near calendar, so the ask has to
    land on those. If this expects nothing, "what's urgent" reaches the model with
    no tool named and the urgency gets invented.
    """
    hints = [h for h in detect_intents("What needs my attention?") if h.kind == "attention"]
    assert hints, "urgency ask produced no intent hint"
    assert "tasks" in hints[0].expected_tools
    for tool in ("attention", "briefing"):
        assert tool not in hints[0].expected_tools


def test_urgency_is_warranted_by_a_store_read() -> None:
    """Without this, kind='attention' is unsatisfiable and every ask refuses."""
    from arelis.core.evidence import EvidenceLedger

    empty = EvidenceLedger()
    assert "attention" in empty.missing_kinds(("attention",))

    for tool in ("tasks", "goals", "agenda"):
        ledger = EvidenceLedger()
        ledger.add(source=tool, kind=tool, span="one open item", ok=True)
        assert "attention" not in ledger.missing_kinds(("attention",)), (
            f"a {tool} read should warrant an urgency answer"
        )
