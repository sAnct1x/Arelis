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
from arelis.spatial.scene import LAST_BIND, MASS, Disc, WorldScene
from arelis.spatial.verbs import (
    classify_physics_act,
    classify_physics_verb,
    match_overlay,
    match_travel,
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


def test_travel_and_overlay_phrases() -> None:
    names = ("Sun", "Earth", "Moon", "Saturn", "Ceres")
    assert match_travel("take me to Earth", names=names) == "Earth"
    assert match_travel("go to the Sun", names=names) == "Sun"
    assert match_travel("fly to Saturn", names=names) == "Saturn"
    assert match_travel("take me to the Moon", names=names) == "Moon"
    assert match_travel("take me there", names=names) == ""
    assert match_travel("take me to x.com", names=names) is None
    assert match_travel("take me to the login", names=names) is None
    assert match_travel("go to bed", names=names) is None
    assert classify_physics_act("inspect Earth", names=names).verb == "inspect_body"
    assert classify_physics_act("inspect Earth", names=names).name == "Earth"
    assert classify_physics_act("look at Earth", names=names).verb == "inspect_body"
    assert classify_physics_act("look at the camera", names=names) is None
    assert classify_physics_act("take me to Earth", names=names).verb == "travel"
    assert classify_physics_act("reset the view").verb == "reset_view"
    assert classify_physics_act("back up").verb == "reset_view"
    assert match_overlay("show the magnetosphere") == ("magnetic", True)
    assert match_overlay("turn gravity off") == ("gravity", False)
    assert match_overlay("hide the orbits") == ("osculating", False)
    assert match_overlay("show the wind") == ("wind", True)
    assert match_overlay("put the grid on") == ("grid", True)
    assert match_overlay("show trails") == ("trails", True)
    assert match_overlay("hide Lagrange") == ("lagrange", False)
    assert match_overlay("turn on graphs") == ("graphs", True)
    lab = classify_physics_act("open the solar lab")
    assert lab is not None
    assert lab.verb == "lab"
    assert lab.page == "solar"
    assert lab.on is True
    toy = classify_physics_act("open the toy area")
    assert toy is not None
    assert toy.page == "hands"
    assert classify_physics_act("close the solar lab").on is False
    assert classify_physics_act("open world").page == ""
    assert classify_physics_act("open Reality").verb == "lab"
    assert classify_physics_act("open Reality").page == ""
    assert classify_physics_act("open thinking") is None


def test_heavier_hits_the_held_disc() -> None:
    scene = _plane()
    scene.apply_pointer(0.50, 0.50, True, t=1.00, who="Right", kind="fist")
    got = scene.apply_verb("heavier", t=1.01)
    assert got is not None
    assert got["mass"] > MASS
    assert scene.disc.mass == got["mass"]
    assert scene.last_verb == "heavier"


def test_heavier_does_not_guess_when_two_are_held() -> None:
    scene = _plane(Disc(), Disc(x=0.74, y=0.36))
    first, second = scene.bodies
    scene.apply_pointer(first.x, first.y, True, t=1.0, who="Right", kind="fist")
    scene.apply_pointer(second.x, second.y, True, t=1.0, who="Left", kind="fist")
    assert scene.apply_verb("heavier", t=1.1) is None
    assert first.mass == MASS
    assert second.mass == MASS


def test_a_verb_hits_the_last_drop() -> None:
    scene = _plane()
    scene.apply_pointer(0.50, 0.50, True, t=1.00, who="Right", kind="fist")
    scene.apply_pointer(0.50, 0.50, False, t=1.10, who="Right", kind="open")
    got = scene.apply_verb("lighter", t=1.10 + LAST_BIND / 2)
    assert got is not None
    assert scene.disc.mass < MASS


def test_a_stale_drop_is_unbound() -> None:
    scene = _plane()
    scene.apply_pointer(0.50, 0.50, True, t=1.00, who="Right", kind="fist")
    scene.apply_pointer(0.50, 0.50, False, t=1.10, who="Right", kind="open")
    assert scene.apply_verb("heavier", t=1.10 + LAST_BIND + 0.05) is None
    assert scene.disc.mass == MASS


def test_freeze_parks_a_drop() -> None:
    scene = _plane()
    scene.apply_pointer(0.50, 0.40, True, t=1.00, who="Right", kind="fist")
    assert scene.apply_verb("freeze", t=1.01) is not None
    scene.apply_pointer(0.50, 0.40, False, t=1.10, who="Right", kind="open")
    y0 = scene.disc.y
    scene.step(0.20)
    assert scene.disc.y == y0
    assert scene.disc.frozen
    scene.apply_verb("unfreeze", t=1.20)
    scene.step(0.20)
    assert scene.disc.y > y0
    assert not scene.disc.frozen


def test_undo_restores_mass() -> None:
    scene = _plane()
    scene.apply_pointer(0.50, 0.50, True, t=1.00, who="Right", kind="fist")
    scene.apply_verb("heavier", t=1.01)
    heavy = scene.disc.mass
    got = scene.apply_verb("undo", t=1.02)
    assert got is not None
    assert scene.disc.mass == MASS
    assert scene.disc.mass < heavy
    row = scene.to_log()
    assert row["mass"] == round(MASS, 4)
    assert row["verb"] == "undo"


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
async def test_spoken_pause_outside_physics_is_ordinary_talk(tmp_path: Path) -> None:
    bus = EventBus()
    seen: list[Event] = []

    async def capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(None, capture)
    orch = Orchestrator(
        bus,
        _StubRouter(),  # type: ignore[arg-type]
        ToolRegistry(),
        {
            "agent": {},
            "workspace": {"roots": ["."]},
            "_persona_path": str(PROJECT_ROOT / "arelis" / "persona" / "arelis.md"),
            "_speak_replies": True,
            "_rooms": RoomStore(tmp_path / "rooms.yaml"),
        },
        SessionMemory(),
    )

    async def _no_turn(*_a, **_k):
        return None

    orch._run_turn = _no_turn  # type: ignore[method-assign]
    bus_task = asyncio.create_task(bus.run())
    try:
        await bus.publish(Event(EventType.VOICE_TRANSCRIPT, {"text": "pause"}))
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
    assert not any(e.type == EventType.PHYSICS_VERB for e in seen)
    messages = [e for e in seen if e.type == EventType.USER_MESSAGE]
    assert messages
    assert messages[0].payload.get("text") == "pause"


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
