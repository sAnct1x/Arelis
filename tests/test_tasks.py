"""Local tasks tool — add/list/done/remove against memory.db."""

from __future__ import annotations

import pytest

from arelis.memory import MemoryStore
from arelis.tools.base import TASKS_WRITE_ACTIONS, ToolRegistry
from arelis.tools.tasks import TasksTool


def _tool(tmp_path) -> TasksTool:
    store = MemoryStore(tmp_path / "memory.db")
    return TasksTool(store)


@pytest.mark.asyncio
async def test_add_list_done_remove(tmp_path) -> None:
    tool = _tool(tmp_path)

    empty = await tool.run(action="list")
    assert empty.ok
    assert "No open tasks" in empty.output

    added = await tool.run(action="add", title="Buy solder", due="2026-08-10")
    assert added.ok
    assert added.data["status"] == "open"
    task_id = int(added.data["id"])

    listed = await tool.run(action="list")
    assert listed.ok
    assert "Buy solder" in listed.output
    assert f"#{task_id}" in listed.output
    assert "2026-08-10" in listed.output
    assert len(listed.data["tasks"]) == 1

    done = await tool.run(action="done", id=task_id)
    assert done.ok
    assert done.data["status"] == "done"
    assert (await tool.run(action="list")).data["tasks"] == []
    done_list = await tool.run(action="list", status="done")
    assert len(done_list.data["tasks"]) == 1

    reopened = await tool.run(action="reopen", id=task_id)
    assert reopened.ok
    assert reopened.data["status"] == "open"

    removed = await tool.run(action="remove", id=task_id)
    assert removed.ok
    assert (await tool.run(action="list", status="all")).data["tasks"] == []

    tool.store.close()


@pytest.mark.asyncio
async def test_add_requires_title(tmp_path) -> None:
    tool = _tool(tmp_path)
    result = await tool.run(action="add")
    assert not result.ok
    assert "title" in result.output.lower()
    tool.store.close()


@pytest.mark.asyncio
async def test_done_missing_id(tmp_path) -> None:
    tool = _tool(tmp_path)
    result = await tool.run(action="done")
    assert not result.ok
    assert "id" in result.output.lower()
    tool.store.close()


def test_write_actions_need_confirm_list_does_not(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    registry = ToolRegistry()
    registry.register(TasksTool(store))
    assert not registry.needs_confirm("tasks", {"action": "list"})
    for action in TASKS_WRITE_ACTIONS:
        assert registry.needs_confirm("tasks", {"action": action, "title": "x", "id": 1})
    assert not registry.needs_confirm(
        "tasks", {"action": "add", "title": "x"}, confirm_writes=False
    )
    store.close()


def test_describe_call_shows_task_fields(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    registry = ToolRegistry()
    registry.register(TasksTool(store))
    detail = registry.describe_call(
        "tasks",
        {"action": "add", "title": "File taxes", "due": "2026-04-15"},
    )
    assert "add" in detail
    assert "File taxes" in detail
    assert "2026-04-15" in detail
    assert "Remove task" in registry.describe_call("tasks", {"action": "remove", "id": 3})
    attach = registry.describe_call(
        "tasks", {"action": "attach", "id": 2, "goal_id": 9}
    )
    assert "Attach task #2" in attach
    assert "goal #9" in attach
    store.close()


def test_tasks_registered_when_archive_present(tmp_path, monkeypatch) -> None:
    from arelis import tools as tools_pkg
    from arelis.workspace import WorkspaceRoots

    monkeypatch.setattr(tools_pkg, "load_account", lambda: None)
    monkeypatch.setattr(tools_pkg, "load_sms_account", lambda: None)
    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(tmp_path)]}})
    store = MemoryStore(tmp_path / "memory.db")
    attended = tools_pkg.build_tool_registry(
        {"tools": {}, "agent": {}}, workspace, memory_store=store
    )
    assert "tasks" in attended.names()
    disabled = tools_pkg.build_tool_registry(
        {"tools": {"tasks": {"enabled": False}}, "agent": {}},
        workspace,
        memory_store=store,
    )
    assert "tasks" not in disabled.names()
    unattended = tools_pkg.build_tool_registry(
        {"tools": {}, "agent": {}}, workspace, allow_send=False
    )
    assert "tasks" not in unattended.names()
    store.close()


@pytest.mark.asyncio
async def test_add_attach_detach_goal_link(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    tool = TasksTool(store)
    goal_id = store.add_goal("Ship linking wave", kind="goal")
    assert goal_id is not None

    added = await tool.run(
        action="add", title="Write docs", goal_id=goal_id
    )
    assert added.ok
    tid = int(added.data["id"])
    assert added.data["goal_id"] == goal_id
    assert f"→ goal #{goal_id}" in added.output

    listed = await tool.run(action="list", goal_id=goal_id)
    assert listed.ok
    assert len(listed.data["tasks"]) == 1

    detached = await tool.run(action="detach", id=tid)
    assert detached.ok
    assert detached.data["goal_id"] is None
    assert "→ goal" not in detached.output

    attached = await tool.run(action="attach", id=tid, goal_id=goal_id)
    assert attached.ok
    assert attached.data["goal_id"] == goal_id

    bad = await tool.run(action="attach", id=tid, goal_id=99999)
    assert not bad.ok

    # Soft-delete goal clears FK (SET NULL).
    store.remove_goal(goal_id)
    row = store.get_task(tid)
    assert row is not None
    assert row.get("goal_id") is None

    store.close()


@pytest.mark.asyncio
async def test_briefing_shows_goal_link(tmp_path) -> None:
    from arelis.briefing import build_briefing
    from arelis.tools.base import ToolResult

    store = MemoryStore(tmp_path / "memory.db")
    gid = store.add_goal("Ship linking")
    store.add_task("Draft README", goal_id=gid)

    class _EmptyInbox:
        async def run(self, **kwargs):
            return ToolResult(
                ok=True,
                output="none",
                data={"messages": [], "matched": 0, "total": 0, "unread": 0},
            )

    text = await build_briefing(
        {"tools": {"briefing": {}}},
        store=store,
        inbox=_EmptyInbox(),  # type: ignore[arg-type]
    )
    assert "## Tasks" in text
    assert "Draft README" in text
    assert f"→ goal #{gid}" in text
    store.close()


@pytest.mark.asyncio
async def test_briefing_includes_open_tasks(tmp_path) -> None:
    from arelis.briefing import build_briefing
    from arelis.tools.base import ToolResult

    store = MemoryStore(tmp_path / "memory.db")
    store.add_task("Ship optics package", due="2026-08-12")

    class _EmptyInbox:
        async def run(self, **kwargs):
            return ToolResult(
                ok=True,
                output="none",
                data={"messages": [], "matched": 0, "total": 0, "unread": 0},
            )

    text = await build_briefing(
        {"tools": {"briefing": {}}},
        store=store,
        inbox=_EmptyInbox(),  # type: ignore[arg-type]
    )
    assert "## Tasks" in text
    assert "Ship optics package" in text
    assert "2026-08-12" in text
    store.close()


@pytest.mark.asyncio
async def test_briefing_stale_tasks_subsection(tmp_path) -> None:
    from arelis.briefing import build_briefing
    from arelis.tools.base import ToolResult

    store = MemoryStore(tmp_path / "memory.db")
    tid = store.add_task("Ancient open loop")
    assert tid is not None
    store._conn.execute(
        "UPDATE tasks SET created_at = ? WHERE id = ?",
        ("2026-01-01T12:00:00+00:00", tid),
    )
    store._conn.commit()

    class _EmptyInbox:
        async def run(self, **kwargs):
            return ToolResult(
                ok=True,
                output="none",
                data={"messages": [], "matched": 0, "total": 0, "unread": 0},
            )

    text = await build_briefing(
        {"tools": {"briefing": {}}},
        store=store,
        inbox=_EmptyInbox(),  # type: ignore[arg-type]
    )
    assert "## Tasks" in text
    assert "### Stale tasks" in text
    assert "Ancient open loop" in text
    assert "2026-01-01" in text
    store.close()
