"""What a room actually changes about a turn taken inside it.

Two things, and they pull in opposite directions. The purpose has to reach the
model every turn, or the room is just a folder bookmark. The tool surface has to
stay whole unless somebody deliberately narrowed it, or asking an ordinary
question in the physics room gets an apology instead of an answer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.memory import SessionMemory
from arelis.rooms import RoomStore
from arelis.tools.analyze import AnalyzeTool
from arelis.tools.base import ToolRegistry
from arelis.tools.calculator import CalculatorTool
from arelis.tools.code_workspace import CodeWorkspaceTool


class _Recorder:
    """Answers once, and keeps every request it was handed."""

    def __init__(self) -> None:
        self.default_role = "fast"
        self.active_model = None
        self.active_role = None
        self.models = {"fast": "mock", "research": "mock", "code": "mock"}
        self.seen: list[dict[str, Any]] = []

    def model_for(self, role=None):
        return "mock"

    async def ensure_role(self, role, *, force: bool = False):
        del force
        self.active_model = "mock"
        return "mock"

    def mark_sticky(self, role) -> None:
        return None

    def apply_sticky(self, wanted, reason: str):
        return wanted, reason

    async def stream(self, role, messages, **kwargs):
        self.seen.append({"messages": messages, "tools": kwargs.get("tools") or []})
        yield ("token", "Done.")


async def _deny(*_args: Any, **_kwargs: Any) -> str:
    return "skip"


def _loop(rooms: RoomStore | None, recorder: _Recorder) -> AgentLoop:
    tools = ToolRegistry()
    tools.register(CodeWorkspaceTool(["."]))
    tools.register(CalculatorTool())
    config: dict[str, Any] = {
        # chat_fast_path off so the schemas are always built and can be counted.
        "agent": {"max_rounds": 2, "chat_fast_path": False},
        "_persona_path": "does-not-exist.md",
    }
    if rooms is not None:
        config["_rooms"] = rooms
    return AgentLoop(
        EventBus(),
        recorder,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "persona",
        config,
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )


def _system_text(recorder: _Recorder) -> str:
    return "\n".join(
        str(m.get("content") or "")
        for m in recorder.seen[0]["messages"]
        if m.get("role") == "system"
    )


@pytest.mark.asyncio
async def test_the_rooms_purpose_is_in_front_of_her_every_turn(
    tmp_path: Path,
) -> None:
    rooms = RoomStore(tmp_path / "rooms.yaml")
    rooms.update(
        "physics",
        purpose="Analysing the survey data. Show the numbers you used.",
        root="notes",
    )
    rooms.set_active("physics")
    recorder = _Recorder()

    await _loop(rooms, recorder).run("what does the fit say?", "fast")

    text = _system_text(recorder)
    assert "Room — Physics" in text
    assert "Show the numbers you used." in text


@pytest.mark.asyncio
async def test_a_turn_outside_any_room_says_nothing_about_rooms(
    tmp_path: Path,
) -> None:
    rooms = RoomStore(tmp_path / "rooms.yaml")
    recorder = _Recorder()

    await _loop(rooms, recorder).run("what does the fit say?", "fast")

    assert "Room —" not in _system_text(recorder)


@pytest.mark.asyncio
async def test_a_room_leans_without_taking_tools_away(tmp_path: Path) -> None:
    """The default has to leave the surface whole.

    An allowlist per room is the obvious design and the wrong default: ask the
    time in the physics room and a caged agent has to refuse, which teaches you
    to stop asking it things.
    """
    rooms = RoomStore(tmp_path / "rooms.yaml")
    rooms.set_active("physics")
    recorder = _Recorder()

    await _loop(rooms, recorder).run("add 2 and 2", "fast")

    offered = {
        t["function"]["name"] for t in recorder.seen[0]["tools"] if "function" in t
    }
    assert {"workspace", "calculator"} <= offered


@pytest.mark.asyncio
async def test_a_room_that_asked_for_a_cage_gets_one(tmp_path: Path) -> None:
    path = tmp_path / "rooms.yaml"
    path.write_text(
        "rooms:\n  physics:\n    name: Physics\n    tools:\n      - calculator\n",
        encoding="utf-8",
    )
    rooms = RoomStore(path)
    rooms.set_active("physics")
    recorder = _Recorder()

    await _loop(rooms, recorder).run("read the notes file", "fast")

    offered = {
        t["function"]["name"] for t in recorder.seen[0]["tools"] if "function" in t
    }
    assert offered == {"calculator"}


@pytest.mark.asyncio
async def test_a_cage_naming_only_unknown_tools_is_ignored(tmp_path: Path) -> None:
    """A hand-edited typo must not silently leave her with no tools at all.

    An empty intersection is far more likely to be a misspelled name than a
    request for a room where nothing works.
    """
    path = tmp_path / "rooms.yaml"
    path.write_text(
        "rooms:\n  physics:\n    name: Physics\n    tools:\n      - calculater\n",
        encoding="utf-8",
    )
    rooms = RoomStore(path)
    rooms.set_active("physics")
    recorder = _Recorder()

    await _loop(rooms, recorder).run("add 2 and 2", "fast")

    offered = {
        t["function"]["name"] for t in recorder.seen[0]["tools"] if "function" in t
    }
    assert "calculator" in offered


def test_make_me_a_room_for_topic_expects_rooms() -> None:
    """13.9: natural-language room create, not furniture."""
    from arelis.core.preflight import detect_intents, looks_like_room_create
    from arelis.core.skills import select_skill_ids

    ask = "Make me a room for astrophysics."
    assert looks_like_room_create(ask)
    hints = detect_intents(ask)
    tools = {t for h in hints for t in h.expected_tools}
    assert "rooms" in tools
    ids = select_skill_ids(
        ask,
        available_tools={"rooms", "image", "web_search", "workspace"},
    )
    assert "rooms" in ids
    assert not looks_like_room_create("make room in the suitcase")
    assert not looks_like_room_create("the living room needs paint")


@pytest.mark.asyncio
async def test_analysis_room_does_not_plan_analyze_on_a_physics_question(
    tmp_path: Path,
) -> None:
    """kind=analysis leans analyze. It must not cage a conceptual ask."""
    rooms = RoomStore(tmp_path / "rooms.yaml")
    rooms.update(
        "physics",
        purpose="Working through the survey and the theory behind it.",
        kind="analysis",
    )
    rooms.set_active("physics")
    recorder = _Recorder()
    loop = _loop(rooms, recorder)
    loop.tools.register(AnalyzeTool([str(tmp_path)]))

    await loop.run("how do toroids relate to physics?", "fast")

    text = _system_text(recorder)
    assert "Room — Physics" in text
    assert "Call analyze" not in text
    assert "named table/CSV" not in text

    recorder.seen.clear()
    await loop.run("summarize the columns in data/sales.csv", "fast")
    follow = _system_text(recorder)
    assert "Call analyze" in follow
