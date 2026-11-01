"""Her GPU cost, measured: per-frame GPU time and per-pass ablation (a measurement build).

Everything here is off unless an env var asks for it; read once, when her host starts.

``ARELIS_GPU_PROFILE=1``
    Turns on QRhi timestamps (``QSG_RHI_PROFILE=1``, which Qt reads when it creates
    the window's QRhi, so ``enable_timestamps`` runs before the QApplication) and writes
    one ``t_epoch_ms,gpu_ms,interval_ms`` line per frame her QQuickWidget renders to
    ``ARELIS_GPU_PROFILE_LOG`` (default ``arelis_gpu_frames.csv`` in the working folder).
    ``gpu_ms`` is ``QRhiCommandBuffer::lastCompletedGpuTime`` of the command buffer her
    frame is recorded on: her scene, the bloom chain, and the widget's own blit. The
    value is the last frame the GPU has finished, so it lags one or two frames; 0 means
    no timing yet (or the backend has none).

Ablation, each independent and combinable:
    ``ARELIS_GPU_NO_BLOOM=1``      no AetherBloom (the effects list is empty)
    ``ARELIS_GPU_BLOOM_HALF=1``    bloom buffers at half their size (0.25 .. 0.015625)
    ``ARELIS_GPU_NO_PARTICLES=1``  hide the point-sprite layers (galaxy L0, motes L37..L43)
    ``ARELIS_GPU_NO_HAIR=1``       hide the hair layers (Hair fills L31..L33, rims L34..L36)
                                   and the threads (L44)
    ``ARELIS_GPU_COMPOSITE_ONLY=1`` hide her whole figure: what is left is the clear, the
                                   bloom chain (unless NO_BLOOM) and the composite
    ``ARELIS_GPU_RENDER_SCALE=s``  her View3D texture at s x her band (1.0, 0.75, 0.5),
                                   scaled up when drawn
    ``ARELIS_GPU_HIDE=L3,L37-L43``  hide any layers by name (L<i> aether layer, S<i> skin
                                   shell, or a balsam node name), for a single pass

Layer numbers follow the look's export (scene/layers.json): L0 galaxy points, L1..L36
body/eye/teeth/brow/hair fills and rims, L37..L43 point motes, L44 threads, L45 floor.
"""

from __future__ import annotations

import os
import re
import time

PROFILE_ENV = "ARELIS_GPU_PROFILE"
PROFILE_LOG_ENV = "ARELIS_GPU_PROFILE_LOG"
DEFAULT_LOG = "arelis_gpu_frames.csv"
_ON = {"1", "true", "yes", "on"}

PARTICLES = ["L0"] + [f"L{i}" for i in range(37, 44)]
HAIR = [f"L{i}" for i in range(31, 37)] + ["L44"]


def _on(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _ON


def profiling() -> bool:
    return _on(PROFILE_ENV)


def enable_timestamps(env=os.environ) -> None:
    """Before the QApplication: ask Qt Quick for a QRhi with timestamps."""
    if env.get(PROFILE_ENV, "").strip().lower() in _ON:
        env.setdefault("QSG_RHI_PROFILE", "1")


def _expand(spec: str) -> list[str]:
    out: list[str] = []
    for part in (p.strip() for p in spec.split(",")):
        m = re.fullmatch(r"([LS])(\d+)-[LS]?(\d+)", part)
        if m:
            out += [f"{m.group(1)}{i}" for i in range(int(m.group(2)), int(m.group(3)) + 1)]
        elif part:
            out.append(part)
    return out


def render_scale() -> float:
    try:
        s = float(os.environ.get("ARELIS_GPU_RENDER_SCALE", "1") or 1)
    except ValueError:
        return 1.0
    return min(1.0, max(0.1, s))


def ablation() -> dict[str, object]:
    """The root properties Avatar.qml reads for the ablation; all defaults mean no change."""
    hidden = _expand(os.environ.get("ARELIS_GPU_HIDE", ""))
    if _on("ARELIS_GPU_NO_PARTICLES"):
        hidden += PARTICLES
    if _on("ARELIS_GPU_NO_HAIR"):
        hidden += HAIR
    return {
        "noBloom": _on("ARELIS_GPU_NO_BLOOM"),
        "bloomRes": 0.5 if _on("ARELIS_GPU_BLOOM_HALF") else 1.0,
        "compositeOnly": _on("ARELIS_GPU_COMPOSITE_ONLY"),
        "renderScale": render_scale(),
        "hiddenLayers": sorted(set(hidden)),
    }


class GpuLog:
    """One ``t_epoch_ms,gpu_ms,interval_ms`` line per frame; connect ``frame`` to afterRendering."""

    def __init__(self, window, path: str) -> None:
        self._window = window
        self._file = open(path, "w", encoding="utf-8", buffering=1 << 16)
        self._file.write("t_epoch_ms,gpu_ms,interval_ms\n")
        self._last: float | None = None

    def _gpu_ms(self) -> float:
        import shiboken6
        from PySide6.QtGui import QRhiCommandBuffer
        from PySide6.QtQuick import QSGRendererInterface

        ri = self._window.rendererInterface()
        ptr = ri.getResource(self._window, QSGRendererInterface.Resource.RhiRedirectCommandBuffer)
        if ptr is None:
            return 0.0
        addr = int(re.search(r"Address 0x([0-9a-fA-F]+)", str(ptr)).group(1), 16)
        if not addr:
            return 0.0
        return shiboken6.wrapInstance(addr, QRhiCommandBuffer).lastCompletedGpuTime() * 1000.0

    def frame(self, *_args) -> None:
        if self._file is None:
            return
        now = time.time() * 1000.0
        gap = now - self._last if self._last is not None else 0.0
        self._last = now
        self._file.write(f"{now:.2f},{self._gpu_ms():.3f},{gap:.3f}\n")

    def flush(self) -> None:
        if self._file is not None:
            self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


def gpu_log(window) -> GpuLog | None:
    if not profiling():
        return None
    return GpuLog(window, os.environ.get(PROFILE_LOG_ENV, "").strip() or DEFAULT_LOG)
