"""Durable facts: explicit via confirm, proposed via review, never silent."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.core.agent_loop import TOOL_POLICY
from arelis.core.facts import facts_prompt_line
from arelis.core.memory import SessionMemory
from arelis.memory import MemoryStore
from arelis.tools import build_tool_registry
from arelis.tools.memory_tool import MemoryTool
from arelis.workspace import WorkspaceRoots


def test_facts_prompt_line_lists_approved_facts_and_caps_length() -> None:
    line = facts_prompt_line(["User climbs", "User builds an interferometer"])
    assert "User climbs" in line
    assert "interferometer" in line
    assert line.startswith("Things you know about the user")
    assert facts_prompt_line([]) == ""
    huge = facts_prompt_line(["x" * 300 for _ in range(40)])
    assert len(huge) <= 1600


@pytest.mark.asyncio
async def test_memory_tool_stores_an_explicit_fact_as_active(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    tool = MemoryTool(store)
    result = await tool.run(action="remember", fact="I climb on Thursdays.")
    assert result.ok
    assert store.active_fact_texts() == ["I climb on Thursdays."]
    rows = store.list_facts(status="active")
    assert rows[0]["source"] == "explicit"
    store.close()


def test_proposed_facts_stay_pending_until_approved(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    memory = SessionMemory(sink=store)
    memory.add_pending_fact("User builds an interferometer")

    assert store.active_fact_texts() == []
    pending = store.list_facts(status="pending")
    assert len(pending) == 1
    fact_id = int(pending[0]["id"])

    assert store.set_fact_status(fact_id, "active")
    assert store.active_fact_texts() == ["User builds an interferometer"]
    assert store.list_facts(status="pending") == []
    store.close()


def test_rejecting_a_proposed_fact_keeps_it_out_of_the_prompt(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    fact_id = store.add_fact(
        "User secretly loves xylophones",
        source="proposed",
        status="pending",
        session_id=store.session_id,
    )
    assert fact_id is not None
    store.set_fact_status(fact_id, "rejected")
    assert store.active_fact_texts() == []
    assert facts_prompt_line(store.active_fact_texts()) == ""
    store.close()


def test_memory_tool_is_write_gated(tmp_path: Path) -> None:
    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(tmp_path)]}})
    store = MemoryStore(tmp_path / "memory.db")
    registry = build_tool_registry(
        {"tools": {}, "agent": {}}, workspace, memory_store=store
    )
    assert "memory" in registry.names()
    assert registry.needs_confirm(
        "memory", {"action": "remember", "fact": "I prefer metric"}
    )
    assert not registry.needs_confirm(
        "memory",
        {"action": "remember", "fact": "I prefer metric"},
        confirm_writes=False,
    )
    store.close()


@pytest.mark.asyncio
async def test_memory_tool_can_forget_an_active_fact(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    tool = MemoryTool(store)
    await tool.run(action="remember", fact="I climb on Thursdays.")
    result = await tool.run(action="forget", fact="I climb on Thursdays.")
    assert result.ok
    assert store.active_fact_texts() == []
    store.close()


def test_tool_policy_sends_remember_requests_through_the_memory_tool() -> None:
    assert "memory tool" in TOOL_POLICY
    assert "remember" in TOOL_POLICY.lower()


def test_history_panel_exposes_pending_facts_for_review(qt_app, tmp_path: Path) -> None:
    from arelis.ui.panels.history import HistoryPanel

    panel = HistoryPanel()
    seen: list[tuple[object, str]] = []
    panel.fact_decided.connect(lambda ids, status: seen.append((ids, status)))
    panel.set_pending_facts([{"id": 7, "text": "User climbs"}])
    assert panel.facts_list.count() == 1
    panel.facts_list.setCurrentRow(0)
    panel.approve_btn.click()
    assert seen == [([7], "active")]


def test_memory_panel_can_forget_an_active_fact(qt_app) -> None:
    from arelis.ui.panels.memory import ActiveFactsPanel

    panel = ActiveFactsPanel()
    seen: list[tuple[object, str]] = []
    panel.fact_decided.connect(lambda ids, status: seen.append((ids, status)))
    panel.set_facts([{"id": 9, "text": "User climbs"}])
    panel.active_list.setCurrentRow(0)
    panel.forget_btn.click()
    assert seen == [([9], "rejected")]


def test_history_panel_rejects_multiple_selected_facts(qt_app) -> None:
    from arelis.ui.panels.history import HistoryPanel

    panel = HistoryPanel()
    seen: list[tuple[object, str]] = []
    panel.fact_decided.connect(lambda ids, status: seen.append((ids, status)))
    panel.set_pending_facts(
        [
            {"id": 1, "text": "User climbs"},
            {"id": 2, "text": "User prefers Fahrenheit"},
            {"id": 3, "text": "Transient junk"},
        ]
    )
    panel.facts_list.item(0).setSelected(True)
    panel.facts_list.item(2).setSelected(True)
    panel.reject_btn.click()
    assert len(seen) == 1
    assert seen[0][1] == "rejected"
    assert set(seen[0][0]) == {1, 3}


def test_history_panel_reject_all_pending(qt_app) -> None:
    from arelis.ui.panels.history import HistoryPanel

    panel = HistoryPanel()
    seen: list[tuple[object, str]] = []
    panel.fact_decided.connect(lambda ids, status: seen.append((ids, status)))
    panel.set_pending_facts(
        [
            {"id": 4, "text": "a"},
            {"id": 5, "text": "b"},
        ]
    )
    panel.reject_all_btn.click()
    assert seen == [([4, 5], "rejected")]


def test_a_fresh_store_records_its_schema_version(tmp_path: Path) -> None:
    from arelis.memory.store import SCHEMA_VERSION

    store = MemoryStore(tmp_path / "memory.db")
    assert store.schema_version == SCHEMA_VERSION
    store.close()
    reopened = MemoryStore(tmp_path / "memory.db")
    assert reopened.schema_version == SCHEMA_VERSION
    reopened.close()


def test_active_fact_with_key_supersedes_siblings(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    first = store.add_fact(
        "Favorite color is blue",
        source="explicit",
        status="active",
        key="favorite_color",
    )
    second = store.add_fact(
        "Favorite color is green",
        source="explicit",
        status="active",
        key=" Favorite_Color ",
    )
    assert first is not None and second is not None
    assert first != second
    active = store.list_facts(status="active")
    assert len(active) == 1
    assert active[0]["id"] == second
    assert active[0]["text"] == "Favorite color is green"
    assert active[0]["key"] == "favorite_color"
    rejected = store.list_facts(status="rejected")
    assert any(row["id"] == first for row in rejected)
    store.close()


def test_set_fact_status_active_supersedes_same_key(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    live = store.add_fact(
        "Timezone is EST",
        source="explicit",
        status="active",
        key="timezone",
    )
    pending = store.add_fact(
        "Timezone is UTC",
        source="proposed",
        status="pending",
        key="timezone",
    )
    assert live is not None and pending is not None
    assert store.set_fact_status(pending, "active")
    assert store.active_fact_texts() == ["Timezone is UTC"]
    rows = {row["id"]: row for row in store.list_facts()}
    assert rows[live]["status"] == "rejected"
    assert rows[pending]["status"] == "active"
    store.close()


def test_archive_stale_pending_facts(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    stale_id = store.add_fact(
        "Old pending fact",
        source="proposed",
        status="pending",
    )
    fresh_id = store.add_fact(
        "Fresh pending fact",
        source="proposed",
        status="pending",
    )
    assert stale_id is not None and fresh_id is not None
    store._conn.execute(
        "UPDATE facts SET created_at = ? WHERE id = ?",
        ("2020-01-01T00:00:00+00:00", stale_id),
    )
    store._conn.commit()
    changed = store.archive_stale_pending_facts(older_than_days=30)
    assert changed == 1
    rows = {row["id"]: row for row in store.list_facts()}
    assert rows[stale_id]["status"] == "rejected"
    assert rows[fresh_id]["status"] == "pending"
    store.close()


def test_latest_session_id_skips_empty_shells(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    empty = store.start_session()
    filled = store.start_session()
    memory = SessionMemory(sink=store)
    memory.add("user", "real turn")
    assert store.latest_session_id(require_messages=True) == filled
    assert empty != filled
    store.close()
