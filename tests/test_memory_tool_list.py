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
async def test_remember_keeps_value_beside_the_fact(tmp_path: Path) -> None:
    """fact and value both set must store the number, not only the label."""
    tool, store = _tool(tmp_path)
    try:
        result = await tool.run(
            action="remember",
            fact="weekly run distance",
            value="24.14016 km",
        )
        assert result.ok
        assert "24.14016" in result.output
        listed = await tool.run(action="list")
        assert "24.14016" in listed.output
        stored = [str(row["text"]) for row in store.list_facts(status="active")]
        assert stored == ["weekly run distance: 24.14016 km"]
    finally:
        store.close()


