"""Physics-room rung 0: grant, 1€, pose FSM, takes. No camera required.

`_hand()` is a fist: other fingertips sit on the palm. That fixture is
why a real fist always matched the old 'pinch' tests.
"""

from __future__ import annotations

import json

from arelis.spatial.gesture import LOCK_MISS, GestureMachine, GestureParams, read_pose
from arelis.spatial.grant import grant_for, must_revoke
from arelis.spatial.one_euro import OneEuro
from arelis.spatial.scene import WorldScene, image_to_world
from arelis.spatial.takes import KEEP_MARKER, TakeWriter, prune_stills, prune_takes
from arelis.spatial.types import Hand, HandsFrame, Landmark
from arelis.spatial.video import POSE_MAX_WIDTH, fit_size, pick_live_format


def _hand(
    pinch_span: float,
    palm: float = 0.2,
    *,
    label: str = "Right",
    origin: tuple[float, float] = (0.0, 0.0),
) -> Hand:
    # Fist: tips near the palm. Aperture = thumb-index / index_mcp-pinky_mcp.
    ox, oy = origin
    pts = [(ox, oy, 0.0)] * 21
    pts[4] = (ox, oy, 0.0)  # thumb tip
    pts[8] = (ox + pinch_span, oy, 0.0)  # index tip
    pts[5] = (ox, oy, 0.0)  # index mcp
    pts[17] = (ox + palm, oy, 0.0)  # pinky mcp
    lms = tuple(
        Landmark(x=p[0], y=p[1], z=p[2], name=str(i)) for i, p in enumerate(pts)
    )
    return Hand(label=label, landmarks=lms, score=1.0)


def _pinch_hand(
    pinch_span: float = 0.04,
    palm: float = 0.2,
    *,
    label: str = "Right",
    origin: tuple[float, float] = (0.0, 0.0),
    extend: float = 0.24,
    into_z: bool = False,
) -> Hand:
    """Precision pinch: thumb-index close, other fingers out."""
    ox, oy = origin
    pts = [(ox, oy, 0.0)] * 21
    pts[5] = (ox, oy, 0.0)
    pts[9] = (ox + palm * 0.33, oy, 0.0)
    pts[13] = (ox + palm * 0.66, oy, 0.0)
    pts[17] = (ox + palm, oy, 0.0)
    pts[4] = (ox + 0.01, oy - 0.03, 0.0)
    pts[8] = (ox + 0.01 + pinch_span, oy - 0.03, 0.0)
    for mcp, pip, dip, tip in (
        (9, 10, 11, 12),
        (13, 14, 15, 16),
        (17, 18, 19, 20),
    ):
        mx, my, _mz = pts[mcp]
        if into_z:
            pts[pip] = (mx, my, extend * 0.33)
            pts[dip] = (mx, my, extend * 0.66)
            pts[tip] = (mx, my, extend)
        else:
            pts[pip] = (mx, my - extend * 0.33, 0.0)
            pts[dip] = (mx, my - extend * 0.66, 0.0)
            pts[tip] = (mx, my - extend, 0.0)
    lms = tuple(
        Landmark(x=p[0], y=p[1], z=p[2], name=str(i)) for i, p in enumerate(pts)
    )
    return Hand(label=label, landmarks=lms, score=1.0)


def _frame(hands: tuple[Hand, ...], t: float = 0.0) -> HandsFrame:
    return HandsFrame(
        t_capture=t,
        t_infer=0.0,
        width=1920,
        height=1080,
        infer_width=960,
        infer_height=540,
        hands=hands,
        backend="test",
    )


def test_grant_only_in_physics_while_tracking() -> None:
    assert grant_for("physics", True).allowed
    assert not grant_for("physics", False).allowed
    assert not grant_for("arelis", True).allowed
    assert not grant_for("", True).allowed
    assert must_revoke("arelis")
    assert must_revoke("")
    assert not must_revoke("physics")


def test_one_euro_holds_a_still_value() -> None:
    filt = OneEuro(min_cutoff=1.0, beta=0.0, d_cutoff=1.0)
    t = 0.0
    last = 0.0
    for _i in range(20):
        t += 1 / 30
        last = filt(1.0, t)
    assert abs(last - 1.0) < 1e-6


def test_video_clock_follows_capture_not_a_fake_33ms() -> None:
    """Dropped frames used to be reported as 33 ms, so the tracker hunted."""
    from arelis.spatial.backend import video_clock_ms

    first = video_clock_ms(10.000, 0)
    assert first == 10000
    # A skipped frame 80 ms later must not be told it was 33.
    later = video_clock_ms(10.080, first)
    assert later == 10080
    # MediaPipe rejects a non-increasing clock.
    assert video_clock_ms(10.080, later) == later + 1


def test_filter_bank_steadies_the_pointer_not_the_tips() -> None:
    """World follows one filtered midpoint. Tips stay raw so pinch does not lag."""
    from arelis.spatial.types import FilterBank

    bank = FilterBank()
    t = 1.0
    last = None
    raw_xs: list[float] = []
    ptr_xs: list[float] = []
    for i in range(16):
        t += 1 / 30
        # Still pinch, tips buzzing ±0.01 — the unfiltered centroid crawls.
        jitter = 0.01 if i % 2 == 0 else -0.01
        hand = _hand(0.04 + jitter, origin=(0.50 + jitter, 0.40))
        raw_xs.append(hand.pinch_centroid()[0])
        out = bank.apply(_frame((hand,), t=t))
        last = out.hands[0]
        assert last.pointer is not None
        ptr_xs.append(last.pointer[0])
    assert last is not None
    assert last.landmarks[4].x == hand.landmarks[4].x
    raw_travel = max(raw_xs) - min(raw_xs)
    ptr_travel = max(ptr_xs[4:]) - min(ptr_xs[4:])
    assert ptr_travel < raw_travel


def test_one_euro_is_deterministic() -> None:
    a = OneEuro()
    b = OneEuro()
    t = 0.0
    seq = [0.0, 0.1, 0.0, 0.2, 0.0]
    out_a = []
    out_b = []
    for x in seq:
        t += 0.03
        out_a.append(a(x, t))
        out_b.append(b(x, t))
    assert out_a == out_b


def test_pinch_needs_hysteresis() -> None:
    machine = GestureMachine(GestureParams(aperture_on=0.35, aperture_off=0.5, frames_on=2, frames_off=2, fist_off=2))
    # Open hand: metric = 0.2/0.2 = 1.0
    open_f = _frame((_hand(0.2),))
    assert machine.step(open_f) == "idle"
    assert machine.step(open_f) == "idle"
    # Tight pinch: 0.04/0.2 = 0.2
    tight = _frame((_hand(0.04),))
    assert machine.step(tight) == "idle"
    assert machine.step(tight) == "fist"
    # Near-pinch in the dead band 0.4 stays pinched
    mid = _frame((_hand(0.08),))  # 0.4
    assert machine.step(mid) == "fist"
    # Open again
    assert machine.step(open_f) == "fist"
    assert machine.step(open_f) == "idle"


def test_lost_hand_is_lost_not_idle_from_pinch() -> None:
    machine = GestureMachine(GestureParams(frames_on=1, frames_off=1, fist_off=1))
    machine.step(_frame((_hand(0.04),)))
    assert machine.state == "fist"
    assert machine.step(None) == "lost"
    assert machine.step(_frame(())) == "lost"


def test_leave_revokes_without_a_worker(qt_app) -> None:
    from arelis.ui.spatial_hands import SpatialHands

    hands = SpatialHands()
    hands.set_room("physics")
    assert not hands.allowed
    hands.set_room("")
    hands.stop_track()
    assert not hands.tracking


def test_take_writer_jsonl(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("arelis.spatial.takes.outputs_dir", lambda: tmp_path)
    take = TakeWriter.start({"room": "physics", "device": "test"})
    take.write(_frame((_hand(0.04),), t=1.5), extra={"gesture": "fist"})
    folder = take.close()
    assert (folder / "meta.json").is_file()
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    assert meta["room"] == "physics"
    lines = (folder / "frames.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["gesture"] == "fist"
    assert row["hands"][0]["pinch"] < 0.3
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    assert summary["frames"] == 1
    assert summary["capped"] is False


def test_take_caps_at_sixty_seconds(tmp_path) -> None:
    take = TakeWriter.start({"room": "physics"}, root=tmp_path)
    assert take.write(_frame((), t=0.0))
    assert take.write(_frame((), t=59.9))
    assert take.write(_frame((), t=60.0)) is False
    assert take.capped
    take.close()
    lines = (take.path / "frames.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_prune_takes_keeps_newest_and_pinned(tmp_path) -> None:
    for i in range(14):
        folder = tmp_path / f"20260822T{i:06d}Z"
        folder.mkdir()
        (folder / "meta.json").write_text("{}", encoding="utf-8")
    pinned = tmp_path / "20260822T000000Z"
    (pinned / KEEP_MARKER).write_text("", encoding="utf-8")
    prune_takes(tmp_path, keep_last=12)
    left = {p.name for p in tmp_path.iterdir() if p.is_dir()}
    assert "20260822T000000Z" in left
    assert len(left) == 13


def test_prune_stills_keeps_newest(tmp_path) -> None:
    for i in range(20):
        (tmp_path / f"camera_{i:02d}.jpg").write_bytes(b"x")
    (tmp_path / "other.png").write_bytes(b"y")
    prune_stills(tmp_path, keep=16)
    jpgs = list(tmp_path.glob("camera_*.jpg"))
    assert len(jpgs) == 16
    assert (tmp_path / "other.png").is_file()


def test_live_format_prefers_mjpeg_30_over_yuy2_5() -> None:
    picked = pick_live_format(
        [
            (1920, 1080, 5.0, "Format_YUYV"),
            (1920, 1080, 30.0, "Format_Jpeg"),
            (1280, 720, 30.0, "Format_YUYV"),
        ]
    )
    assert picked is not None
    assert picked[0] == 1920
    assert picked[2] == 30.0
    assert "Jpeg" in picked[3]


def test_image_to_world_mirrors_x() -> None:
    x, y = image_to_world(0.25, 0.4, reach=1.0)
    assert abs(x - 0.75) < 1e-9
    assert abs(y - 0.4) < 1e-9


def test_reach_amplifies_around_center() -> None:
    x, y = image_to_world(0.25, 0.4, reach=2.0)
    assert x > 0.75
    assert x < 1.0
    assert y < 0.4
    cx, cy = image_to_world(0.5, 0.5, reach=2.0)
    assert abs(cx - 0.5) < 1e-9
    assert abs(cy - 0.5) < 1e-9


def test_reach_center_slope_matches_gain() -> None:
    gain = 1.45
    eps = 1e-4
    left, _ = image_to_world(0.5 + eps, 0.5, reach=gain)
    right, _ = image_to_world(0.5 - eps, 0.5, reach=gain)
    assert abs((right - left) / (2 * eps) - gain) < 0.02


def test_reach_still_moves_near_the_sensor_edge() -> None:
    """Linear gain used to clamp the outer ~15% to the wall."""
    a, _ = image_to_world(0.10, 0.50, reach=1.45)
    b, _ = image_to_world(0.04, 0.50, reach=1.45)
    assert a < 1.0
    assert b > a
    assert b <= 1.0


def _clip_tips(hand: Hand, y: float = 1.02) -> Hand:
    lms = list(hand.landmarks)
    for i in (4, 8, 12, 16, 20):
        old = lms[i]
        lms[i] = Landmark(x=old.x, y=y, z=old.z, name=old.name)
    return Hand(label=hand.label, landmarks=tuple(lms), score=hand.score)


def test_a_clipped_fist_does_not_open() -> None:
    """Tips past the sensor invent aperture. That is not a throw."""
    machine = GestureMachine()
    tight = _frame((_hand(0.04, origin=(0.40, 0.40)),))
    assert machine.step(tight) == "idle"
    assert machine.step(tight) == "fist"
    clipped = _frame((_clip_tips(_hand(0.20, origin=(0.40, 0.40))),))
    for _ in range(12):
        assert machine.step(clipped) == "fist"


def test_a_clipped_idle_does_not_enter() -> None:
    machine = GestureMachine()
    clipped = _frame((_clip_tips(_hand(0.04, origin=(0.40, 0.40))),))
    for _ in range(5):
        assert machine.step(clipped) == "idle"


def test_a_throw_opens_without_waiting_out_a_twist() -> None:
    """Wrist traveled — that is a sling. Don't sit on fist_off."""
    machine = GestureMachine()
    tight = _frame((_hand(0.04, origin=(0.0, 0.0)),))
    assert machine.step(tight) == "idle"
    assert machine.step(tight) == "fist"
    assert machine.step(_frame((_hand(0.20, origin=(0.12, 0.0)),))) == "fist"
    assert machine.step(_frame((_hand(0.20, origin=(0.24, 0.0)),))) == "fist"
    assert machine.step(_frame((_hand(0.20, origin=(0.36, 0.0)),))) == "idle"


def test_a_still_twist_does_not_drop_the_fist() -> None:
    """Same wrist, aperture spike: the C920 lie during a horizontal turn."""
    machine = GestureMachine()
    tight = _frame((_hand(0.04),))
    machine.step(tight)
    machine.step(tight)
    open_f = _frame((_hand(0.20),))
    for _ in range(7):
        assert machine.step(open_f) == "fist"
    assert machine.step(open_f) == "idle"


def test_a_still_twist_does_not_drop_the_pinch() -> None:
    """Same wrist, aperture spike: pinch used to die in frames_off=3."""
    machine = GestureMachine()
    tight = _frame((_pinch_hand(0.04),))
    machine.step(tight)
    machine.step(tight)
    assert machine.state == "pinch"
    open_f = _frame((_pinch_hand(0.20),))
    for _ in range(7):
        assert machine.step(open_f) == "pinch"
    assert machine.step(open_f) == "idle"


def test_a_moving_open_drops_the_pinch() -> None:
    machine = GestureMachine()
    tight = _frame((_pinch_hand(0.04, origin=(0.0, 0.0)),))
    assert machine.step(tight) == "idle"
    assert machine.step(tight) == "pinch"
    assert machine.step(_frame((_pinch_hand(0.20, origin=(0.12, 0.0)),))) == "pinch"
    assert machine.step(_frame((_pinch_hand(0.20, origin=(0.24, 0.0)),))) == "pinch"
    assert machine.step(_frame((_pinch_hand(0.20, origin=(0.36, 0.0)),))) == "idle"


def test_an_idle_track_does_not_steal_the_other_fist() -> None:
    """After a right drop, the left fist on the disc must be its own track."""
    machine = GestureMachine()
    right = _hand(0.04, label="Right", origin=(0.50, 0.50))
    left_open = _hand(0.20, label="Left", origin=(0.70, 0.50))
    machine.step(_frame((right, left_open)))
    machine.step(_frame((right, left_open)))
    assert any(track.who == "Right" and track.state == "fist" for track in machine.tracks)
    right_open = _hand(0.20, label="Right", origin=(0.50, 0.50))
    for _ in range(8):
        machine.step(_frame((right_open, left_open)))
    assert not any(
        track.who == "Right" and track.state == "fist" for track in machine.tracks
    )
    left_fist = _hand(0.04, label="Left", origin=(0.62, 0.50))
    right_still = _hand(0.20, label="Right", origin=(0.50, 0.50))
    machine.step(_frame((right_still, left_fist)))
    machine.step(_frame((right_still, left_fist)))
    assert any(track.who == "Left" and track.state == "fist" for track in machine.tracks)
    assert not any(
        track.who == "Right" and track.state == "fist" for track in machine.tracks
    )


def test_one_open_flicker_does_not_restart_unpinch() -> None:
    machine = GestureMachine()
    tight = _frame((_hand(0.04),))
    machine.step(tight)
    machine.step(tight)
    open_f = _frame((_hand(0.14),))
    mid = _frame((_hand(0.10),))  # 0.50, under pinch_off
    assert machine.step(open_f) == "fist"
    assert machine.step(mid) == "fist"
    for _ in range(4):
        assert machine.step(open_f) == "fist"


def test_lost_does_not_resume_a_half_open_pinch() -> None:
    machine = GestureMachine()
    tight = _frame((_hand(0.04),))
    machine.step(tight)
    machine.step(tight)
    assert machine.state == "fist"
    assert machine.step(None) == "lost"
    half = _frame((_hand(0.10),))  # 0.50, used to be <= pinch_off 0.75
    assert machine.step(half) == "idle"


def test_a_one_frame_gap_keeps_the_fist() -> None:
    """Side-on fist: MediaPipe often returns no hands for a beat."""
    machine = GestureMachine()
    tight = _frame((_hand(0.04),))
    machine.step(tight)
    machine.step(tight)
    assert machine.state == "fist"
    assert machine.step(_frame(())) == "fist"
    assert machine.tracks[0].coasting
    assert machine.step(tight) == "fist"
    assert not machine.tracks[0].coasting


def test_a_long_gap_does_release_the_fist() -> None:
    machine = GestureMachine()
    tight = _frame((_hand(0.04),))
    machine.step(tight)
    machine.step(tight)
    empty = _frame(())
    last = "fist"
    for _ in range(LOCK_MISS):
        last = machine.step(empty)
    assert last in ("lost", "idle")
    assert machine.state != "fist"


def test_loose_pinch_enters_on_defaults() -> None:
    machine = GestureMachine()
    # 0.08/0.2 = 0.4, used to miss 0.35; now under 0.45
    loose = _frame((_hand(0.08),))
    assert machine.step(loose) == "idle"
    assert machine.step(loose) == "fist"


def test_pinch_survives_a_turned_hand() -> None:
    """Palm stacked in the image, still a pinch in 3D — 2D used to drop it."""
    machine = GestureMachine()
    tight = _frame((_hand(0.04),))
    assert machine.step(tight) == "idle"
    assert machine.step(tight) == "fist"
    pts = [(0.0, 0.0, 0.0)] * 21
    pts[4] = (0.0, 0.0, 0.0)
    pts[8] = (0.04, 0.0, 0.0)
    pts[5] = (0.0, 0.0, 0.0)
    pts[17] = (0.01, 0.0, 0.20)
    turned = Hand(
        label="Right",
        landmarks=tuple(
            Landmark(x=p[0], y=p[1], z=p[2], name=str(i)) for i, p in enumerate(pts)
        ),
        score=1.0,
    )
    assert turned.pinch_metric() < 0.3
    assert machine.step(_frame((turned,))) == "fist"


def test_a_turned_pinch_does_not_orbit_the_cursor() -> None:
    """2D tips circle the wrist when you rotate. The disc must not follow them."""
    from arelis.spatial.types import grab_drive

    facing = _hand(0.04, origin=(0.50, 0.40))
    xy, off = grab_drive(facing, closed=True, offset=None)
    assert off is not None
    assert abs(xy[0] - facing.pinch_centroid()[0]) < 1e-9
    turned = _hand(0.01, origin=(0.50, 0.40))
    stuck, _ = grab_drive(turned, closed=True, offset=off)
    assert abs(stuck[0] - xy[0]) < 1e-9
    assert abs(stuck[1] - xy[1]) < 1e-9
    moved = _hand(0.01, origin=(0.60, 0.40))
    followed, _ = grab_drive(moved, closed=True, offset=off)
    assert abs(followed[0] - (xy[0] + 0.10)) < 1e-9
    open_hand = _hand(0.20, origin=(0.60, 0.40))
    live, cleared = grab_drive(open_hand, closed=False, offset=off)
    assert cleared is None
    assert abs(live[0] - open_hand.pinch_centroid()[0]) < 1e-9


def test_follow_hand_keeps_the_wrist_when_labels_flip() -> None:
    """Close hands + swapped Left/Right used to trade bodies."""
    from arelis.spatial.gesture import follow_hand

    physical_right = _hand(0.04, label="Left", origin=(0.52, 0.50))
    physical_left = _hand(0.04, label="Right", origin=(0.48, 0.50))
    found = follow_hand(
        (physical_left, physical_right),
        label="Right",
        wrist=(0.52, 0.50),
    )
    assert found is physical_right


def test_a_pinch_stays_on_the_hand_that_started_it() -> None:
    """The other hand may close or come first in the list. It does not steal."""
    machine = GestureMachine(GestureParams(frames_on=2, frames_off=2))
    right = _hand(0.04, label="Right", origin=(0.72, 0.50))
    left_open = _hand(0.20, label="Left", origin=(0.28, 0.50))
    assert machine.step(_frame((left_open, right))) == "idle"
    assert machine.step(_frame((left_open, right))) == "fist"
    assert machine.hand is not None
    assert machine.hand.label == "Right"
    left_tight = _hand(0.02, label="Left", origin=(0.28, 0.50))
    swapped = _frame((left_tight, right))
    assert machine.step(swapped) == "fist"
    right_tracks = [
        track
        for track in machine.tracks
        if track.who == "Right" and track.state == "fist"
    ]
    assert right_tracks


def test_the_other_hand_does_not_inherit_a_lost_pinch() -> None:
    machine = GestureMachine(GestureParams(frames_on=2, frames_off=2))
    right = _hand(0.04, label="Right", origin=(0.72, 0.50))
    left = _hand(0.20, label="Left", origin=(0.28, 0.50))
    assert machine.step(_frame((left, right))) == "idle"
    assert machine.step(_frame((left, right))) == "fist"
    assert machine.step(_frame((left,))) == "fist"
    assert not any(
        track.state == "fist" and track.who == "Left" for track in machine.tracks
    )
    assert any(getattr(track, "coasting", False) for track in machine.tracks)


def test_both_hands_can_pinch_at_once() -> None:
    machine = GestureMachine(GestureParams(frames_on=2, frames_off=2))
    left = _hand(0.04, label="Left", origin=(0.28, 0.50))
    right = _hand(0.04, label="Right", origin=(0.72, 0.50))
    assert machine.step(_frame((left, right))) == "idle"
    assert machine.step(_frame((left, right))) == "fist"
    closed = {track.who for track in machine.tracks if track.state == "fist"}
    assert closed == {"Left", "Right"}


def test_a_duplicate_detection_is_one_hand() -> None:
    """C920 often reports the same fist as Left and Right."""
    machine = GestureMachine(GestureParams(frames_on=2, frames_off=2))
    right = _pinch_hand(0.04, label="Right", origin=(0.50, 0.50))
    ghost = _pinch_hand(0.04, label="Left", origin=(0.52, 0.50))
    assert machine.step(_frame((right, ghost))) == "idle"
    assert machine.step(_frame((right, ghost))) == "pinch"
    assert len(machine.tracks) == 1


def test_a_fist_is_not_a_pinch() -> None:
    """The old fixture was a fist. Aperture is closed; other fingers are not out."""
    fist = _hand(0.04)
    pinch = _pinch_hand(0.04)
    opened = _hand(0.20)
    assert read_pose(fist) == "fist"
    assert read_pose(pinch) == "pinch"
    assert read_pose(opened) == "open"
    assert fist.hand_curl() > pinch.hand_curl()
    assert pinch.hand_curl() < 0.28


def test_a_turned_pinch_still_reads_as_a_pinch() -> None:
    """2D blob, 3D fingers out — that is a pinch, not a fist."""
    turned = _pinch_hand(0.04, into_z=True)
    assert turned.pinch_span_xy() < 0.06
    assert read_pose(turned) == "pinch"
    machine = GestureMachine()
    frame = _frame((turned,))
    assert machine.step(frame) == "idle"
    assert machine.step(frame) == "pinch"


def test_a_turned_fist_still_reads_as_a_fist() -> None:
    pts = [(0.0, 0.0, 0.0)] * 21
    pts[4] = (0.0, 0.0, 0.0)
    pts[8] = (0.04, 0.0, 0.0)
    pts[5] = (0.0, 0.0, 0.0)
    pts[17] = (0.01, 0.0, 0.20)
    turned = Hand(
        label="Right",
        landmarks=tuple(
            Landmark(x=p[0], y=p[1], z=p[2], name=str(i)) for i, p in enumerate(pts)
        ),
        score=1.0,
    )
    assert turned.pinch_metric() < 0.3
    assert read_pose(turned) == "fist"


def test_kind_does_not_flip_from_fist_to_pinch_while_closed() -> None:
    machine = GestureMachine()
    fist = _frame((_hand(0.04),))
    assert machine.step(fist) == "idle"
    assert machine.step(fist) == "fist"
    assert machine.step(_frame((_pinch_hand(0.04),))) == "fist"


def test_a_3d_fist_at_the_camera_is_still_a_fist() -> None:
    """Tip–MCP along z looks like an open finger. Knuckle fold does not."""
    ox, oy = 0.40, 0.40
    pts = [(ox, oy, 0.0)] * 21
    pts[4] = (ox, oy, 0.0)
    pts[8] = (ox + 0.04, oy, 0.0)
    pts[5] = (ox, oy, 0.0)
    pts[17] = (ox + 0.20, oy, 0.0)
    for mcp, pip, dip, tip in (
        (9, 10, 11, 12),
        (13, 14, 15, 16),
        (17, 18, 19, 20),
    ):
        mx = ox + (0.0 if mcp == 9 else 0.07 if mcp == 13 else 0.20)
        pts[mcp] = (mx, oy, 0.0)
        pts[pip] = (mx + 0.02, oy, 0.05)
        pts[dip] = (mx + 0.04, oy, 0.05)
        pts[tip] = (mx + 0.04, oy, 0.01)
    fist = Hand(
        label="Right",
        landmarks=tuple(
            Landmark(x=p[0], y=p[1], z=p[2], name=str(i)) for i, p in enumerate(pts)
        ),
        score=1.0,
    )
    assert fist.finger_extension() > 0.2
    assert fist.hand_curl() > 0.35
    assert read_pose(fist) == "fist"


def test_fist_and_pinch_together_are_both() -> None:
    machine = GestureMachine(GestureParams(frames_on=2, frames_off=2))
    fist = _hand(0.04, label="Right", origin=(0.72, 0.50))
    pinch = _pinch_hand(0.04, label="Left", origin=(0.28, 0.50))
    assert machine.step(_frame((fist, pinch))) == "idle"
    assert machine.step(_frame((fist, pinch))) == "both"
    kinds = {track.who: track.state for track in machine.tracks}
    assert kinds["Right"] == "fist"
    assert kinds["Left"] == "pinch"


def test_fit_size_shrinks_1080p() -> None:
    w, h = fit_size(1920, 1080, POSE_MAX_WIDTH)
    assert w == POSE_MAX_WIDTH
    assert h == 360
    assert fit_size(320, 240, POSE_MAX_WIDTH) == (320, 240)


def test_disc_attaches_near_and_ignores_far() -> None:
    scene = WorldScene()
    scene.disc.x, scene.disc.y = 0.5, 0.5
    scene.apply_pointer(0.9, 0.9, True)
    assert not scene.disc.attached
    assert scene.disc.x == 0.5
    scene.apply_pointer(0.52, 0.50, True)
    assert scene.disc.attached
    assert abs(scene.disc.x - 0.52) < 1e-9
    scene.apply_pointer(0.7, 0.3, True)
    assert abs(scene.disc.x - 0.7) < 1e-9
    scene.apply_pointer(0.7, 0.3, False)
    assert not scene.disc.attached
    assert abs(scene.disc.x - 0.7) < 1e-9


def test_leave_drops_attach_and_resets() -> None:
    scene = WorldScene()
    scene.apply_pointer(0.5, 0.5, True)
    assert scene.disc.attached
    scene.drop()
    assert not scene.disc.attached
    scene.reset()
    assert scene.disc.x == 0.5
    assert not scene.disc.attached
