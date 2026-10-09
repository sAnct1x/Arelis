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


def composite_rest(
    layers: dict[str, np.ndarray], phase: int = 0, *, star: bool = True
) -> np.ndarray:
    """Calm face at one hair phase: back hair, face, fringe, ring, star."""
    acc = np.zeros_like(layers["face"])
    back = layers.get(f"back_{phase}")
    if back is None and "hair_back" in layers:
        back = layers["hair_back"]
    if back is not None:
        acc = screen(acc, back)
    if "wisps" in layers:
        acc = screen(acc, layers["wisps"])
    acc = over(acc, layers["face"])
    acc = over(acc, layers["mouth_0"])
    acc = over(acc, layers["eye_0"])
    front = layers.get(f"front_{phase}")
    if front is None and "hair_front" in layers:
        front = layers["hair_front"]
    if front is not None:
        acc = screen(acc, front)
    acc = screen(acc, layers["ring"])
    if star and "star" in layers:
        acc = screen(acc, layers["star"])
    return acc


def _area_down(image: np.ndarray, small_h: int, small_w: int) -> np.ndarray:
    """Box average into a smaller grid. Each output pixel covers a real area."""
    height, width, channels = image.shape
    src = image.astype(np.float32)
    y_edges = np.linspace(0, height, small_h + 1).astype(np.int32)
    x_edges = np.linspace(0, width, small_w + 1).astype(np.int32)
    out = np.empty((small_h, small_w, channels), dtype=np.float32)
    for row in range(small_h):
        y0 = int(y_edges[row])
        y1 = max(y0 + 1, int(y_edges[row + 1]))
        for col in range(small_w):
            x0 = int(x_edges[col])
            x1 = max(x0 + 1, int(x_edges[col + 1]))
            out[row, col] = src[y0:y1, x0:x1].mean(axis=(0, 1))
    return out


def _bilinear_up(small: np.ndarray, height: int, width: int) -> np.ndarray:
    """Sample the small grid with bilinear weights. No nearest neighbour."""
    small_h, small_w, _channels = small.shape
    if small_h == height and small_w == width:
        return small
    ys = (np.arange(height, dtype=np.float32) + 0.5) * (small_h / height) - 0.5
    xs = (np.arange(width, dtype=np.float32) + 0.5) * (small_w / width) - 0.5
    y0 = np.clip(np.floor(ys).astype(np.int32), 0, small_h - 1)
    x0 = np.clip(np.floor(xs).astype(np.int32), 0, small_w - 1)
    y1 = np.clip(y0 + 1, 0, small_h - 1)
    x1 = np.clip(x0 + 1, 0, small_w - 1)
    wy = (ys - y0).astype(np.float32)[:, None, None]
    wx = (xs - x0).astype(np.float32)[None, :, None]
    top = small[y0][:, x0] * (1.0 - wx) + small[y0][:, x1] * wx
    bot = small[y1][:, x0] * (1.0 - wx) + small[y1][:, x1] * wx
    return top * (1.0 - wy) + bot * wy


def blur_premul(image: np.ndarray, factor: int) -> np.ndarray:
    """Area downscale, then bilinear upscale, in premultiplied space.

    Built once at bake time. A frame only fades between this and the sharp plate.
    Repeating pixels (nearest) leaves flat blocks, so this path never does that.
    """
    factor = max(2, int(factor))
    height, width, _channels = image.shape
    small_h = max(1, height // factor)
    small_w = max(1, width // factor)
    small = _area_down(image, small_h, small_w)
    up = _bilinear_up(small, height, width)
    return np.clip(up + 0.5, 0, 255).astype(np.uint8)


def flatten_on_black(image: np.ndarray) -> np.ndarray:
    """Visible color over black, opaque, so a grab can be compared."""
    out = np.zeros_like(image)
    out[..., 0] = image[..., 0]
    out[..., 1] = image[..., 1]
    out[..., 2] = image[..., 2]
    out[..., 3] = 255
    return out
