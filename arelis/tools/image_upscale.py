"""Tiled 4x upscale with Real-ESRGAN general x4v3.

128 px tiles, 8 px overlap thrown away, so the join is the model's
interior and not its border. A 2x ask runs the same model and then
shrinks. CPU only.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from arelis.tools import image_models

TILE = 128
OVERLAP = 8
_SCIENCE = re.compile(r"(?i)(\.fits|\bfits\b|telescope|\bastro)")


def tiled_upscale(
    rgb: Any,
    predict: Callable[[Any], Any],
    *,
    tile: int = TILE,
    overlap: int = OVERLAP,
    scale: int = 4,
) -> Any:
    """rgb is HWC float in 0..1. predict takes NCHW and returns NCHW."""
    height, width, _channels = rgb.shape
    pad = overlap
    padded = np.pad(
        rgb,
        ((pad, pad + tile), (pad, pad + tile), (0, 0)),
        mode="reflect",
    )
    out = np.zeros((height * scale, width * scale, 3), np.float32)
    step = tile - 2 * pad
    for y in range(0, height, step):
        for x in range(0, width, step):
            piece = padded[y : y + tile, x : x + tile]
            feed = np.ascontiguousarray(piece.transpose(2, 0, 1)[None])
            pred = np.asarray(predict(feed)[0]).transpose(1, 2, 0)
            core = pred[
                pad * scale : (tile - pad) * scale,
                pad * scale : (tile - pad) * scale,
            ]
            row = min(step * scale, height * scale - y * scale)
            col = min(step * scale, width * scale - x * scale)
            out[y * scale : y * scale + row, x * scale : x * scale + col] = core[
                :row, :col
            ]
    return out


def upscale_image(image: Any, factor: int) -> Any:
    if factor not in (2, 4):
        raise ValueError("upscale must be 2 or 4.")
    session = image_models.session_for("realesrgan-x4v3")
    input_name = session.get_inputs()[0].name
    rgb = np.asarray(image.convert("RGB")).astype(np.float32) / 255.0

    def predict(feed: Any) -> Any:
        return session.run(None, {input_name: feed})[0]

    out = tiled_upscale(rgb, predict)
    picture = Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8), mode="RGB")
    if factor == 2:
        picture = picture.resize(
            (image.width * 2, image.height * 2), Image.Resampling.LANCZOS
        )
    if image.mode == "RGBA":
        alpha = image.getchannel("A").resize(picture.size, Image.Resampling.LANCZOS)
        picture = picture.convert("RGBA")
        picture.putalpha(alpha)
    return picture


def source_is_science(path: Path) -> bool:
    """A FITS-derived file, or a sidecar that says telescope or astro."""
    if path.suffix.lower() in {".fits", ".fit", ".fts"}:
        return True
    if _SCIENCE.search(path.name):
        return True
    sidecar = path.with_suffix(".json")
    if not sidecar.is_file():
        return False
    try:
        text = sidecar.read_text(encoding="utf-8")
    except OSError:
        return False
    return _SCIENCE.search(text) is not None


def mark_cosmetic(path: Path) -> None:
    dest = path.with_suffix(".json")
    payload: dict[str, Any] = {}
    if dest.is_file():
        try:
            found = json.loads(dest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            found = None
        if isinstance(found, dict):
            payload = found
    payload["cosmetic"] = True
    tmp = dest.with_suffix(".json.part")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, dest)
