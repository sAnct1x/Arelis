"""The room definition file, and what someone has to say to get into one.

A room decides which folder she writes to and which conversation she is
continuing, so the two dangerous operations are resolving a name to the wrong
room and treating an ordinary sentence as a request to change rooms. Most of
what is pinned here is about refusing to guess.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.rooms import (
    KINDS,
    PHYSICS_DISPLAY_NAME,
    PHYSICS_PURPOSE,
    PHYSICS_ROOM_ID,
    RoomStore,
    is_perma,
)


@pytest.fixture
def store(tmp_path: Path) -> RoomStore:
    return RoomStore(tmp_path / "rooms.yaml")


def test_a_room_survives_being_written_and_read_back(tmp_path: Path) -> None:
    path = tmp_path / "rooms.yaml"
    first = RoomStore(path)
    first.create(
        "Survey",
        purpose="Analysing the survey data.",
        root="Lab Notes",
        kind="analysis",
    )

    reopened = RoomStore(path)
    room = reopened.get("survey")

    assert room is not None
    assert room.name == "Survey"
    assert room.purpose == "Analysing the survey data."
    assert room.root == "Lab Notes"
    assert room.kind == "analysis"
    assert room.role == KINDS["analysis"].role
    assert "code" not in KINDS["analysis"].skills
    assert "science" in KINDS["analysis"].skills
    assert "analyze" in KINDS["analysis"].skills
    assert "document" in KINDS["writing"].skills
    assert "workspace" in KINDS["writing"].skills
    assert KINDS["code"].skills == ("workspace", "code")
    from arelis.core.skills import SKILL_CARDS

    assert "code" in SKILL_CARDS
    assert SKILL_CARDS["code"].requires_tool == "run_script"


def test_a_fresh_store_has_physics(store: RoomStore) -> None:
    room = store.get(PHYSICS_ROOM_ID)
    assert room is not None
    assert is_perma(room.id)
    assert room.name == PHYSICS_DISPLAY_NAME
    assert room.name == "Reality"
    assert room.purpose == PHYSICS_PURPOSE
    assert room.kind == "analysis"
    assert room.root == ""


def test_forgetting_physics_is_refused(store: RoomStore) -> None:
    store.set_active(PHYSICS_ROOM_ID)
    with pytest.raises(ValueError, match="permanent"):
        store.remove(PHYSICS_ROOM_ID)
    assert store.get(PHYSICS_ROOM_ID) is not None
    assert store.active_id == PHYSICS_ROOM_ID


# -- what counts as asking to change rooms ---------------------------------


