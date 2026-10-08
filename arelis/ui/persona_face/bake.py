"""Bake the face once in memory, then stack the layers for a still frame."""

from __future__ import annotations

import numpy as np

from arelis.ui.persona_face.engine import VIEW, bake_layers

__all__ = ["VIEW", "bake_layers", "composite_rest", "flatten_on_black"]


def _unit(image: np.ndarray) -> np.ndarray:
    return image.astype(np.float32) / 255.0


def _pack(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    out = np.empty((*rgb.shape[:2], 4), dtype=np.uint8)
    out[..., 0] = np.clip(rgb[..., 0] * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out[..., 1] = np.clip(rgb[..., 1] * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out[..., 2] = np.clip(rgb[..., 2] * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(alpha * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return out


def over(base: np.ndarray, src: np.ndarray) -> np.ndarray:
    """Source-over. Both images are premultiplied."""
    b = _unit(base)
    s = _unit(src)
    sa = s[..., 3:4]
    rgb = s[..., :3] + b[..., :3] * (1.0 - sa)
    alpha = sa[..., 0] + b[..., 3] * (1.0 - sa[..., 0])
    return _pack(np.clip(rgb, 0.0, 1.0), np.clip(alpha, 0.0, 1.0))


def screen(base: np.ndarray, src: np.ndarray) -> np.ndarray:
    """Light layers add the way stacked glow does. Both images are premultiplied."""
    b = _unit(base)
    s = _unit(src)
    rgb = np.clip(b[..., :3] + s[..., :3], 0.0, 1.0)
    alpha = np.clip(b[..., 3] + s[..., 3], 0.0, 1.0)
    return _pack(rgb, alpha)


def composite_rest(layers: dict[str, np.ndarray]) -> np.ndarray:
    """Calm face: open eyes, closed mouth, hair and ring stacked."""
    acc = np.zeros_like(layers["face"])
    for name in ("wisps", "hair_tip", "hair_mid", "hair_root"):
        acc = screen(acc, layers[name])
    acc = over(acc, layers["face"])
    acc = over(acc, layers["mouth_0"])
    acc = over(acc, layers["eye_0"])
    for name in ("hair_front", "ring", "star"):
        acc = screen(acc, layers[name])
    return acc


def flatten_on_black(image: np.ndarray) -> np.ndarray:
    """Visible color over black, opaque, so a grab can be compared."""
    out = np.zeros_like(image)
    out[..., 0] = image[..., 0]
    out[..., 1] = image[..., 1]
    out[..., 2] = image[..., 2]
    out[..., 3] = 255
    return out
