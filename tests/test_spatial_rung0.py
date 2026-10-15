"""Rung 0: pose language, grant, session ≠ camera tile. No C920."""

from __future__ import annotations

from types import SimpleNamespace

from arelis.spatial.gesture import read_pose
from arelis.spatial.grant import grant_for, world_stage_allowed
from arelis.spatial.video import POSE_MAX_WIDTH
from arelis.ui.hands_host import park_hands, resume_hands
from tests.hands_pose import make_hand


def test_read_pose_splits_pinch_from_fist() -> None:
    open_h = make_hand("Right", (0.50, 0.55), pose="open")
    pinch = make_hand("Right", (0.50, 0.55), pose="pinch")
    fist = make_hand("Right", (0.50, 0.55), pose="fist")
    assert read_pose(open_h) == "open"
    assert read_pose(pinch) == "pinch"
    # A curled close is the same grab. Fist was a second verb.
    assert read_pose(fist) == "pinch"
    assert pinch.pinch_metric() < 0.50
    assert pinch.hand_curl() <= 0.28
    assert fist.hand_curl() > 0.28


def test_filament_chip_grants_outside_reality() -> None:
    assert world_stage_allowed() is True
    assert grant_for("physics", True).allowed is True
    assert grant_for("lab", True, filament=True, chip=True).allowed is True
    assert grant_for("lab", True, filament=True, chip=False).allowed is False
    assert grant_for("lab", True).allowed is False
    assert grant_for("physics", False).allowed is False
    assert grant_for("lab", True, filament=False, chip=True).allowed is False


def test_rest_parks_and_return_with_chip_restarts() -> None:
    from arelis.ui.theme import apply_theme

    events: list[str] = []
    apply_theme("filament")
    spatial = SimpleNamespace(
        tracking=True,
        _parked=False,
        set_face=lambda **kw: events.append(f"face:{kw}"),
        park_session=lambda: events.append("park"),
        start_track=lambda meta=None: events.append("start") or True,
        stop_track=lambda: events.append("stop"),
        set_preview_wanted=lambda on: events.append(f"preview:{int(bool(on))}"),
    )

    def _park() -> None:
        spatial.tracking = False
        spatial._parked = True
        events.append("park")

    spatial.park_session = _park
    camera = SimpleNamespace(
        _running=True,
        track_btn=SimpleNamespace(isChecked=lambda: False),
        start=lambda **kw: events.append(f"cam:{kw.get('max_width')}"),
        stop=lambda: events.append("cam_stop"),
        current_device_name=lambda: "C920",
    )
    dock = SimpleNamespace(isVisible=lambda: False)
    chrome = SimpleNamespace(set_hands_visible=lambda on: None)
    window = SimpleNamespace(
        spatial=spatial,
        camera=camera,
        camera_dock=dock,
        _hands_chip=True,
        _filament_floats=SimpleNamespace(set_hands_on=lambda on: None, hands_btn=None),
        title_bar=chrome,
        config={},
    )
    try:
        park_hands(window)
        assert "park" in events
        assert spatial.tracking is False
        spatial.tracking = False
        camera._running = False
        resume_hands(window)
        assert "start" in events
        assert "cam:640" in events or any(
            item.startswith("cam:") and str(POSE_MAX_WIDTH) in item for item in events
        )
        assert any(item == "preview:0" for item in events)
    finally:
        apply_theme("sodium")


