"""Filament Hands chip and session life. Camera tile is inspect-only."""

from __future__ import annotations

from arelis.config import merge_local_config
from arelis.spatial.grant import world_stage_allowed
from arelis.ui.theme import active_theme


def apply_hands_face(window) -> None:
    """Grant + chip follow the live theme. Sodium keeps camera → Track."""
    filament = active_theme() == "filament"
    chip = bool(getattr(window, "_hands_chip", False))
    window.spatial.set_face(filament=filament, chip=chip)
    floats = getattr(window, "_filament_floats", None)
    if floats is not None:
        floats.set_hands_on(filament and chip)
        if hasattr(floats, "hands_btn"):
            floats.hands_btn.setVisible(filament and world_stage_allowed())
    if filament and chip and world_stage_allowed():
        _ensure_session(window)
        return
    if not filament and not window.spatial.tracking:
        return
    if not filament:
        # Sodium: only the camera Track button keeps a session.
        if not window.camera.track_btn.isChecked():
            window.spatial.stop_track()


def on_hands_chip(window, on: bool) -> None:
    window._hands_chip = bool(on)
    window.config.setdefault("ui", {})["hands_chip"] = bool(on)
    merge_local_config({"ui": {"hands_chip": bool(on)}})
    apply_hands_face(window)


def park_hands(window) -> None:
    if window.spatial.tracking:
        window.spatial.park_session()
        if getattr(window.camera, "_running", False) and not window.camera_dock.isVisible():
            window.camera.stop()


def resume_hands(window) -> None:
    apply_hands_face(window)


def _ensure_session(window) -> None:
    if not world_stage_allowed():
        return
    tile_up = window.camera_dock.isVisible()
    window.spatial.set_preview_wanted(tile_up)
    if not getattr(window.camera, "_running", False):
        from arelis.spatial.video import POSE_MAX_WIDTH, PREVIEW_CAPTURE_MAX_WIDTH

        window.camera.start(
            max_width=PREVIEW_CAPTURE_MAX_WIDTH if tile_up else POSE_MAX_WIDTH
        )
    window.spatial.start_track({"device": window.camera.current_device_name()})
