"""A crash mid-stream must keep the assistant text already written.

The archive used to write the assistant row only when the turn finished.
A kill during the stream left the user turn with no reply, and Stop did
not keep the words already on screen. This file drives AgentLoop's
publish / retract / cancel path so a revert of that hook fails.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.memory import SessionMemory
from arelis.memory import MemoryStore
from arelis.tools.base import ToolRegistry


def _loop(memory: SessionMemory) -> AgentLoop:
    return AgentLoop(
        EventBus(),
        object(),
        ToolRegistry(),
        memory,
        "PERSONA",
        {},
        request_confirm=lambda *_: False,
        is_cancelled=lambda: False,
    )


def test_streamed_reply_survives_a_crash_before_the_turn_ends(tmp_path: Path) -> None:
    crash_path = tmp_path / "crash.db"
    store = MemoryStore(crash_path)
    sid = store.start_session()
    memory = SessionMemory(sink=store)
    memory.add("user", "explain the orbit")
    loop = _loop(memory)
    asyncio.run(loop._publish_delta("The orbit is"))
    asyncio.run(loop._publish_delta(" elliptical."))
    store.flush()
    store.close()

    crashed = MemoryStore(crash_path)
    rows = crashed.get_messages(sid)
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert rows[1]["content"] == "The orbit is elliptical."
    crashed.close()

    store = MemoryStore(tmp_path / "live.db")
    sid = store.start_session()
    memory = SessionMemory(sink=store)
    memory.add("user", "explain the orbit")
    loop = _loop(memory)
    asyncio.run(loop._publish_delta("The orbit is"))
    memory.add("assistant", "The orbit is elliptical.", "note")
    rows = store.get_messages(sid)
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert rows[1]["content"] == "The orbit is elliptical."
    assert rows[1]["note"] == "note"

    asyncio.run(loop._publish_delta("withdrawn"))
    asyncio.run(loop._retract())
    assert [row["content"] for row in store.get_messages(sid)] == [
        "explain the orbit",
        "The orbit is elliptical.",
    ]

    asyncio.run(loop._publish_delta("Partial answer"))
    asyncio.run(loop._cancel_notice())
    stopped = store.get_messages(sid)
    assert stopped[-1]["role"] == "assistant"
    assert "Partial answer" in stopped[-1]["content"]
    assert "Stopped" in stopped[-1]["content"]
    store.close()

@pytest.mark.parametrize(
    ("streamed", "sources"),
    [
        ("", []),
        ("Hello there.", [("Example", "https://example.com/a")]),
    ],
    ids=["empty_streamed", "sources_remainder"],
)
def test_finish_writes_a_single_assistant_row(
    tmp_path: Path,
    streamed: str,
    sources: list[tuple[str, str]],
) -> None:
    """Mutant: _finish publishes a catch-up delta after memory.add, which
    starts a second open assistant row that is never sealed."""
    store = MemoryStore(tmp_path / "finish.db")
    sid = store.start_session()
    memory = SessionMemory(sink=store)
    memory.add("user", "hi")
    loop = _loop(memory)
    if streamed:
        asyncio.run(loop._publish_delta(streamed))
    asyncio.run(loop._finish("Hello there.", sources, streamed=streamed))
    assistant = [row for row in store.get_messages(sid) if row["role"] == "assistant"]
    assert len(assistant) == 1
    assert assistant[0]["content"].startswith("Hello there.")
    if sources:
        assert "https://example.com/a" in assistant[0]["content"]
    store.close()

