"""Rung 0: pose language, grant, session ≠ camera tile. No C920."""

from __future__ import annotations

from types import SimpleNamespace

from arelis.spatial.gesture import GestureMachine, read_pose
from arelis.spatial.grant import grant_for, must_revoke, world_stage_allowed
from arelis.spatial.video import POSE_MAX_WIDTH, PREVIEW_CAPTURE_MAX_WIDTH
from arelis.ui.camera_host import on_camera_dock_visibility
from arelis.ui.hands_host import apply_hands_face, park_hands, resume_hands
from tests.hands_pose import frame_of, make_hand


def test_read_pose_splits_pinch_from_fist() -> None:
    open_h = make_hand("Right", (0.50, 0.55), pose="open")
    pinch = make_hand("Right", (0.50, 0.55), pose="pinch")
    fist = make_hand("Right", (0.50, 0.55), pose="fist")
    assert read_pose(open_h) == "open"
    assert read_pose(pinch) == "pinch"
    assert read_pose(fist) == "fist"
    assert pinch.pinch_metric() < 0.50
    assert pinch.hand_curl() <= 0.28
    assert fist.hand_curl() > 0.28


def test_two_tracks_stay_independent() -> None:
    machine = GestureMachine()
    t = 1.0
    for _ in range(3):
        machine.step(
            frame_of(
                make_hand("Right", (0.35, 0.55), pose="pinch"),
                make_hand("Left", (0.70, 0.50), pose="fist"),
                t=t,
            )
        )
        t += 0.03
    kinds = {track.who: track.state for track in machine.tracks}
    assert kinds.get("Right") == "pinch"
    assert kinds.get("Left") == "fist"
    assert not next(t for t in machine.tracks if t.who == "Right").dragging
    assert next(t for t in machine.tracks if t.who == "Left").dragging


def test_filament_chip_grants_outside_reality() -> None:
    assert world_stage_allowed() is True
    assert grant_for("physics", True).allowed is True
    assert grant_for("lab", True, filament=True, chip=True).allowed is True
    assert grant_for("lab", True, filament=True, chip=False).allowed is False
    assert grant_for("lab", True).allowed is False
    assert grant_for("physics", False).allowed is False
    assert grant_for("lab", True, filament=False, chip=True).allowed is False


def test_leave_reality_kills_sodium_track_not_filament() -> None:
    assert must_revoke("lab") is True
    assert must_revoke("physics") is False
    assert must_revoke("lab", filament=True, chip=True) is False
    assert must_revoke("lab", filament=True, chip=False) is True


def test_installer_never_gets_a_session(monkeypatch) -> None:
    from pathlib import Path

    import arelis.spatial.grant as grant
    import arelis.update as update

    monkeypatch.setattr(update, "install_root", lambda: Path("C:/installed"))
    assert grant.world_stage_allowed() is False
    assert grant.grant_for("physics", True).allowed is False
    assert grant.grant_for("lab", True, filament=True, chip=True).allowed is False


def test_non_source_never_gets_a_session(monkeypatch) -> None:
    import arelis.spatial.grant as grant
    import arelis.update as update

    monkeypatch.setattr(update, "install_root", lambda: None)
    monkeypatch.setattr(grant, "is_source_checkout", lambda: False)
    assert grant.world_stage_allowed() is False
    assert grant.grant_for("physics", True, filament=True, chip=True).allowed is False


def test_hiding_the_camera_tile_keeps_a_live_session(monkeypatch) -> None:
    stopped: list[str] = []
    wanted: list[bool] = []
    dock = SimpleNamespace()
    camera = SimpleNamespace(
        _running=True,
        stop=lambda: stopped.append("camera"),
        set_hands=lambda _h: None,
    )
    spatial = SimpleNamespace(
        tracking=True,
        set_preview_wanted=lambda on: wanted.append(bool(on)),
    )
    window = SimpleNamespace(camera_dock=dock, camera=camera, spatial=spatial)
    monkeypatch.setattr(
        "arelis.ui.camera_host.chrome_applying", lambda _dock: False
    )
    monkeypatch.setattr("arelis.ui.camera_host.refresh_camera_capture_hook", lambda _w: None)
    on_camera_dock_visibility(window, False)
    assert stopped == []
    assert wanted == [False]


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


def test_session_only_capture_stays_pose_width(monkeypatch) -> None:
    from arelis.ui.hands_host import _ensure_session
    from arelis.ui.theme import apply_theme

    widths: list[int] = []
    apply_theme("filament")
    spatial = SimpleNamespace(
        set_preview_wanted=lambda on: None,
        start_track=lambda meta=None: True,
        tracking=False,
    )
    camera = SimpleNamespace(
        _running=False,
        start=lambda max_width=None: widths.append(int(max_width)),
        current_device_name=lambda: "C920",
    )
    window = SimpleNamespace(
        spatial=spatial,
        camera=camera,
        camera_dock=SimpleNamespace(isVisible=lambda: False),
    )
    monkeypatch.setattr("arelis.ui.hands_host.world_stage_allowed", lambda: True)
    try:
        _ensure_session(window)
        assert widths == [POSE_MAX_WIDTH]
        assert POSE_MAX_WIDTH == 640
        assert PREVIEW_CAPTURE_MAX_WIDTH == 1280
        camera._running = False
        window.camera_dock = SimpleNamespace(isVisible=lambda: True)
        widths.clear()
        _ensure_session(window)
        assert widths == [PREVIEW_CAPTURE_MAX_WIDTH]
    finally:
        apply_theme("sodium")


def test_sodium_apply_does_not_start_from_a_chip(monkeypatch) -> None:
    from arelis.ui.theme import apply_theme

    started: list[str] = []
    apply_theme("sodium")
    spatial = SimpleNamespace(
        tracking=False,
        set_face=lambda **kw: None,
        start_track=lambda meta=None: started.append("start") or True,
        stop_track=lambda: started.append("stop"),
    )
    window = SimpleNamespace(
        spatial=spatial,
        camera=SimpleNamespace(track_btn=SimpleNamespace(isChecked=lambda: False)),
        _hands_chip=True,
        _filament_floats=None,
    )
    apply_hands_face(window)
    assert started == []
