"""Making a room by describing one, and the line the tool must not cross.

The slash commands need you to know them. This is the half that works from
"make me a physics room for the survey data" — so the interesting cases are
whether it fills the room in from one sentence, and whether it can be talked
into entering one, which it must not be: a room swap replaces the conversation
thread, and this runs inside a turn that is using it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.rooms import RoomStore
from arelis.tools.rooms_tool import RoomsTool


@pytest.fixture
def store(tmp_path: Path) -> RoomStore:
    return RoomStore(tmp_path / "rooms.yaml")


@pytest.mark.asyncio
async def test_one_sentence_becomes_a_configured_room(store: RoomStore) -> None:
    tool = RoomsTool(store)

    result = await tool.run(
        action="create",
        name="Survey",
        purpose="Analysing the survey data.",
        root="Lab Notes",
        kind="analysis",
    )

    assert result.ok
    room = store.get("survey")
    assert room.purpose == "Analysing the survey data."
    assert room.root == "Lab Notes"
    assert room.kind == "analysis"


@pytest.mark.asyncio
async def test_a_duplicate_is_refused_rather_than_merged(store: RoomStore) -> None:
    result = await RoomsTool(store).run(action="create", name="physics")

    assert not result.ok
    assert store.get("physics") is not None


@pytest.mark.asyncio
async def test_forgetting_physics_is_refused(store: RoomStore) -> None:
    result = await RoomsTool(store).run(action="forget", name="physics")

    assert not result.ok
    assert "permanent" in result.output
    assert store.get("physics") is not None
