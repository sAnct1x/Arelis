"""Leaving a room sits back on the general chat from this load.

The room thread is a different row. /leave must restore the seat you
were on before you walked in — including an empty new chat — and must
not fall through to some other filled conversation in History.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from arelis.config import PROJECT_ROOT
from arelis.core.bus import EventBus
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.core.orchestrator_rooms import enter_room, leave_room
from arelis.memory import MemoryStore
from arelis.rooms import PHYSICS_ROOM_ID, RoomStore
from arelis.tools.base import ToolRegistry
from arelis.workspace import WorkspaceRoots


class _StubRouter:
    default_role = "fast"
    active_model = None
    models = {"fast": "mock"}

    def model_for(self, role=None):
        return "mock"

    async def ensure_role(self, role, *, force: bool = False):
        del force
        return "mock"

    def mark_sticky(self, role) -> None:
        return None

    async def stream(self, role, messages, **kwargs):
        if False:
            yield ("token", "")
        return

    async def close(self):
        return None


def _orch(tmp_path: Path, store: MemoryStore) -> Orchestrator:
    (tmp_path / "lab").mkdir(exist_ok=True)
    workspace = WorkspaceRoots.from_paths([str(tmp_path / "lab")], active="lab")
    rooms = RoomStore(tmp_path / "rooms.yaml")
    memory = SessionMemory(sink=store)
    return Orchestrator(
        EventBus(),
        _StubRouter(),  # type: ignore[arg-type]
        ToolRegistry(),
        {
            "agent": {},
            "_persona_path": str(PROJECT_ROOT / "arelis" / "persona" / "arelis.md"),
            "_workspace": workspace,
            "_rooms": rooms,
        },
        memory,
    )


@pytest.fixture
async def seat(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory.db")
    orch = _orch(tmp_path, store)
    task = asyncio.create_task(orch.bus.run())
    try:
        yield orch, store
    finally:
        orch.bus.stop()
        task.cancel()
        store.close()


@pytest.mark.asyncio
async def test_leave_returns_to_the_chat_you_were_in(seat) -> None:
    orch, store = seat
    store.start_session()
    orch.memory.add("user", "general talk")
    general = store.session_id
    room = orch.rooms.get(PHYSICS_ROOM_ID)
    assert room is not None

    await enter_room(orch, room)
    await orch.bus.drain()
    assert store.session_id != general

    await leave_room(orch)
    await orch.bus.drain()

    assert store.session_id == general
    assert orch.rooms.active_id == ""
    assert orch.memory.as_ollama()[0]["content"] == "general talk"


@pytest.mark.asyncio
async def test_leave_returns_to_this_load_empty_new_chat(seat) -> None:
    orch, store = seat
    empty = store.start_session()
    assert store.get_messages(empty) == []
    room = orch.rooms.get(PHYSICS_ROOM_ID)
    assert room is not None

    await enter_room(orch, room)
    await orch.bus.drain()

    await leave_room(orch)
    await orch.bus.drain()

    assert store.session_id == empty
    assert store.get_session(empty) is not None
    assert store.get_messages(empty) == []


@pytest.mark.asyncio
async def test_leave_after_fresh_enter_does_not_jump_to_an_old_chat(seat) -> None:
    orch, store = seat
    older = store.start_session()
    orch.memory.add("user", "last night")
    glass = store.start_glass_session()
    assert store.get_messages(glass) == []
    room = orch.rooms.get(PHYSICS_ROOM_ID)
    assert room is not None

    await enter_room(orch, room, silent=True, fresh=True)
    await orch.bus.drain()

    await leave_room(orch)
    await orch.bus.drain()

    assert store.session_id == glass
    assert store.get_session(older) is not None
    assert store.get_messages(older)[0]["content"] == "last night"


@pytest.mark.asyncio
async def test_leave_without_a_parked_seat_does_not_pick_history(seat) -> None:
    orch, store = seat
    filled = store.start_session()
    orch.memory.add("user", "an old thread")
    room = orch.rooms.get(PHYSICS_ROOM_ID)
    assert room is not None
    await enter_room(orch, room)
    await orch.bus.drain()
    orch._general_session = ""

    await leave_room(orch)
    await orch.bus.drain()

    assert store.session_id != filled
    assert store.get_messages(store.session_id) == []
