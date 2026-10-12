"""Cut a subject out of a picture with ISNet or BiRefNet.

Same preparation the published weights expect. No rembg: the session
comes from image_models, on the CPU, and the mask is composited here.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image

from arelis.tools import image_models


def cutout(image: Any, model_name: str) -> Any:
    spec = image_models.MODELS[model_name]
    session = image_models.session_for(model_name)
    feed = _prepare(image, spec.input_size, spec.mean, spec.std)
    input_name = session.get_inputs()[0].name
    raw = session.run(None, {input_name: feed})[0]
    mask = _mask(raw, image.size, sigmoid=spec.sigmoid)
    return _composite(image, mask)


def _prepare(
    image: Any,
    size: tuple[int, int],
    mean: tuple[float, float, float],
    std: tuple[float, float, float],
) -> Any:
    resized = image.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    pixels = np.asarray(resized).astype(np.float32)
    pixels = pixels / max(float(np.max(pixels)), 1e-6)
    mean_arr = np.asarray(mean, dtype=np.float32)
    std_arr = np.asarray(std, dtype=np.float32)
    normalised = (pixels - mean_arr) / std_arr
    chw = np.transpose(normalised, (2, 0, 1))
    return np.expand_dims(chw, 0).astype(np.float32)


def _mask(raw: Any, size: tuple[int, int], *, sigmoid: bool) -> Any:
    pred = np.asarray(raw, dtype=np.float32)[:, 0, :, :]
    if sigmoid:
        pred = 1.0 / (1.0 + np.exp(-pred))
    pred = np.squeeze(pred)
    high = float(np.max(pred))
    low = float(np.min(pred))
    if high > low:
        pred = (pred - low) / (high - low)
    else:
        pred = np.zeros_like(pred)
    pred = np.clip(pred, 0.0, 1.0)
    mask = Image.fromarray((pred * 255).astype(np.uint8), mode="L")
    return mask.resize(size, Image.Resampling.LANCZOS)


def _composite(image: Any, mask: Any) -> Any:
    rgba = image.convert("RGBA")
    rgba.putalpha(mask)
    return rgba
