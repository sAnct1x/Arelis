"""Walking into a room, and what moves when you do.

Entering a room swaps three things at once — the conversation thread, the active
project, and the model role — and the whole value of the feature is that the
first one is real. A room that shares the general thread is a system prompt with
extra steps; you would come back to it tomorrow and find last night's weather
question in the middle of three weeks of analysis.

The other half is the refusals. A thread swap while a turn is running would
answer one conversation into another, and a spoken sentence that merely sounds
like navigation must not move anything at all.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from arelis.config import PROJECT_ROOT
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.memory import MemoryStore
from arelis.rooms import RoomStore
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


class _Harness:
    """One orchestrator on a running bus, with what it published kept."""

    def __init__(self, tmp_path: Path) -> None:
        self.store = MemoryStore(tmp_path / "memory.db")
        self.store.start_session()
        self.rooms = RoomStore(tmp_path / "rooms.yaml")
        lab = tmp_path / "lab"
        lab.mkdir(exist_ok=True)
        notes = tmp_path / "notes"
        notes.mkdir(exist_ok=True)
        self.workspace = WorkspaceRoots.from_paths(
            [str(lab), str(notes)], active="lab"
        )
        self.memory = SessionMemory(sink=self.store)
        self.bus = EventBus()
        self.said: list[str] = []
        self.rooms_seen: list[dict] = []
        self.bus.subscribe(EventType.ASSISTANT_DONE, self._done)
        self.bus.subscribe(EventType.ROOM_CHANGED, self._room)
        self.orchestrator = Orchestrator(
            self.bus,
            _StubRouter(),  # type: ignore[arg-type]
            ToolRegistry(),
            {
                "agent": {},
                "_persona_path": str(
                    PROJECT_ROOT / "arelis" / "persona" / "arelis.md"
                ),
                "_workspace": self.workspace,
                "_rooms": self.rooms,
            },
            self.memory,
        )
        self._task: asyncio.Task | None = None

    async def _done(self, event: Event) -> None:
        self.said.append(str(event.payload.get("text") or ""))

    async def _room(self, event: Event) -> None:
        self.rooms_seen.append(dict(event.payload))

    async def start(self) -> None:
        self._task = asyncio.create_task(self.bus.run())

    async def say(self, text: str) -> None:
        await self.bus.publish(Event(EventType.USER_MESSAGE, {"text": text}))
        await self.bus.drain()

    async def stop(self) -> None:
        self.bus.stop()
        if self._task is not None:
            self._task.cancel()
        self.store.close()


@pytest.fixture
async def harness(tmp_path: Path):
    h = _Harness(tmp_path)
    await h.start()
    try:
        yield h
    finally:
        await h.stop()


@pytest.mark.asyncio
async def test_a_room_keeps_its_own_conversation(harness) -> None:
    """The reason rooms exist, stated as the thing that must be true.

    The general thread and the room's thread are different rows with different
    messages, and stepping between them does not mix or lose either.
    """
    harness.memory.add("user", "what is the weather")
    general = harness.store.session_id

    await harness.say("/room new physics")
    in_room = harness.store.session_id
    harness.memory.add("user", "three weeks of analysis")

    assert in_room != general
    assert harness.memory.as_ollama()[0]["content"] == "three weeks of analysis"

    await harness.say("/leave")

    assert harness.store.session_id == general
    assert harness.memory.as_ollama()[0]["content"] == "what is the weather"

    await harness.say("/room physics")

    assert harness.store.session_id == in_room
    assert harness.memory.as_ollama()[0]["content"] == "three weeks of analysis"


@pytest.mark.asyncio
async def test_entering_a_room_points_the_workspace_at_its_folder(harness) -> None:
    harness.rooms.create("Physics", root="notes")

    await harness.say("/room physics")

    assert harness.workspace.active == "notes"


@pytest.mark.asyncio
async def test_help_lists_every_room_verb_that_exists(harness) -> None:
    """A command absent from `/help` is a command nobody finds.

    `forget` shipped working and undocumented, which is the worse half of the
    two: the operator cannot discover it, and cannot discover that their rooms
    are removable at all.
    """
    await harness.say("/help")
    help_text = harness.said[-1]

    for verb in ("/rooms", "/room new", "/room set", "/room forget", "/leave"):
        assert verb in help_text, f"`{verb}` works but /help never mentions it"


@pytest.mark.asyncio
async def test_changing_the_kind_leans_the_model_now_not_next_time(harness) -> None:
    harness.rooms.create("Physics")
    await harness.say("/room physics")
    assert harness.orchestrator.router.default_role == "fast"

    await harness.say("/room set kind research")
    assert harness.orchestrator.router.default_role == "research"

    await harness.say("/room set kind analysis")
    assert harness.orchestrator.router.default_role == "fast"


@pytest.mark.asyncio
async def test_the_folder_is_named_the_way_the_operator_named_it(harness) -> None:
    """A project name is a path component, so its case is not cosmetic."""
    harness.rooms.create("Physics", root="notes")

    await harness.say("/room physics")

    assert "Working in `notes`" in harness.said[-1]


@pytest.mark.asyncio
async def test_a_room_whose_folder_vanished_still_opens(harness) -> None:
    """Roots are edited in Settings, rooms are edited in a file; they drift.

    Refusing to open the room would strand the conversation inside it, which is
    the part that cannot be rebuilt. Paths keep resolving against whatever is
    active and the answer says so.
    """
    harness.rooms.create("Physics", root="deleted-project")

    await harness.say("/room physics")

    assert harness.rooms.active_id == "physics"
    assert harness.workspace.active == "lab"
    assert "deleted-project" in harness.said[-1]


@pytest.mark.asyncio
async def test_the_room_kind_sets_the_model_chip(harness) -> None:
    harness.rooms.create("Physics", kind="research")

    await harness.say("/room physics")

    assert harness.orchestrator.router.default_role == "research"


@pytest.mark.asyncio
async def test_saying_it_works_when_the_room_exists(harness) -> None:
    harness.rooms.create("Physics")

    await harness.say("let's work on physics")

    assert harness.rooms.active_id == "physics"


@pytest.mark.asyncio
async def test_saying_it_about_nothing_is_just_a_sentence(harness) -> None:
    """No budget room, so this is a normal turn and the thread must not move."""
    harness.rooms.create("Physics")
    before = harness.store.session_id

    await harness.say("let's work on the budget")

    assert harness.rooms.active_id == ""
    assert harness.store.session_id == before
    assert harness.rooms_seen == []


@pytest.mark.asyncio
async def test_a_room_swap_is_refused_while_a_turn_is_running(harness) -> None:
    """Both own SessionMemory. Interleaving them answers into the wrong room."""
    harness.rooms.create("Physics")

    async def _forever() -> None:
        await asyncio.sleep(30)

    harness.orchestrator._turn_task = asyncio.create_task(_forever())
    try:
        await harness.say("/room physics")

        assert harness.rooms.active_id == ""
        assert "Finish or stop" in harness.said[-1]
    finally:
        harness.orchestrator._turn_task.cancel()


@pytest.mark.asyncio
async def test_leaving_returns_to_the_thread_you_left(harness) -> None:
    harness.memory.add("user", "general talk")
    general = harness.store.session_id
    await harness.say("/room new physics")

    await harness.say("/leave")

    assert harness.store.session_id == general
    assert harness.rooms.active_id == ""
    assert harness.rooms_seen[-1]["room_id"] == ""


@pytest.mark.asyncio
async def test_leaving_when_you_are_nowhere_says_so(harness) -> None:
    await harness.say("/leave")

    assert "No room is open" in harness.said[-1]


@pytest.mark.asyncio
async def test_asking_for_a_room_that_does_not_exist_offers_to_make_it(
    harness,
) -> None:
    await harness.say("/room chemistry")

    assert "/room new chemistry" in harness.said[-1]
    assert harness.rooms.active_id == ""


@pytest.mark.asyncio
async def test_the_room_is_configured_by_talking_to_it(harness) -> None:
    await harness.say("/room new physics")

    await harness.say("/room set purpose analysing the survey data")
    await harness.say("/room set root notes")

    room = harness.rooms.get("physics")
    assert room.purpose == "analysing the survey data"
    assert room.root == "notes"
    assert harness.workspace.active == "notes"


@pytest.mark.asyncio
async def test_changing_a_room_repaints_the_banner(harness) -> None:
    """Found by the smoke run, not by a unit test — so it gets one now.

    The strip is the only place the purpose and the folder are visible. Writing
    them to disk without republishing left the banner describing a room that no
    longer existed in that form, and it looked exactly like the setting had not
    taken.
    """
    await harness.say("/room new physics")
    seen_before = len(harness.rooms_seen)

    await harness.say("/room set purpose analysing the survey data")

    assert len(harness.rooms_seen) == seen_before + 1
    assert harness.rooms_seen[-1]["purpose"] == "analysing the survey data"
    assert harness.rooms_seen[-1]["room_id"] == "physics"


@pytest.mark.asyncio
async def test_a_root_that_is_not_a_project_is_refused_with_the_list(
    harness,
) -> None:
    await harness.say("/room new physics")

    await harness.say("/room set root nowhere")

    assert "nowhere" in harness.said[-1]
    assert "`lab`" in harness.said[-1]
    assert harness.rooms.get("physics").root == ""


@pytest.mark.asyncio
async def test_forgetting_a_room_keeps_its_conversations(harness) -> None:
    """The definition is cheap to rebuild. The thread is not."""
    await harness.say("/room new physics")
    harness.memory.add("user", "three weeks of analysis")
    thread = harness.store.session_id

    await harness.say("/room forget physics")

    assert harness.rooms.get("physics") is None
    assert harness.store.get_session(thread) is not None
    assert harness.store.get_messages(thread)[0]["content"] == (
        "three weeks of analysis"
    )


@pytest.mark.asyncio
async def test_the_room_list_names_the_open_one(harness) -> None:
    harness.rooms.create("Physics")
    harness.rooms.create("Writing")

    await harness.say("/room physics")
    await harness.say("/rooms")

    listing = harness.said[-1]
    assert "`physics` (open)" in listing
    assert "`writing`" in listing


@pytest.mark.asyncio
async def test_launch_resumes_the_room_you_were_in(tmp_path: Path) -> None:
    """Cold orbit every time was the hole. The strip is how you see it."""
    first = _Harness(tmp_path)
    await first.start()
    try:
        first.rooms.create("Physics", root="notes")
        await first.say("/room physics")
        first.memory.add("user", "three weeks of analysis")
        assert first.rooms.active_id == "physics"
    finally:
        await first.stop()

    second = _Harness(tmp_path)
    await second.start()
    try:
        assert second.rooms.active_id == ""
        assert second.rooms.last_active_id == "physics"
        assert await second.orchestrator.resume_last_room() is True
        await second.bus.drain()
        assert second.rooms.active_id == "physics"
        assert any(
            m.get("content") == "three weeks of analysis"
            for m in second.memory.as_ollama()
        )
        assert second.rooms_seen[-1]["room_id"] == "physics"
        assert second.said == []
    finally:
        await second.stop()


@pytest.mark.asyncio
async def test_launch_does_not_enter_a_room_you_only_created(tmp_path: Path) -> None:
    first = _Harness(tmp_path)
    await first.start()
    try:
        first.rooms.create("Physics")
    finally:
        await first.stop()

    second = _Harness(tmp_path)
    await second.start()
    try:
        assert await second.orchestrator.resume_last_room() is False
        assert second.rooms.active_id == ""
        assert second.rooms_seen == []
    finally:
        await second.stop()


@pytest.mark.asyncio
async def test_launch_stays_in_orbit_if_you_left(tmp_path: Path) -> None:
    first = _Harness(tmp_path)
    await first.start()
    try:
        first.rooms.create("Physics")
        await first.say("/room physics")
        await first.say("/leave")
    finally:
        await first.stop()

    second = _Harness(tmp_path)
    await second.start()
    try:
        assert await second.orchestrator.resume_last_room() is False
        assert second.rooms.active_id == ""
    finally:
        await second.stop()
