"""Approved nebula face. The bake uses the v2.3 renderer and the adult rig.

The old in-app drawing drifted pale and thin. This module is the dock-sized
entry to that renderer: one shared rig, layers in RAM, no per-frame redraw.
"""

from __future__ import annotations

from arelis.ui.persona_face.face_src import EYE_X, EYE_Y, smooth
from arelis.ui.persona_face.plate import (
    BLINK_LEVELS,
    FACE_T,
    GAZE_LEVELS,
    MOUTH_LEVELS,
    PHASE_COUNT,
    PHASE_T,
    VIEW,
    Rig,
    bake_layers,
    paint_eyes,
    paint_face,
    paint_mouth,
    raster_size,
    unstretch_y,
)

__all__ = [
    "BLINK_LEVELS",
    "EYE_X",
    "EYE_Y",
    "FACE_T",
    "GAZE_LEVELS",
    "MOUTH_LEVELS",
    "PHASE_COUNT",
    "PHASE_T",
    "VIEW",
    "Rig",
    "bake_layers",
    "paint_eyes",
    "paint_face",
    "paint_mouth",
    "raster_size",
    "smooth",
    "unstretch_y",
]
