"""Closed physics verbs. No camera, no turn, no 9B."""

from __future__ import annotations

from arelis.spatial.scene import LAST_BIND, MASS, Disc, WorldScene
from arelis.spatial.verbs import classify_physics_verb


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
    assert classify_physics_verb("undo") == "undo"
    assert classify_physics_verb("stop") is None
    assert classify_physics_verb("yes") is None
    assert classify_physics_verb("that's heavier than I thought") is None


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
