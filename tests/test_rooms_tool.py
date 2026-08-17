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
from arelis.tools.base import ToolRegistry
from arelis.tools.rooms_tool import RoomsTool


@pytest.fixture
def store(tmp_path: Path) -> RoomStore:
    return RoomStore(tmp_path / "rooms.yaml")


@pytest.mark.asyncio
async def test_one_sentence_becomes_a_configured_room(store: RoomStore) -> None:
    tool = RoomsTool(store)

    result = await tool.run(
        action="create",
        name="Physics",
        purpose="Analysing the survey data.",
        root="Lab Notes",
        kind="analysis",
    )

    assert result.ok
    room = store.get("physics")
    assert room.purpose == "Analysing the survey data."
    assert room.root == "Lab Notes"
    assert room.kind == "analysis"


@pytest.mark.asyncio
async def test_creating_a_room_says_how_to_walk_into_it(store: RoomStore) -> None:
    """The tool cannot enter, so the answer has to hand the user the way in."""
    result = await RoomsTool(store).run(action="create", name="Physics")

    assert "let's work on Physics" in result.output or "/room physics" in result.output


@pytest.mark.asyncio
async def test_the_tool_cannot_enter_a_room(store: RoomStore) -> None:
    """Entering mid-turn would swap SessionMemory under the running turn.

    Pinned as an absence: there is no action for it, and adding one later has to
    be a deliberate decision that solves the thread swap, not a convenience.
    """
    store.create("Physics")
    tool = RoomsTool(store)

    assert "enter" not in tool.parameters_schema["properties"]["action"]["enum"]

    result = await tool.run(action="enter", name="Physics")

    assert not result.ok
    assert store.active is None


@pytest.mark.asyncio
async def test_a_room_needs_a_name_and_says_so(store: RoomStore) -> None:
    result = await RoomsTool(store).run(action="create", purpose="Something vague.")

    assert not result.ok
    assert "name" in result.output.lower()


@pytest.mark.asyncio
async def test_a_duplicate_is_refused_rather_than_merged(store: RoomStore) -> None:
    store.create("Physics", purpose="The original.")

    result = await RoomsTool(store).run(action="create", name="physics")

    assert not result.ok
    assert store.get("physics").purpose == "The original."


@pytest.mark.asyncio
async def test_an_update_changes_only_what_was_passed(store: RoomStore) -> None:
    store.create("Physics", purpose="The original.", root="Lab Notes")

    result = await RoomsTool(store).run(
        action="update", name="physics", purpose="Sharper now."
    )

    assert result.ok
    room = store.get("physics")
    assert room.purpose == "Sharper now."
    assert room.root == "Lab Notes"


@pytest.mark.asyncio
async def test_listing_nothing_explains_what_a_room_is(store: RoomStore) -> None:
    """An empty list is the model's cue to offer one, so it has to read as one."""
    result = await RoomsTool(store).run(action="list")

    assert result.ok
    assert result.data["rooms"] == []
    assert "create" in result.output


def test_making_a_room_asks_first() -> None:
    """Writes go through the confirm card, the way contacts and tasks do."""
    registry = ToolRegistry()
    registry.register(RoomsTool(RoomStore()))

    assert registry.needs_confirm("rooms", {"action": "create", "name": "Physics"})
    assert registry.needs_confirm("rooms", {"action": "update", "name": "Physics"})
    assert registry.needs_confirm("rooms", {"action": "forget", "name": "Physics"})
    assert not registry.needs_confirm("rooms", {"action": "list"})
    assert not registry.needs_confirm("rooms", {"action": "get", "name": "Physics"})
