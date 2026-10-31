"""Chromium flags for her view, merged into QTWEBENGINE_CHROMIUM_FLAGS at start.

Babbage, 4d5ef87: in Filament she drew right after a resize settled, then went
blank about 5 s later at the same size, and minimize/restore flipped her either
way within 300 ms. That is Windows native occlusion: the native tile windows
over or near the hub made Chromium treat her view as occluded and stop
presenting it. These flags keep her page visible and unthrottled.
QtWebEngine reads the variable once, so this must run before it initialises.
"""

from __future__ import annotations

import logging
import os
from collections.abc import MutableMapping

log = logging.getLogger(__name__)

VAR = "QTWEBENGINE_CHROMIUM_FLAGS"
DISABLE_FEATURES = ("CalculateNativeWinOcclusion",)
SWITCHES = ("--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding")

# A/B switch for the Filament blank (966aeae: she renders but frames do not
# reach the screen). Flip with an env var, no rebuild; read before Qt starts.
ARM_VAR = "ARELIS_GPU_ARM"
ARMS: dict[str, tuple[str, ...]] = {
    "default": (),
    "d3d11": ("--use-angle=d3d11",),
    "gl": ("--use-angle=gl",),
    "nocomp": ("--disable-gpu-compositing",),
}


def arm(env: MutableMapping[str, str] | None = None) -> str:
    target = os.environ if env is None else env
    name = str(target.get(ARM_VAR) or "default").strip().lower() or "default"
    if name not in ARMS:
        log.warning("%s=%s unknown, using default (known: %s)", ARM_VAR, name, ", ".join(ARMS))
        return "default"
    return name


def merge_flags(current: str, arm_name: str = "default") -> str:
    """Add our switches and --disable-features values; keep everything already there."""
    parts = current.split()
    features: list[str] = []
    rest: list[str] = []
    for part in parts:
        if part.startswith("--disable-features="):
            features += [f for f in part.split("=", 1)[1].split(",") if f]
        else:
            rest.append(part)
    for feature in DISABLE_FEATURES:
        if feature not in features:
            features.append(feature)
    for switch in (*SWITCHES, *ARMS[arm_name]):
        if switch not in rest:
            rest.append(switch)
    return " ".join([*rest, "--disable-features=" + ",".join(features)])


def apply(env: MutableMapping[str, str] | None = None) -> str:
    target = os.environ if env is None else env
    target[VAR] = merge_flags(str(target.get(VAR) or ""), arm(target))
    return target[VAR]
