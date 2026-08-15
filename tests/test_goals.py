"""Goals tool — add/list/status/remove against memory.db."""

from __future__ import annotations

import pytest

from arelis.core.claims import detect_exactness_need, detect_goals_ask
from arelis.core.evidence import EvidenceLedger
from arelis.core.preflight import detect_intents
from arelis.core.receipts import action_receipt
from arelis.core.skills import select_skill_ids
from arelis.memory import MemoryStore
from arelis.tools.base import GOALS_WRITE_ACTIONS, ToolRegistry, capability_class
from arelis.tools.goals import GoalsTool


def _tool(tmp_path) -> GoalsTool:
    store = MemoryStore(tmp_path / "memory.db")
    return GoalsTool(store)


@pytest.mark.asyncio
async def test_add_list_pause_resume_done_drop_remove(tmp_path) -> None:
    tool = _tool(tmp_path)

    empty = await tool.run(action="list")
    assert empty.ok
    assert "No active goals" in empty.output

    added = await tool.run(
        action="add",
        title="Ship goals wave",
        kind="goal",
        horizon="this week",
    )
    assert added.ok
    assert added.data["status"] == "active"
    goal_id = int(added.data["id"])

    listed = await tool.run(action="list")
    assert listed.ok
    assert "Ship goals wave" in listed.output
    assert f"#{goal_id}" in listed.output

    paused = await tool.run(action="pause", id=goal_id)
    assert paused.ok
    assert paused.data["status"] == "paused"
    bad_pause = await tool.run(action="pause", id=goal_id)
    assert not bad_pause.ok

    resumed = await tool.run(action="resume", id=goal_id)
    assert resumed.ok
    assert resumed.data["status"] == "active"

    done = await tool.run(action="done", id=goal_id)
    assert done.ok
    assert done.data["status"] == "done"
    assert (await tool.run(action="list")).data["goals"] == []

    # Fresh commitment for drop path
    c = await tool.run(
        action="add",
        title="No cloud APIs",
        kind="commitment",
    )
    cid = int(c.data["id"])
    dropped = await tool.run(action="drop", id=cid)
    assert dropped.ok
    assert dropped.data["status"] == "dropped"

    removed = await tool.run(action="remove", id=cid)
    assert removed.ok
    all_rows = await tool.run(action="list", status="all")
    assert all(int(g["id"]) != cid for g in all_rows.data["goals"])

    tool.store.close()


@pytest.mark.asyncio
async def test_list_shows_open_task_count(tmp_path) -> None:
    tool = _tool(tmp_path)
    added = await tool.run(action="add", title="Ship linking")
    gid = int(added.data["id"])
    tool.store.add_task("Draft docs", goal_id=gid)
    tool.store.add_task("Write tests", goal_id=gid)
    listed = await tool.run(action="list")
    assert listed.ok
    assert "2 open tasks" in listed.output
    tool.store.close()


@pytest.mark.asyncio
async def test_illegal_resume_from_active(tmp_path) -> None:
    tool = _tool(tmp_path)
    added = await tool.run(action="add", title="Keep active")
    gid = int(added.data["id"])
    bad = await tool.run(action="resume", id=gid)
    assert not bad.ok
    assert "active" in bad.output.lower()
    tool.store.close()


@pytest.mark.asyncio
async def test_add_requires_title(tmp_path) -> None:
    tool = _tool(tmp_path)
    result = await tool.run(action="add")
    assert not result.ok
    assert "title" in result.output.lower()
    tool.store.close()


def test_write_actions_need_confirm_list_does_not(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    registry = ToolRegistry()
    registry.register(GoalsTool(store))
    assert not registry.needs_confirm("goals", {"action": "list"})
    for action in GOALS_WRITE_ACTIONS:
        assert registry.needs_confirm(
            "goals", {"action": action, "title": "x", "id": 1}
        )
    assert not registry.needs_confirm(
        "goals", {"action": "add", "title": "x"}, confirm_writes=False
    )
    assert capability_class("goals", {"action": "add"}) == "WRITE_LOCAL"
    assert capability_class("goals", {"action": "list"}) == "READ"
    store.close()


def test_goals_registered_when_archive_present(tmp_path, monkeypatch) -> None:
    from arelis import tools as tools_pkg
    from arelis.workspace import WorkspaceRoots

    monkeypatch.setattr(tools_pkg, "load_account", lambda: None)
    monkeypatch.setattr(tools_pkg, "load_sms_account", lambda: None)
    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(tmp_path)]}})
    store = MemoryStore(tmp_path / "memory.db")
    attended = tools_pkg.build_tool_registry(
        {"tools": {}, "agent": {}}, workspace, memory_store=store
    )
    assert "goals" in attended.names()
    disabled = tools_pkg.build_tool_registry(
        {"tools": {"goals": {"enabled": False}}, "agent": {}},
        workspace,
        memory_store=store,
    )
    assert "goals" not in disabled.names()
    unattended = tools_pkg.build_tool_registry(
        {"tools": {}, "agent": {}}, workspace, allow_send=False
    )
    assert "goals" not in unattended.names()
    store.close()


@pytest.mark.asyncio
async def test_briefing_and_world_state_include_goals(tmp_path) -> None:
    from arelis.briefing import build_briefing
    from arelis.core.world_state import world_state_prompt_line
    from arelis.tools.base import ToolResult

    store = MemoryStore(tmp_path / "memory.db")
    store.add_goal("Finish optics review", kind="goal", horizon="August")

    class _FakeInbox:
        async def run(self, **kwargs):
            return ToolResult(ok=True, output="No unread mail.", data={"messages": []})

    text = await build_briefing(
        {
            "tools": {"briefing": {"goal_limit": 8, "task_limit": 12}},
            "location": {"enabled": False},
        },
        store=store,
        inbox=_FakeInbox(),
    )
    assert "## Goals" in text
    assert "Finish optics review" in text

    line = world_state_prompt_line(
        {},
        role="fast",
        model="eval",
        store=store,
    )
    assert "active goals 1" in line
    store.close()


def test_goals_exactness_preflight_skill() -> None:
    assert detect_goals_ask("What are my goals?")
    assert detect_goals_ask("Commit to no cloud APIs")
    assert not detect_goals_ask("What is a goal?")
    assert not detect_goals_ask("git commit the changes")
    need = detect_exactness_need("What am I committed to?")
    assert need.needs_goals
    assert "goals" in need.kinds

    hints = detect_intents("Add a goal: ship the goals wave")
    assert any(h.kind == "goals" for h in hints)

    ids = select_skill_ids(
        "What are my commitments?",
        available_tools={"goals", "tasks", "memory"},
    )
    assert "goals" in ids

    ledger = EvidenceLedger()
    ledger.record_tool(
        "goals",
        ok=True,
        output="#1 [active/goal] Ship it",
        data={"id": 1, "title": "Ship it", "action": "list"},
        args={"action": "list"},
    )
    assert ledger.satisfies(("goals",))


def test_goals_receipt() -> None:
    r = action_receipt(
        "goals",
        ok=True,
        args={"action": "add", "title": "Ship it", "kind": "goal"},
        data={"id": 3, "title": "Ship it", "kind": "goal", "status": "active"},
    )
    assert r is not None
    assert r["action"] == "goals.add"
    assert r["title"] == "Ship it"
    assert action_receipt("goals", ok=True, args={"action": "list"}) is None
