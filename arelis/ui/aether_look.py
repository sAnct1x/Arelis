"""Arelis's colours, read from the web scene's own config.js.

The 3D scene and the filament room share one source: the ``LOOK`` block in
persona_face/web/config.js, with the per-model override for the shipped
figure. The scene feeds those linear values to its shaders and the output
pass encodes them to sRGB, so the same encode here gives the colours she
shows on screen. Edit config.js and both follow.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

CONFIG_JS = Path(__file__).resolve().parent / "persona_face" / "web" / "config.js"
MODEL = "ellah"  # the shipped figure's override key in MODEL_LOOK

_FALLBACK = {
    "violet": (0.25, 0.07, 0.78),
    "lilac": (0.37, 0.17, 0.87),
    "interior": (0.06, 0.02, 0.16),
}


def _encode(v: float) -> int:
    v = max(0.0, min(1.0, v))
    s = 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
    return round(s * 255)


def _triples(block: str) -> dict[str, tuple[float, float, float]]:
    found = re.findall(r"(violet|lilac|interior)\s*:\s*\[([^\]]+)\]", block)
    return {k: tuple(float(x) for x in v.split(",")) for k, v in found}  # type: ignore[misc]


@cache
def aether_rgb() -> dict[str, tuple[int, int, int]]:
    """violet, lilac, interior and spark as on-screen sRGB."""
    lin = dict(_FALLBACK)
    try:
        src = CONFIG_JS.read_text(encoding="utf-8")
        base = src.split("export const MODEL_LOOK", 1)
        lin.update(_triples(base[0]))
        tail = base[1] if len(base) > 1 else ""
        model = re.search(rf"'{MODEL}'\s*:\s*\{{(.*?)\n\s*\}},", tail, re.S)
        if model:
            lin.update(_triples(model.group(1)))
    except OSError:
        pass
    out = {k: tuple(_encode(c) for c in v) for k, v in lin.items()}
    # The scene lifts her brightest threads toward white; spark is that point.
    out["spark"] = tuple(round(c + (255 - c) * 0.75) for c in out["lilac"])
    return out  # type: ignore[return-value]
