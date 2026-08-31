"""The desk is an inbox of pages, not a folder listing."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from arelis.desk import (
    DeskStore,
    infer_kind,
    match_keep_last,
    match_keep_note,
    write_note,
)
from arelis.workspace import WorkspaceRoots


def test_keep_this_colon_is_a_note() -> None:
    assert match_keep_note("keep this: the spare key is under the planter") == (
        "the spare key is under the planter"
    )
    assert match_keep_note("/keep spare key under the planter") == (
        "spare key under the planter"
    )
    assert match_keep_note("jot this down — call Robin before Friday") == (
        "call Robin before Friday"
    )
    assert match_keep_note("remember that I climb on Tuesdays") is None
    assert match_keep_note("keep this conversation going") is None


def test_bare_keep_this_pins_the_last_file() -> None:
    assert match_keep_last("keep this")
    assert match_keep_last("pin that.")
    assert match_keep_last("put this on the desk")
    assert not match_keep_last("keep this: a real note")
    assert not match_keep_last("remember that I climb")


def test_desk_store_pins_and_drops(tmp_path: Path) -> None:
    a = tmp_path / "one.md"
    b = tmp_path / "two.md"
    a.write_text("a", encoding="utf-8")
    b.write_text("b", encoding="utf-8")
    store = DeskStore(path=tmp_path / "desk.json")
    store.record(str(a), label="one", source="keep", root_name="lab")
    store.record(str(b), label="two", source="document", root_name="lab")
    store.pin(str(a), pinned=True)
    listed = store.list_for(root_name="lab")
    assert [item.label for item in listed] == ["one", "two"]
    assert listed[0].pinned
    store.drop(str(a))
    leftover = store.list_for(root_name="lab")
    assert [item.label for item in leftover] == ["two"]
    assert a.is_file()


def test_desk_drops_missing_files(tmp_path: Path) -> None:
    gone = tmp_path / "gone.md"
    gone.write_text("x", encoding="utf-8")
    store = DeskStore(path=tmp_path / "desk.json")
    store.record(str(gone), label="gone", source="keep", root_name="lab")
    gone.unlink()
    assert store.list_for(root_name="lab") == []


def test_desk_scopes_to_the_active_project(tmp_path: Path) -> None:
    lab = tmp_path / "lab.md"
    other = tmp_path / "other.md"
    orbit = tmp_path / "drop.pdf"
    lab.write_text("l", encoding="utf-8")
    other.write_text("o", encoding="utf-8")
    orbit.write_bytes(b"%PDF")
    store = DeskStore(path=tmp_path / "desk.json")
    store.record(str(lab), label="lab", source="keep", root_name="lab")
    store.record(str(other), label="other", source="keep", root_name="notes")
    store.record(str(orbit), label="drop", source="document", root_name="")
    in_lab = store.list_for(root_name="lab", include_orbit=True)
    assert {item.label for item in in_lab} == {"lab", "drop"}
    in_room = store.list_for(root_name="lab", room_id="physics", include_orbit=False)
    assert [item.label for item in in_room] == ["lab"]


def test_write_note_lands_in_notes(tmp_path: Path) -> None:
    roots = WorkspaceRoots.from_paths([str(tmp_path)], active=tmp_path.name)
    store = DeskStore(path=tmp_path / "desk.json")
    item = write_note(
        roots, "the spare key is under the planter", store=store
    )
    assert item.kind == "note"
    path = Path(item.abs_path)
    assert path.parent.name == "notes"
    assert "spare key" in path.read_text(encoding="utf-8").casefold()
    listed = store.list_for(root_name=tmp_path.name)
    assert listed[0].abs_path == item.abs_path


def test_opening_a_file_does_not_invent_a_desk_row(tmp_path: Path) -> None:
    note = tmp_path / "peek.md"
    note.write_text("hi", encoding="utf-8")
    store = DeskStore(path=tmp_path / "desk.json")
    assert store.record(str(note), source="open") is None
    assert store.list_for() == []


def test_scrape_cache_never_lands_on_the_desk(tmp_path: Path) -> None:
    cache = tmp_path / "tool_cache" / "20260821T022627Z_scrape_x.txt"
    cache.parent.mkdir()
    cache.write_text("old scrape", encoding="utf-8")
    store = DeskStore(path=tmp_path / "desk.json")
    assert store.record(str(cache), source="keep") is None
    assert store.list_for() == []


def test_infer_kind_from_path() -> None:
    assert infer_kind("notes/foo.md", source="keep") == "note"
    assert infer_kind("outputs/plots/plot-line.png") == "plot"
    assert infer_kind("shot.png", source="image") == "image"
    assert infer_kind("brief.pdf", source="document") == "document"


@pytest.mark.asyncio
async def test_workspace_keep_writes_a_note(tmp_path: Path) -> None:
    from arelis.tools.code_workspace import CodeWorkspaceTool

    tool = CodeWorkspaceTool([str(tmp_path)])
    result = await tool.run(action="keep", text="call Robin before Friday")
    assert result.ok
    assert "On the desk" in result.output
    notes = list((tmp_path / "notes").glob("*.md"))
    assert len(notes) == 1
    assert "Robin" in notes[0].read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_keep_slash_writes_without_a_confirm(tmp_path: Path) -> None:
    from arelis.config import PROJECT_ROOT
    from arelis.core.bus import EventBus
    from arelis.core.events import Event, EventType
    from arelis.core.memory import SessionMemory
    from arelis.core.orchestrator import Orchestrator
    from arelis.tools.base import ToolRegistry

    class _Router:
        default_role = "fast"
        active_model = None
        models = {"fast": "mock"}

        def model_for(self, role=None):
            return "mock"

        async def ensure_role(self, role, *, force: bool = False):
            return "mock"

        def mark_sticky(self, role) -> None:
            return None

        async def stream(self, role, messages, **kwargs):
            if False:
                yield ("token", "")
            return

        async def close(self):
            return None

    desk = DeskStore(path=tmp_path / "desk.json")
    workspace = WorkspaceRoots.from_paths([str(tmp_path)], active=tmp_path.name)
    bus = EventBus()
    said: list[str] = []
    files: list[str] = []

    async def _done(event: Event) -> None:
        said.append(str(event.payload.get("text") or ""))

    async def _file(event: Event) -> None:
        files.append(str(event.payload.get("abs_path") or ""))

    bus.subscribe(EventType.ASSISTANT_DONE, _done)
    bus.subscribe(EventType.FILE_READY, _file)
    Orchestrator(
        bus,
        _Router(),  # type: ignore[arg-type]
        ToolRegistry(),
        {
            "agent": {},
            "_persona_path": str(PROJECT_ROOT / "arelis" / "persona" / "arelis.md"),
            "_workspace": workspace,
            "_desk": desk,
        },
        SessionMemory(),
        workspace,
    )
    task = asyncio.create_task(bus.run())
    try:
        await bus.publish(
            Event(EventType.USER_MESSAGE, {"text": "/keep spare key under the planter"})
        )
        await bus.drain()
    finally:
        bus.stop()
        task.cancel()
    assert said
    assert "On the desk" in said[-1]
    assert files
    assert Path(files[-1]).is_file()
