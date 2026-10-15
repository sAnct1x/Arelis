"""Closed physics verbs. No camera, no turn, no 9B."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from arelis.config import PROJECT_ROOT
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.rooms import RoomStore
from arelis.spatial.scene import Disc, WorldScene
from arelis.spatial.verbs import (
    classify_physics_verb,
)
from arelis.tools.base import ToolRegistry


def _plane(*bodies: Disc) -> WorldScene:
    scene = WorldScene()
    scene.bodies = list(bodies) if bodies else [Disc()]
    return scene


def test_classify_is_whole_utterance() -> None:
    assert classify_physics_verb("heavier") == "heavier"
    assert classify_physics_verb("make it heavier") == "heavier"
    assert classify_physics_verb("lighter") == "lighter"
    assert classify_physics_verb("freeze") == "freeze"
    assert classify_physics_verb("unfreeze") == "unfreeze"
    assert classify_physics_verb("pause") == "pause"
    assert classify_physics_verb("resume") == "resume"
    assert classify_physics_verb("step") == "step"
    assert classify_physics_verb("faster") == "faster"
    assert classify_physics_verb("slower") == "slower"
    assert classify_physics_verb("realtime") == "realtime"
    assert classify_physics_verb("1x") == "realtime"
    assert classify_physics_verb("hour") == "hour"
    assert classify_physics_verb("day") == "day"
    assert classify_physics_verb("year") == "year"
    assert classify_physics_verb("fly") == "fly"
    assert classify_physics_verb("craft") == "fly"
    assert classify_physics_verb("inspect") == "inspect"
    assert classify_physics_verb("pause the sim") == "pause"
    assert classify_physics_verb("play the sim") == "resume"
    assert classify_physics_verb("increase speed") == "faster"
    assert classify_physics_verb("decrease speed") == "slower"
    assert classify_physics_verb("speed up time") == "faster"
    assert classify_physics_verb("slow time down") == "slower"
    assert classify_physics_verb("one hour a second") == "hour"
    assert classify_physics_verb("one day a second") == "day"
    assert classify_physics_verb("stop") is None
    assert classify_physics_verb("yes") is None
    assert classify_physics_verb("that's heavier than I thought") is None
    assert classify_physics_verb("reset") is None
    assert classify_physics_verb("take me to Earth") is None


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

    def apply_sticky(self, wanted, reason: str):
        return wanted, reason

    async def stream(self, role, messages, **kwargs):
        if False:
            yield ("token", "")
        return


@pytest.mark.asyncio
async def test_spoken_pause_in_physics_is_a_verb_not_a_turn(tmp_path: Path) -> None:
    bus = EventBus()
    seen: list[Event] = []

    async def capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(None, capture)
    rooms = RoomStore(tmp_path / "rooms.yaml")
    rooms.set_active("physics")
    orch = Orchestrator(
        bus,
        _StubRouter(),  # type: ignore[arg-type]
        ToolRegistry(),
        {
            "agent": {},
            "workspace": {"roots": ["."]},
            "_persona_path": str(PROJECT_ROOT / "arelis" / "persona" / "arelis.md"),
            "_speak_replies": True,
            "_rooms": rooms,
        },
        SessionMemory(),
    )
    bus_task = asyncio.create_task(bus.run())
    try:
        assert orch.rooms.active_id == "physics"
        await bus.publish(Event(EventType.VOICE_TRANSCRIPT, {"text": "pause"}))
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
    assert any(e.type == EventType.PHYSICS_VERB and e.payload.get("verb") == "pause" for e in seen)
    assert not any(e.type == EventType.USER_MESSAGE for e in seen)


@pytest.mark.asyncio
async def test_spoken_take_me_to_earth_is_a_verb_not_a_turn(tmp_path: Path) -> None:
    bus = EventBus()
    seen: list[Event] = []

    async def capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(None, capture)
    rooms = RoomStore(tmp_path / "rooms.yaml")
    rooms.set_active("physics")
    _orch = Orchestrator(
        bus,
        _StubRouter(),  # type: ignore[arg-type]
        ToolRegistry(),
        {
            "agent": {},
            "workspace": {"roots": ["."]},
            "_persona_path": str(PROJECT_ROOT / "arelis" / "persona" / "arelis.md"),
            "_speak_replies": True,
            "_rooms": rooms,
        },
        SessionMemory(),
    )
    bus_task = asyncio.create_task(bus.run())
    try:
        await bus.publish(Event(EventType.VOICE_TRANSCRIPT, {"text": "take me to Earth"}))
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
    hits = [e for e in seen if e.type == EventType.PHYSICS_VERB]
    assert hits
    assert hits[0].payload.get("verb") == "travel"
    assert hits[0].payload.get("name") == "Earth"
    assert not any(e.type == EventType.USER_MESSAGE for e in seen)


