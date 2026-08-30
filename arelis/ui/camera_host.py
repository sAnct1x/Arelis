"""Camera dock and spatial hands. Window methods stay as delegates."""

from __future__ import annotations

import math
import time

from arelis.paths import display_path
from arelis.spatial.depth import ESTIMATOR
from arelis.spatial.scene import GRAVITY, REACH_DEFAULT, image_to_world
from arelis.spatial.types import grab_drive
from arelis.ui.dock_surface import chrome_applying


def on_camera_dock_visibility(window, visible: bool) -> None:
    if chrome_applying(window.camera_dock):
        return
    if visible:
        window.camera.start()
    else:
        window.camera.stop()
    window._refresh_camera_capture_hook()


def on_camera_running_changed(window, _running: bool) -> None:
    window._refresh_camera_capture_hook()


def on_camera_track(window, on: bool) -> None:
    if on:
        if not getattr(window.camera, "_running", False):
            window.camera.start()
        ok = window.spatial.start_track(
            {"device": window.camera.current_device_name()}
        )
        if not ok:
            window.camera.track_btn.blockSignals(True)
            window.camera.track_btn.setChecked(False)
            window.camera.track_btn.blockSignals(False)
        return
    window.spatial.stop_track()
    window.camera.set_hands(())


def on_camera_record(window, on: bool) -> None:
    if on:
        path = window.spatial.start_record(
            {
                "device": window.camera.current_device_name(),
                "gravity": GRAVITY,
                "rung": 3,
                "estimator": ESTIMATOR,
            }
        )
        if path is None:
            window.camera.record_btn.blockSignals(True)
            window.camera.record_btn.setChecked(False)
            window.camera.record_btn.blockSignals(False)
        return
    window.spatial.stop_record()


def on_camera_pose(window, payload: object) -> None:
    if not isinstance(payload, tuple) or len(payload) != 4:
        return
    rgb, t_capture, width, height = payload
    window.spatial.submit_frame(rgb, t_capture, width, height)


def on_camera_pose_video(window, frame: object, t_capture: float) -> None:
    window.spatial.submit_video(frame, t_capture)


def on_spatial_recording(window, on: bool) -> None:
    if window.camera.record_btn.isChecked() == on:
        return
    window.camera.record_btn.blockSignals(True)
    window.camera.record_btn.setChecked(on)
    window.camera.record_btn.blockSignals(False)


def hand_depth(window, who: str, hand: object, stamp: float, frame: object) -> float | None:
    """Palm-pinhole z, or none if the frame has no size."""
    if hand is None or not hasattr(window, "world_depth"):
        return None
    width = int(getattr(frame, "width", 0) or 0)
    height = int(getattr(frame, "height", 0) or 0)
    if width < 1 or height < 1:
        return None
    return window.world_depth.observe(
        who, hand, t=stamp, width=width, height=height
    )


def on_spatial_hands(window, frame: object) -> None:
    if frame is None:
        window._closed_off.clear()
        window.camera.set_hands(())
        if hasattr(window, "world_depth"):
            window.world_depth.reset()
        window.world_scene.drop(t=time.perf_counter())
        if hasattr(window, "world_window") and not window.world_window.isHidden():
            window.world_window.panel.clear_hand()
        return
    hands = getattr(frame, "hands", ())
    state = str(getattr(window.spatial, "last_state", "") or "idle")
    fps = float(getattr(window.spatial, "last_fps", 0.0) or 0.0)
    tracks = tuple(getattr(window.spatial, "last_tracks", ()) or ())
    closed_kinds: dict[str, str] = {}
    overlay_hands = list(hands)
    for track in tracks:
        st = str(getattr(track, "state", "") or "")
        who = str(getattr(track, "who", "") or "")
        if who and st in ("fist", "pinch"):
            closed_kinds[who] = st
        held = getattr(track, "hand", None)
        if (
            getattr(track, "coasting", False)
            and held is not None
            and not any(h is held for h in overlay_hands)
        ):
            overlay_hands.append(held)
    window.camera.set_hands(
        tuple(overlay_hands),
        closed=bool(closed_kinds),
        state=state,
        fps=fps,
        closed_kinds=closed_kinds,
    )
    world_up = hasattr(window, "world_window") and not window.world_window.isHidden()
    solar = world_up and window.world_window.solar_active()
    reach = getattr(window, "_world_reach", REACH_DEFAULT)
    stamp = float(getattr(frame, "t_capture", time.perf_counter()))
    apertures: list[tuple[tuple[float, float], tuple[float, float], bool]] = []
    alive: set[str] = set()
    ordered = sorted(
        tracks,
        key=lambda track: (
            0
            if str(getattr(track, "state", "") or "") in ("fist", "pinch")
            else 1,
            0
            if getattr(track, "who", "") == "Left"
            else 1
            if getattr(track, "who", "") == "Right"
            else 2,
            str(getattr(track, "who", "")),
        ),
    )
    for track in ordered:
        who = str(getattr(track, "who", "") or "")
        hand = getattr(track, "hand", None)
        st = str(getattr(track, "state", "") or "idle")
        held = window.world_scene.held_names()
        if who in held and st in ("fist", "pinch"):
            alive.add(who)
        if getattr(track, "coasting", False):
            if who in held and st in ("fist", "pinch"):
                alive.add(who)
                if window.world_scene.is_flicking(who):
                    window.world_scene.drop(t=stamp, who=who)
                    alive.discard(who)
                    continue
                # Last closed pose still drives the ball. Skipping
                # apply_pointer here was the freeze-then-jump.
            else:
                continue
        if hand is None:
            if who:
                window._closed_off.pop(who, None)
            if who in held:
                window.world_scene.drop(t=stamp, who=who)
            elif who:
                window.world_scene.forget_pending(who)
            continue
        thumb, index = hand.pinch_tips()
        holding = st in ("fist", "pinch")
        centroid, off = grab_drive(
            hand, closed=holding, offset=window._closed_off.get(who)
        )
        if who and off is not None:
            window._closed_off[who] = off
        elif who:
            window._closed_off.pop(who, None)
        tw, ti = image_to_world(*thumb, reach=reach), image_to_world(*index, reach=reach)
        cw = image_to_world(*centroid, reach=reach)
        if not solar:
            window.world_scene.apply_pointer(
                cw[0],
                cw[1],
                holding,
                t=stamp,
                who=who,
                kind=st if holding else "open",
                z=window._hand_depth(who, hand, stamp, frame),
            )
        if st == "fist":
            apertures.append((cw, cw, True))
        elif st == "pinch":
            apertures.append((tw, ti, True))
        else:
            apertures.append((tw, ti, False))
    live = {
        str(getattr(track, "who", "") or "")
        for track in ordered
        if getattr(track, "hand", None) is not None
    }
    if tracks:
        window.world_scene.forget_absent(live, t=stamp)
    if not tracks and hands:
        hand = hands[0]
        holding = state in ("fist", "pinch", "both")
        kind = "fist" if state in ("fist", "both") else "pinch" if state == "pinch" else "open"
        centroid, off = grab_drive(
            hand, closed=holding, offset=window._closed_off.get("")
        )
        if off is not None:
            window._closed_off[""] = off
        else:
            window._closed_off.pop("", None)
        cw = image_to_world(*centroid, reach=reach)
        if not solar:
            window.world_scene.apply_pointer(
                cw[0],
                cw[1],
                holding,
                t=stamp,
                kind=kind,
                z=window._hand_depth("", hand, stamp, frame),
            )
        if holding and kind == "fist":
            apertures.append((cw, cw, True))
        elif holding:
            thumb, index = hand.pinch_tips()
            apertures.append(
                (
                    image_to_world(*thumb, reach=reach),
                    image_to_world(*index, reach=reach),
                    True,
                )
            )
        else:
            thumb, index = hand.pinch_tips()
            apertures.append(
                (
                    image_to_world(*thumb, reach=reach),
                    image_to_world(*index, reach=reach),
                    False,
                )
            )
    if window.world_scene.bodies:
        for body in window.world_scene.bodies:
            if (
                body.attached
                and body.holder
                and body.holder not in alive
                and not any(
                    str(getattr(track, "who", "") or "") == body.holder
                    for track in tracks
                )
            ):
                window.world_scene.drop(t=stamp, who=body.holder)
    if not hands and not tracks:
        window.world_scene.drop(t=stamp)
        if world_up:
            window.world_window.panel.clear_hand()
        return
    if world_up:
        if solar:
            if apertures:
                (t0, i0, pinched) = apertures[0]
                mx = (t0[0] + i0[0]) * 0.5
                my = (t0[1] + i0[1]) * 0.5
                span = math.hypot(t0[0] - i0[0], t0[1] - i0[1])
                z = None
                if tracks:
                    hand0 = getattr(ordered[0], "hand", None) if ordered else None
                    who0 = str(getattr(ordered[0], "who", "") or "") if ordered else ""
                    if hand0 is not None:
                        z = window._hand_depth(who0, hand0, stamp, frame)
                window.world_window.solar.apply_hand(
                    mx, my, pinched=pinched, span=span, palm_z=z
                )
            else:
                window.world_window.solar.apply_hand(
                    0.5, 0.5, pinched=False, span=0.0, palm_z=None
                )
        else:
            window.world_window.panel.set_apertures(apertures)


def refresh_camera_capture_hook(window) -> None:
    """Expose live capture to the camera tool while the dock session is up."""
    if getattr(window.camera, "_running", False):
        window.config["_camera_capture"] = window.camera.snapshot_blocking
    else:
        window.config.pop("_camera_capture", None)


def on_camera_ask(window, path: str) -> None:
    """Dock Ask Arelis: submit a look-on-ask turn naming the snapshot path."""
    path_text = display_path(path)
    text = (
        f"Look at the camera frame at {path_text}. What do you see?"
    )
    if not window.camera_dock.isVisible():
        window.camera_dock.show()
        window.camera_dock.raise_()
    window.conversation.input.setFocus()
    role = str(window._current_role or "fast")
    window._on_submit(text, role)

