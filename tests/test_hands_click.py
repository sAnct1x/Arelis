"""Pinch tap vs grab. Frozen hit. Desk delivery. No camera."""

from __future__ import annotations

from PySide6.QtCore import QRect

from arelis.spatial.gesture import GestureMachine
from tests.hands_pose import frame_of, make_hand


def _still_pinch(machine: GestureMachine, wrist, *, t0: float, pose: str = "pinch"):
    """Enter pinch, then still-unpinch. Returns clicks."""
    t = t0
    clicks = []
    for _ in range(3):
        machine.step(frame_of(make_hand("Right", wrist, pose=pose), t=t))
        clicks.extend(machine.consume_clicks())
        t += 0.03
    for _ in range(10):
        machine.step(frame_of(make_hand("Right", wrist, pose="open"), t=t))
        clicks.extend(machine.consume_clicks())
        t += 0.03
    return clicks, t


def test_pinch_with_travel_is_grab_not_click() -> None:
    machine = GestureMachine()
    t = 2.0
    for _ in range(3):
        machine.step(frame_of(make_hand("Right", (0.40, 0.55), pose="pinch"), t=t))
        t += 0.03
    assert machine.tracks
    assert machine.tracks[0].state == "pinch"
    assert not machine.tracks[0].dragging
    for i in range(4):
        machine.step(
            frame_of(make_hand("Right", (0.40 + 0.03 * (i + 1), 0.55), pose="pinch"), t=t)
        )
        t += 0.03
    assert machine.tracks[0].dragging
    clicks = []
    for _ in range(5):
        machine.step(frame_of(make_hand("Right", (0.55, 0.55), pose="open"), t=t))
        clicks.extend(machine.consume_clicks())
        t += 0.03
    assert clicks == []


def test_two_pinches_resize_and_one_still_pinch_does_not() -> None:

    from arelis.ui.camera_host import scene_pose
    from arelis.ui.hands_desk import scaled_frame

    grab, pose = scene_pose(closed=True, dragging=False, company=1)
    assert grab is False and pose == "open"
    grab, pose = scene_pose(closed=True, dragging=False, company=2)
    assert grab is True and pose == "pinch"
    grab, pose = scene_pose(closed=True, dragging=True, company=1)
    assert grab is True and pose == "pinch"
    grown = scaled_frame(QRect(100, 80, 300, 200), 1.5)
    assert grown.width() == 324
    assert grown.height() == 216
    assert abs(grown.center().x() - 249) <= 1
    assert abs(grown.center().y() - 179) <= 1


def test_filament_words_are_desk_commands() -> None:
    from arelis.core.tile_complete import match_desk_intent, match_tile_intent

    assert match_tile_intent("open files") == ("open", "workspace")
    assert match_tile_intent("open days") == ("open", "calendar")
    assert match_tile_intent("close notify") == ("close", "notifications")
    assert match_tile_intent("open history") == ("open", "history")
    assert match_tile_intent("close this") == ("close", "")
    assert match_desk_intent("span 2") == ("span", "2")
    assert match_desk_intent("two screens") == ("span", "2")
    assert match_desk_intent("open rooms") == ("rooms", "")
    assert match_desk_intent("open the notes room") is None
    assert match_desk_intent("span 2 and check the weather") is None
    assert match_tile_intent("open settings") is None
    from arelis.core.desk_guide import desk_guide_text, match_desk_guide

    assert match_desk_guide("how do hands work")
    assert match_desk_guide("how do I use my hands")
    assert match_desk_guide("how does voice control work")
    assert match_desk_guide("what can I say")
    assert match_desk_guide("how do I drag a window")
    assert match_desk_guide("how do I control you")
    assert not match_desk_guide("open history")
    assert not match_desk_guide("how is the weather")
    guide = desk_guide_text()
    assert "pinch" in guide.casefold()
    assert "fist" not in guide.casefold()
    assert "span 2" in guide.casefold()


