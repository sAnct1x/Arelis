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
    DEFAULT_KIND,
    KINDS,
    RoomStore,
    match_enter_intent,
    match_leave_intent,
    slugify,
)


@pytest.fixture
def store(tmp_path: Path) -> RoomStore:
    return RoomStore(tmp_path / "rooms.yaml")


def test_a_room_survives_being_written_and_read_back(tmp_path: Path) -> None:
    path = tmp_path / "rooms.yaml"
    first = RoomStore(path)
    first.create(
        "Physics",
        purpose="Analysing the survey data.",
        root="Lab Notes",
        kind="analysis",
    )

    reopened = RoomStore(path)
    room = reopened.get("physics")

    assert room is not None
    assert room.name == "Physics"
    assert room.purpose == "Analysing the survey data."
    assert room.root == "Lab Notes"
    assert room.kind == "analysis"
    assert room.role == KINDS["analysis"].role


def test_the_file_is_the_interface_so_a_typo_costs_one_room(tmp_path: Path) -> None:
    """Rooms are YAML precisely so they can be hand-edited, and hands slip.

    Refusing to load the whole file over one bad entry would mean a stray
    character in the room somebody added last week takes away the nine rooms
    they have been using for months.
    """
    path = tmp_path / "rooms.yaml"
    path.write_text(
        "rooms:\n"
        "  good:\n"
        "    name: Good\n"
        "  broken: [not, a, mapping]\n"
        "  odd:\n"
        "    name: Odd\n"
        "    kind: nonsense\n",
        encoding="utf-8",
    )

    store = RoomStore(path)

    assert store.get("good") is not None
    assert store.get("broken") is None
    odd = store.get("odd")
    assert odd is not None and odd.kind == DEFAULT_KIND


def test_an_unreadable_file_is_no_rooms_rather_than_no_arelis(tmp_path: Path) -> None:
    path = tmp_path / "rooms.yaml"
    path.write_text("rooms: [oh, dear\n", encoding="utf-8")

    assert len(RoomStore(path)) == 0


def test_a_name_resolves_by_id_name_or_unique_prefix(store: RoomStore) -> None:
    store.create("Physics")
    store.create("Reading Group")

    assert store.find("physics").id == "physics"
    assert store.find("Physics").id == "physics"
    assert store.find("reading group").id == "reading-group"
    assert store.find("read").id == "reading-group"


def test_an_ambiguous_name_resolves_to_nothing(store: RoomStore) -> None:
    """Entering the wrong room swaps the thread and the folder silently.

    Two rooms starting with the same word is ordinary — "physics" and "physics
    reading" — and picking whichever sorts first would be a coin flip over
    which conversation the next answer belongs to.
    """
    store.create("Physics")
    store.create("Physics Reading")

    assert store.find("phys") is None


def test_a_room_cannot_take_a_name_that_means_no_room(store: RoomStore) -> None:
    """`/room general` and `/leave` have to keep meaning what they say."""
    with pytest.raises(ValueError):
        store.create("general")
    with pytest.raises(ValueError):
        store.create("leave")


def test_a_room_needs_a_name_with_something_in_it(store: RoomStore) -> None:
    with pytest.raises(ValueError):
        store.create("   ")
    with pytest.raises(ValueError):
        store.create("!!!")


def test_two_rooms_cannot_share_an_id(store: RoomStore) -> None:
    store.create("Physics")
    with pytest.raises(ValueError):
        store.create("physics")


def test_forgetting_a_room_leaves_the_others_and_closes_it(store: RoomStore) -> None:
    store.create("Physics")
    store.create("Writing")
    store.set_active("physics")

    assert store.remove("physics") is True
    assert store.active is None
    assert [r.id for r in store.all()] == ["writing"]


def test_the_purpose_reaches_the_prompt_with_the_folder(store: RoomStore) -> None:
    room = store.create(
        "Physics", purpose="Analysing the survey data.", root="Lab Notes"
    )

    block = room.prompt_block()

    assert "Physics" in block
    assert "Analysing the survey data." in block
    assert "Lab Notes" in block


def test_slugs_stay_sayable(store: RoomStore) -> None:
    assert slugify("Physics Lab") == "physics-lab"
    assert slugify("  Weird   Spacing ") == "weird-spacing"
    # Folded, not dropped: a room called Café is `cafe`, and `caf` would be a
    # word nobody would guess when typing /room.
    assert slugify("Café Notes") == "cafe-notes"


# -- what counts as asking to change rooms ---------------------------------


@pytest.mark.parametrize(
    "said",
    [
        "let's work on physics",
        "lets work on physics",
        "Arelis, let's work on physics",
        "hey arelis lets work on the physics room",
        "open the physics room",
        "switch to physics",
        "go to the physics room",
        "work in physics",
        "can we work on physics?",
    ],
)
def test_these_are_asking_for_a_room(said: str) -> None:
    assert match_enter_intent(said) is not None


@pytest.mark.parametrize(
    "said",
    [
        "what is the physics of a pendulum",
        "tell me about the physics room in the library",
        "I was working on physics yesterday",
        "how does interference work",
        "open the file physics.py",
        "",
    ],
)
def test_these_are_not(said: str) -> None:
    """A false positive silently changes which conversation she is in.

    `open the file physics.py` is the one that matters: it starts with a verb
    this pattern knows and has to lose to the word `file`, or asking for a file
    moves the whole session.
    """
    found = match_enter_intent(said)
    assert found is None or found.lower() not in {"physics", "the physics"}


def test_the_name_still_has_to_be_a_real_room(store: RoomStore) -> None:
    """The pattern is half of it. Resolution is the half that says no.

    "let's work on the budget" is an ordinary sentence in a house with no
    budget room, and has to stay one.
    """
    store.create("Physics")

    assert store.find(match_enter_intent("let's work on the budget") or "") is None
    assert store.find(match_enter_intent("let's work on physics") or "").id == "physics"


@pytest.mark.parametrize(
    "said",
    [
        "leave the room",
        "exit the room",
        "close the room",
        "back to general",
        "go back to the main conversation",
    ],
)
def test_these_are_asking_to_come_out(said: str) -> None:
    assert match_leave_intent(said)


@pytest.mark.parametrize(
    "said",
    ["leave the door open", "close the file", "general relativity", "back to work"],
)
def test_these_are_not_asking_to_come_out(said: str) -> None:
    assert not match_leave_intent(said)
