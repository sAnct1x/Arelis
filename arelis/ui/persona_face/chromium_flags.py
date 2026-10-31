"""Chromium flags for her view, merged into QTWEBENGINE_CHROMIUM_FLAGS at start.

Babbage, 4d5ef87: in Filament she drew right after a resize settled, then went
blank about 5 s later at the same size, and minimize/restore flipped her either
way within 300 ms. That is Windows native occlusion: the native tile windows
over or near the hub made Chromium treat her view as occluded and stop
presenting it. These flags keep her page visible and unthrottled.
QtWebEngine reads the variable once, so this must run before it initialises.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping

VAR = "QTWEBENGINE_CHROMIUM_FLAGS"
DISABLE_FEATURES = ("CalculateNativeWinOcclusion",)
SWITCHES = ("--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding")


def merge_flags(current: str) -> str:
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
    for switch in SWITCHES:
        if switch not in rest:
            rest.append(switch)
    return " ".join([*rest, "--disable-features=" + ",".join(features)])


def apply(env: MutableMapping[str, str] | None = None) -> str:
    target = os.environ if env is None else env
    target[VAR] = merge_flags(str(target.get(VAR) or ""))
    return target[VAR]
