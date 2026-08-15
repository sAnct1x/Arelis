"""Past conversations are searchable; a miss is a miss, not an invention."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.core.agent_loop import TOOL_POLICY
from arelis.core.memory import SessionMemory
from arelis.memory import MemoryStore
from arelis.tools import build_tool_registry
from arelis.tools.recall import RecallTool
from arelis.workspace import WorkspaceRoots


@pytest.mark.asyncio
async def test_recall_search_returns_dated_excerpts(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    memory = SessionMemory(sink=store)
    memory.add("user", "I climb at the local wall on Thursdays.")
    memory.add("assistant", "I will remember you climb.")

    tool = RecallTool(store)
    result = await tool.run(action="search", query="climb")
    assert result.ok
    assert "climb" in result.output.lower()
    assert "session=" in result.output
    assert result.data["hits"]
    assert result.data["hits"][0]["session_id"] == store.session_id
    store.close()


@pytest.mark.asyncio
async def test_recall_session_reads_a_past_conversation_back(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    sid = store.start_session()
    memory = SessionMemory(sink=store)
    memory.add("user", "Calibrate the interferometer tonight.")
    memory.add("assistant", "I will help with the pointing model.")

    tool = RecallTool(store)
    result = await tool.run(action="session", session_id=sid)
    assert result.ok
    assert "Calibrate the interferometer" in result.output
    assert "pointing model" in result.output
    assert "user:" in result.output
    store.close()


@pytest.mark.asyncio
async def test_recall_search_skips_inbound_sms_notices(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    memory = SessionMemory(sink=store)
    memory.add("user", "how would we approach this")
    memory.add("notice", "Text from Robin Hale: Bro that man is SSG")
    memory.add("assistant", "A visualization interface.")

    tool = RecallTool(store)
    result = await tool.run(action="search", query="Robin")
    assert result.ok
    assert "Bro that man is SSG" not in result.output
    session = await tool.run(action="session", session_id=store.session_id or "")
    assert session.ok
    assert "notice:" not in session.output
    assert "visualization" in session.output.lower()
    store.close()


@pytest.mark.asyncio
async def test_a_search_miss_says_so_rather_than_inventing(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    tool = RecallTool(store)
    result = await tool.run(action="search", query="xylophone-banjo-42")
    assert result.ok
    assert "No past messages, files, or mail matched" in result.output
    assert "ask them rather than inventing" in result.output
    store.close()


def test_recall_is_registered_as_a_read_tool(tmp_path: Path) -> None:
    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(tmp_path)]}})
    store = MemoryStore(tmp_path / "memory.db")
    registry = build_tool_registry(
        {"tools": {}, "agent": {}}, workspace, memory_store=store
    )
    assert "recall" in registry.names()
    tool = registry.get("recall")
    assert tool is not None
    assert tool.risk == "read"
    assert not registry.needs_confirm("recall", {"action": "search", "query": "x"})
    store.close()


def test_tool_policy_requires_a_memory_search_before_claiming_ignorance() -> None:
    assert "recall" in TOOL_POLICY
    assert "before claiming you do not know" in TOOL_POLICY.lower()


def test_the_persona_no_longer_claims_to_have_no_session_memory() -> None:
    """Line that was true before recall would now teach her to lie."""
    text = Path("arelis/persona/arelis.md").read_text(encoding="utf-8")
    assert "no memory of previous sessions" not in text
    assert "recall tool" in text
