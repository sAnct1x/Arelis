"""She must be able to read back what she was told to remember.

`memory` shipped as write-only: remember, forget, prefer, decide, episode.
Nothing in the tool could answer "what do you remember about me?" — the store
has had `list_facts`, `list_preferences`, `list_decisions` and `list_episodes`
the whole time, and no action reached them.

The workaround was `recall`, which searches conversation transcripts. That
answers a different question. A fact survives precisely because it was lifted
out of a transcript and stored on purpose; searching transcripts to find it
again is the long way round, and it silently fails once the session that
produced it is pruned.

`list` stays out of MEMORY_WRITE_ACTIONS in tools/policy.py, so reading does
not raise the confirm card. Writes still do.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.memory import MemoryStore
from arelis.tools.memory_tool import MemoryTool
from arelis.tools.policy import MEMORY_WRITE_ACTIONS, action_is_write


def _tool(tmp_path: Path) -> tuple[MemoryTool, MemoryStore]:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    return MemoryTool(store), store


@pytest.mark.asyncio
async def test_reading_memory_back_does_not_raise_the_confirm_card(
    tmp_path: Path,
) -> None:
    """The whole point. A read behind an Allow click is a read nobody does."""
    assert "list" not in MEMORY_WRITE_ACTIONS
    assert action_is_write("memory", {"action": "list"}) is False
    assert action_is_write("memory", {"action": "remember"}) is True


@pytest.mark.asyncio
async def test_a_remembered_fact_comes_back_out(tmp_path: Path) -> None:
    tool, store = _tool(tmp_path)
    try:
        await tool.run(action="remember", fact="I climb on weekends")
        result = await tool.run(action="list")
        assert result.ok
        assert "I climb on weekends" in result.output
    finally:
        store.close()


@pytest.mark.asyncio
async def test_a_forgotten_fact_stops_coming_back(tmp_path: Path) -> None:
    """forget deactivates rather than deletes, so list must filter on status."""
    tool, store = _tool(tmp_path)
    try:
        await tool.run(action="remember", fact="I climb on weekends")
        await tool.run(action="remember", fact="I drink my coffee black")
        await tool.run(action="forget", fact="I climb on weekends")
        result = await tool.run(action="list")
        assert "I drink my coffee black" in result.output
        assert "I climb on weekends" not in result.output
    finally:
        store.close()


@pytest.mark.asyncio
async def test_preferences_and_episodes_come_back_too(tmp_path: Path) -> None:
    tool, store = _tool(tmp_path)
    try:
        await tool.run(action="prefer", key="units", value="metric")
        await tool.run(action="episode", summary="Rebuilt the eval board")
        result = await tool.run(action="list")
        assert "units" in result.output
        assert "metric" in result.output
        assert "Rebuilt the eval board" in result.output
    finally:
        store.close()


@pytest.mark.asyncio
async def test_forget_drops_pasted_episode_list(tmp_path: Path) -> None:
    """Live dump: forget only matched facts, then math ate the turn."""
    tool, store = _tool(tmp_path)
    try:
        keep = "Rebuilt the eval board"
        await tool.run(action="episode", summary=keep)
        stamps = (
            "20260810-011327-7c7369",
            "20260810-005019-dbc9ac",
            "20260810-004830-af83e0",
            "20260810-004632-236df1",
        )
        for stamp in stamps:
            await tool.run(action="episode", summary=f"e2e episode {stamp}")
        blob = (
            "all of those episodes, Episodes:\n"
            + "\n".join(f"e2e episode {stamp}" for stamp in stamps)
        )
        result = await tool.run(action="forget", fact=blob)
        assert result.ok, result.output
        assert result.data["episodes"] == 4
        listed = await tool.run(action="list")
        assert keep in listed.output
        for stamp in stamps:
            assert stamp not in listed.output
    finally:
        store.close()


@pytest.mark.asyncio
async def test_one_kind_can_be_asked_for_on_its_own(tmp_path: Path) -> None:
    tool, store = _tool(tmp_path)
    try:
        await tool.run(action="remember", fact="I climb on weekends")
        await tool.run(action="prefer", key="units", value="metric")
        result = await tool.run(action="list", type="preference")
        assert "units" in result.output
        assert "I climb on weekends" not in result.output
    finally:
        store.close()


@pytest.mark.asyncio
async def test_decisions_need_the_project_they_were_filed_under(
    tmp_path: Path,
) -> None:
    """store.list_decisions takes a project and has no all-projects query.

    So `list` without one cannot show decisions, and must say that rather than
    imply there are none. "I have no decisions stored" when the caller simply
    did not name a project is exactly the confident-wrong answer this tool is
    supposed to prevent.
    """
    tool, store = _tool(tmp_path)
    try:
        await tool.run(action="decide", project="arelis", text="Cancel phase 2")

        scoped = await tool.run(action="list", type="decision", project="arelis")
        assert "Cancel phase 2" in scoped.output

        unscoped = await tool.run(action="list", type="decision")
        assert "project" in unscoped.output.lower()
        assert "Cancel phase 2" not in unscoped.output
    finally:
        store.close()


@pytest.mark.asyncio
async def test_an_empty_memory_says_so_without_sounding_broken(
    tmp_path: Path,
) -> None:
    tool, store = _tool(tmp_path)
    try:
        result = await tool.run(action="list")
        assert result.ok, "nothing stored yet is not a failure"
        assert "nothing" in result.output.lower() or "no " in result.output.lower()
    finally:
        store.close()


@pytest.mark.asyncio
async def test_the_list_is_capped_so_a_full_memory_cannot_flood_the_turn(
    tmp_path: Path,
) -> None:
    tool, store = _tool(tmp_path)
    try:
        for i in range(60):
            await tool.run(action="remember", fact=f"fact number {i}")
        result = await tool.run(action="list", limit=5)
        assert result.ok
        shown = result.output.count("fact number")
        assert shown == 5, f"asked for 5, got {shown}"
    finally:
        store.close()
