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
import sys
from collections.abc import Callable, MutableMapping

log = logging.getLogger(__name__)

VAR = "QTWEBENGINE_CHROMIUM_FLAGS"
DISABLE_FEATURES = ("CalculateNativeWinOcclusion",)
SWITCHES = ("--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding")

# A/B switch for the Filament blank (966aeae: she renders but frames do not
# reach the screen). Flip with an env var, no rebuild; read before Qt starts.
# Default is d3d11: on Atria (gpuab, 2026-10-31) it held idle at 55-58 fps where
# no flag held 44-53, no arm fixed the blank, and gl lost WebGL. "none" is the
# old no-flag launch.
ARM_VAR = "ARELIS_GPU_ARM"
D3D11 = ("--use-angle=d3d11",)
ARMS: dict[str, tuple[str, ...]] = {
    "default": D3D11,
    "none": (),
    "d3d11": D3D11,
    "gl": ("--use-angle=gl",),
    "nocomp": ("--disable-gpu-compositing",),
    # m1-blank3: d3d11 plus no vsync / frame-rate cap. Tests whether the blank
    # is a present-timing race between Chromium's frame swap and Qt's flush.
    "novsync": (*D3D11, "--disable-gpu-vsync", "--disable-frame-rate-limit"),
}
NOVSYNC = ("--disable-gpu-vsync", "--disable-frame-rate-limit")

# m1-blank3 A/B: the Qt side that imports her frames. Since Qt 6.5.1 Chromium
# renders into shared DXGI buffers and Qt's D3D11 RHI samples them (Qt blog,
# "New graphics integration in Qt WebEngine 6.6 and even 6.5.1"). opengl moves
# the consumer to Qt's OpenGL RHI (WGL_NV_DX_interop2 import, a different
# sync path). Unset leaves Qt's default. Read before QApplication exists.
RHI_VAR = "ARELIS_QT_RHI"
RHI_KNOWN = ("opengl", "d3d11", "d3d12", "vulkan")
# qq3d gate1 (6160ae6, RX 6700 XT): on d3d11 the part of her body below a
# horizontal cut vanished in 108/372 frames, on vulkan in 0/374. The cause
# inside the d3d11 path is still unknown; this is a backend choice, not a
# d3d11 fix. Windows defaults to vulkan unless the user or Qt env pins one.
RHI_DEFAULT_WIN = "vulkan"
RHI_FALLBACK = "d3d11"
RHI_ENV = ("QSG_RHI_BACKEND", "QT_WIDGETS_RHI_BACKEND")


def apply_rhi(env: MutableMapping[str, str] | None = None, platform: str | None = None) -> str:
    """Pin Qt Quick and the widget backing store to ARELIS_QT_RHI; return it or 'default'.

    On Windows with nothing pinned (no ARELIS_QT_RHI, no QSG_RHI_BACKEND, no
    QT_WIDGETS_RHI_BACKEND) this pins vulkan; vulkan_fallback() undoes that
    if Vulkan cannot start.
    """
    target = os.environ if env is None else env
    name = str(target.get(RHI_VAR) or "").strip().lower()
    if not name:
        plat = sys.platform if platform is None else platform
        if plat != "win32" or any(target.get(var) for var in RHI_ENV):
            return "default"
        name = RHI_DEFAULT_WIN
    if name not in RHI_KNOWN:
        log.warning(
            "%s=%s unknown, leaving Qt default (known: %s)", RHI_VAR, name, ", ".join(RHI_KNOWN)
        )
        return "default"
    for var in RHI_ENV:
        target[var] = name
    return name


def vulkan_fallback(
    env: MutableMapping[str, str] | None = None, probe: Callable[[], str] | None = None
) -> str:
    """After QApplication exists, before the first window: if vulkan is pinned
    and cannot start, log why and pin d3d11 instead. Returns the backend in use."""
    target = os.environ if env is None else env
    if any(target.get(var) != "vulkan" for var in RHI_ENV):
        return rhi_arm(target)
    reason = (probe or _vulkan_problem)()
    if not reason:
        return "vulkan"
    log.warning("Qt RHI vulkan unavailable (%s), falling back to %s", reason, RHI_FALLBACK)
    for var in RHI_ENV:
        target[var] = RHI_FALLBACK
    return RHI_FALLBACK


def _vulkan_problem() -> str:
    """Empty when a QVulkanInstance can be created, else the reason it cannot."""
    try:
        from PySide6.QtGui import QVulkanInstance
    except Exception as exc:
        return f"QVulkanInstance not importable: {exc}"
    inst = QVulkanInstance()
    if not inst.create():
        return f"QVulkanInstance.create failed (VkResult {int(inst.errorCode())})"
    inst.destroy()
    return ""


def rhi_arm(env: MutableMapping[str, str] | None = None) -> str:
    target = os.environ if env is None else env
    name = str(target.get(RHI_VAR) or "").strip().lower()
    if name in RHI_KNOWN and target.get(RHI_ENV[0]) == name:
        return name
    pinned = str(target.get(RHI_ENV[0]) or "").strip().lower()
    return pinned if pinned in RHI_KNOWN else "default"


def arm(env: MutableMapping[str, str] | None = None) -> str:
    target = os.environ if env is None else env
    name = str(target.get(ARM_VAR) or "default").strip().lower() or "default"
    if name not in ARMS:
        log.warning("%s=%s unknown, using default (known: %s)", ARM_VAR, name, ", ".join(ARMS))
        return "default"
    return name


def effective_arm(env: MutableMapping[str, str] | None = None) -> str:
    """The arm the flags actually carry: the default arm logs as d3d11, a pinned
    --use-angle wins over ARELIS_GPU_ARM, and no GPU switch logs as none."""
    target = os.environ if env is None else env
    parts = str(target.get(VAR) or "").split()
    angle = [p.split("=", 1)[1] for p in parts if p.startswith("--use-angle=")]
    tail = "+novsync" if all(f in parts for f in NOVSYNC) else ""
    if angle:
        return angle[-1] + tail
    return "nocomp" if "--disable-gpu-compositing" in parts else "none"


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
    # An --use-angle already in the variable wins over the arm's.
    has_angle = any(p.startswith("--use-angle=") for p in rest)
    for switch in (*SWITCHES, *ARMS[arm_name]):
        if has_angle and switch.startswith("--use-angle=") and switch in ARMS[arm_name]:
            continue
        if switch not in rest:
            rest.append(switch)
    return " ".join([*rest, "--disable-features=" + ",".join(features)])


def apply(env: MutableMapping[str, str] | None = None) -> str:
    target = os.environ if env is None else env
    target[VAR] = merge_flags(str(target.get(VAR) or ""), arm(target))
    return target[VAR]
