"""Nebula face, v2.3, drawn with numpy. Baked once, not every frame.

The numbers are the approved face: cheek 0.95, crown pulled in, side volume
pulled in, head a little taller, inner glow on, neck on. Seeds stay fixed so
she looks the same every launch.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image

# Tall dock: head in the upper part, hair and wisps running down to a soft bottom fade.
VIEW = (-0.80, 0.80, -0.72, 1.22)

CHEEK = 0.95
CROWN = 1.0
SIDE = 1.0
SIDE_RESTORE = 1.0
VSTRETCH = 1.04
VY = -0.05
GLOW_P = {"c0": 0.14, "c1": 0.66, "edge": 0.34, "base": 0.55, "core": 0.26, "fil": 0.19}

TOP, WID = -0.44, 0.03
# Hair keeps the v2.3 head. Skin uses a slightly longer, less round chin.
HAIR_CHIN = 0.305
CHIN = 0.312
JAW_P, JAW_Q = 1.85, 0.70
HALF = 0.255
EYE_Y, EYE_X, EYE_HW = 0.014, 0.114, 0.059
EYE_SCALE = 0.91
BROW_Y, BROW_X, BROW_HW = -0.066, 0.118, 0.062
NOSE_Y = 0.121
MOUTH_Y, MOUTH_HW = 0.190, 0.047
PIVOT = np.array([0.0, 0.36], dtype=np.float64)


def _hex(value: str) -> np.ndarray:
    raw = value.lstrip("#")
    return np.array([int(raw[i : i + 2], 16) / 255.0 for i in (0, 2, 4)], dtype=np.float64)


PAL = {
    "face": _hex("#f1eaff"),
    "hair0": _hex("#a58aff"),
    "hair1": _hex("#e9a6d8"),
    "ring": _hex("#8050b0"),
    "blush": _hex("#f5a3c7"),
    "star": np.array([1.0, 1.0, 1.0]),
    "wisp": _hex("#4a3480"),
    "white": np.array([1.0, 1.0, 1.0]),
    "lip": _hex("#d77aa8"),
    "teeth": _hex("#f4eeff"),
    "shine": _hex("#ffd6ef"),
    "iris0": _hex("#8a6ae0"),
    "iris1": _hex("#efc4ff"),
    "glow": _hex("#fff0fb"),
}


def smooth(value: np.ndarray | float) -> np.ndarray | float:
    clipped = np.clip(value, 0.0, 1.0)
    return clipped * clipped * (3.0 - 2.0 * clipped)


def lerp(a: np.ndarray, b: np.ndarray, t: np.ndarray | float) -> np.ndarray:
    mix = np.asarray(t, dtype=np.float64)[..., None]
    return a * (1.0 - mix) + b * mix


def _upper_half(y: np.ndarray) -> np.ndarray:
    up_u = np.clip((WID - y) / (WID - TOP), 0.0, 1.0)
    return HALF * np.sqrt(np.clip(1.0 - up_u**2, 0.0, 1.0))


def half_w(y: np.ndarray | float) -> np.ndarray:
    """v2.3 head shape. The hair uses this, not the aged chin."""
    y = np.asarray(y, dtype=np.float64)
    down_u = np.clip((y - WID) / (HAIR_CHIN - WID), 0.0, 1.0)
    lower = HALF * np.clip(1.0 - down_u**2.15, 0.0, 1.0) ** 0.64
    width = np.where(y < WID, _upper_half(y), lower)
    return np.where((y > TOP) & (y < HAIR_CHIN), width, 0.0)


def face_w(y: np.ndarray | float) -> np.ndarray:
    """Skin outline: a touch longer, and narrower toward the chin."""
    y = np.asarray(y, dtype=np.float64)
    down_u = np.clip((y - WID) / (CHIN - WID), 0.0, 1.0)
    lower = HALF * np.clip(1.0 - down_u**JAW_P, 0.0, 1.0) ** JAW_Q
    width = np.where(y < WID, _upper_half(y), lower)
    width = np.where((y > TOP) & (y < CHIN), width, 0.0)
    return width * (1.0 - (1.0 - CHEEK) * smooth((y + 0.20) / 0.20))


def raster_size(width: int) -> tuple[int, int]:
    """Pixel size for a bake of this width. Height follows the tall view."""
    x0, x1, y0, y1 = VIEW
    height = max(1, round(width * (y1 - y0) / (x1 - x0)))
    return int(width), height


def side_weight(sin_up: np.ndarray) -> np.ndarray:
    return np.exp(-(((sin_up + 0.50) / 0.34) ** 2))


def top_weight(sin_up: np.ndarray) -> np.ndarray:
    return np.clip(-sin_up, 0.0, 1.0) ** 2


def inside_face(points: np.ndarray, scale: float = 1.0) -> np.ndarray:
    return np.abs(points[:, 0]) < half_w(points[:, 1]) * scale


def stretch_y(y: np.ndarray | float) -> np.ndarray | float:
    return VY + (y - VY) * VSTRETCH


def unstretch_y(y: np.ndarray | float) -> np.ndarray | float:
    return VY + (y - VY) / VSTRETCH


class Noise:
    """Smooth value noise on a square, plus a curl field for the gas."""

    def __init__(self, seed: int = 0, res: int = 384, limit: float = 1.6) -> None:
        rng = np.random.default_rng(seed)
        field = np.zeros((res, res), dtype=np.float32)
        for cells, amp in ((6, 1.0), (12, 0.5), (24, 0.25)):
            small = rng.random((cells, cells)).astype(np.float32)
            image = Image.fromarray(small, mode="F").resize((res, res), Image.Resampling.BICUBIC)
            field += amp * (np.asarray(image, dtype=np.float32) - 0.5)
        self.field = field
        self.res = res
        self.limit = limit
        grad_y, grad_x = np.gradient(field)
        curl_x, curl_y = grad_y, -grad_x
        peak = float(np.abs(np.stack([curl_x, curl_y])).max()) or 1.0
        self.curl_x = curl_x / peak
        self.curl_y = curl_y / peak

    def _sample(self, grid: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        span = 2.0 * self.limit
        u = np.clip((x + self.limit) / span * (self.res - 1), 0.0, self.res - 1.001)
        v = np.clip((y + self.limit) / span * (self.res - 1), 0.0, self.res - 1.001)
        i = u.astype(np.int32)
        j = v.astype(np.int32)
        fu = u - i
        fv = v - j
        return (
            grid[j, i] * (1.0 - fu) * (1.0 - fv)
            + grid[j, i + 1] * fu * (1.0 - fv)
            + grid[j + 1, i] * (1.0 - fu) * fv
            + grid[j + 1, i + 1] * fu * fv
        )

    def value(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        return self._sample(
            self.field, np.asarray(x, dtype=np.float32), np.asarray(y, dtype=np.float32)
        )

    def curl(self, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        xx = np.asarray(x, dtype=np.float32)
        yy = np.asarray(y, dtype=np.float32)
        return self._sample(self.curl_x, xx, yy), self._sample(self.curl_y, xx, yy)

    def advect(self, points: np.ndarray, steps: int, step: float, amp: float = 1.0) -> np.ndarray:
        x = points[:, 0].astype(np.float32).copy()
        y = points[:, 1].astype(np.float32).copy()
        gain = np.float32(amp)
        for _ in range(steps):
            cx, cy = self.curl(x, y)
            x = x + cx * np.float32(step) * gain
            y = y + cy * np.float32(step) * gain
        return np.stack([x, y], 1).astype(np.float64)


def blur(image: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian blur through a Fourier multiply. Sigma is in pixels."""
    if sigma <= 0.35:
        return image
    if image.ndim == 2:
        return _blur_plane(image, sigma)
    planes = [_blur_plane(image[..., channel], sigma) for channel in range(image.shape[-1])]
    return np.stack(planes, -1)


def _blur_plane(plane: np.ndarray, sigma: float) -> np.ndarray:
    height, width = plane.shape
    freq_y = np.fft.fftfreq(height)[:, None]
    freq_x = np.fft.rfftfreq(width)[None, :]
    kernel = np.exp(-2.0 * (math.pi * sigma) ** 2 * (freq_x**2 + freq_y**2))
    spec = np.fft.rfft2(plane) * kernel
    return np.fft.irfft2(spec, s=(height, width)).real


class Canvas:
    """Additive light and a shade buffer. Particle weights keep the same brightness at any size."""

    def __init__(
        self, width: int, height: int, view: tuple[float, float, float, float] = VIEW
    ) -> None:
        self.w = int(width)
        self.h = int(height)
        self.view = view
        self.layers: dict[float, np.ndarray] = {}
        self.shades: dict[float, np.ndarray] = {}
        x0, x1, y0, y1 = view
        xs = x0 + (np.arange(self.w, dtype=np.float32) + 0.5) * ((x1 - x0) / self.w)
        ys = y0 + (np.arange(self.h, dtype=np.float32) + 0.5) * ((y1 - y0) / self.h)
        self.x = xs[None, :].repeat(self.h, 0)
        self.y = ys[:, None].repeat(self.w, 1)
        self.px = (x1 - x0) / self.w
        self.density = (self.w / (x1 - x0) / 640.0) ** 2

    def buf(self, sigma: float) -> np.ndarray:
        key = round(float(sigma), 3)
        layer = self.layers.get(key)
        if layer is None:
            layer = np.zeros((self.h, self.w, 3), dtype=np.float32)
            self.layers[key] = layer
        return layer

    def shade_buf(self, sigma: float) -> np.ndarray:
        key = round(float(sigma), 3)
        layer = self.shades.get(key)
        if layer is None:
            layer = np.zeros((self.h, self.w), dtype=np.float32)
            self.shades[key] = layer
        return layer

    def to_px(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        x0, x1, y0, y1 = self.view
        px = (points[:, 0] - x0) / (x1 - x0) * self.w
        py = (points[:, 1] - y0) / (y1 - y0) * self.h
        return px, py

    def splat(
        self, points: np.ndarray, weight: np.ndarray | float, color, sigma: float = 0.8
    ) -> None:
        if len(points) == 0:
            return
        px, py = self.to_px(points)
        weights = np.broadcast_to(np.asarray(weight, dtype=np.float64), px.shape).copy()
        weights *= self.density
        tint = np.asarray(color, dtype=np.float64)
        if tint.ndim == 1:
            tint = np.broadcast_to(tint, (len(px), 3)).copy()
        keep = (px >= 0.0) & (px < self.w - 1) & (py >= 0.0) & (py < self.h - 1)
        if not np.any(keep):
            return
        px, py, weights, tint = px[keep], py[keep], weights[keep], tint[keep]
        i = px.astype(np.int32)
        j = py.astype(np.int32)
        fx = px - i
        fy = py - j
        target = self.buf(sigma)
        count = self.w * self.h
        for di, dj, share in (
            (0, 0, (1.0 - fx) * (1.0 - fy)),
            (1, 0, fx * (1.0 - fy)),
            (0, 1, (1.0 - fx) * fy),
            (1, 1, fx * fy),
        ):
            index = (j + dj) * self.w + (i + di)
            for channel in range(3):
                added = np.bincount(index, weights * share * tint[:, channel], minlength=count)
                target[..., channel] += added.reshape(self.h, self.w).astype(np.float32)

    def splat_shade(
        self, points: np.ndarray, weight: np.ndarray | float, sigma: float = 0.8
    ) -> None:
        if len(points) == 0:
            return
        px, py = self.to_px(points)
        weights = np.broadcast_to(
            np.asarray(weight, dtype=np.float64) * self.density, px.shape
        ).copy()
        keep = (px >= 0.0) & (px < self.w - 1) & (py >= 0.0) & (py < self.h - 1)
        if not np.any(keep):
            return
        px, py, weights = px[keep], py[keep], weights[keep]
        i = px.astype(np.int32)
        j = py.astype(np.int32)
        fx = px - i
        fy = py - j
        target = self.shade_buf(sigma)
        count = self.w * self.h
        for di, dj, share in (
            (0, 0, (1.0 - fx) * (1.0 - fy)),
            (1, 0, fx * (1.0 - fy)),
            (0, 1, (1.0 - fx) * fy),
            (1, 1, fx * fy),
        ):
            index = (j + dj) * self.w + (i + di)
            added = np.bincount(index, weights * share, minlength=count)
            target += added.reshape(self.h, self.w).astype(np.float32)

    def light(self, field: np.ndarray, color: np.ndarray) -> None:
        self.buf(0)[:] += field[..., None].astype(np.float32) * np.asarray(color, dtype=np.float32)

    def shade(self, field: np.ndarray) -> None:
        self.shade_buf(0)[:] += field.astype(np.float32)

    def base_light(self) -> tuple[np.ndarray, np.ndarray]:
        """Light with shade applied, before bloom and the film curve."""
        acc = np.zeros((self.h, self.w, 3), dtype=np.float32)
        for sigma, layer in self.layers.items():
            scale = (2.0 * math.pi * sigma * sigma) if sigma > 0.5 else 1.0
            acc += blur(layer, sigma).astype(np.float32) * np.float32(scale)
        shade = np.zeros((self.h, self.w), dtype=np.float32)
        tint = np.array([1.0, 1.18, 0.78], dtype=np.float32)
        for sigma, layer in self.shades.items():
            if sigma > 0.5:
                blurred = blur(np.repeat(layer[..., None], 3, -1), sigma)[..., 0]
                shade += blurred.astype(np.float32) * np.float32(2.0 * math.pi * sigma * sigma)
            else:
                shade += layer
        dark = np.exp(-np.clip(shade, 0.0, None)[..., None] * tint)
        return (acc * dark).astype(np.float32), dark

    def lit(self, exposure: float = 1.0) -> np.ndarray:
        colored, dark = self.base_light()
        return film(colored, exposure, self.w, dark)


def film(
    colored: np.ndarray, exposure: float, width: int, dark: np.ndarray | None = None
) -> np.ndarray:
    """Bloom, then the film curve. Bloom stays in the layer so the halo is not clipped later."""
    scale = max(0.25, width / 1024.0)
    bloomed = colored.copy()
    for sigma, amount in ((6.0 * scale, 0.35), (22.0 * scale, 0.28), (55.0 * scale, 0.20)):
        bloomed += np.float32(amount) * blur(colored, sigma).astype(np.float32)
    if dark is None:
        bloomed *= np.float32(exposure)
    else:
        bloomed *= np.float32(exposure) * (dark**0.6)
    return np.clip(1.0 - np.exp(-np.clip(bloomed, 0.0, None)), 0.0, 1.0)


def gasify(points: np.ndarray, copies: int, jitter, rng: np.random.Generator) -> np.ndarray:
    base = np.repeat(points, copies, 0)
    spread = np.repeat(
        np.broadcast_to(np.asarray(jitter, dtype=np.float64), (len(points),)), copies
    )
    return base + rng.normal(0.0, 1.0, base.shape) * spread[:, None]


def sparkle(
    canvas: Canvas, center: np.ndarray, size: float, color: np.ndarray, strength: float
) -> None:
    canvas.light(_blob(canvas, center[0], center[1], size * 0.12) * (2.2 * strength), color)
    canvas.light(_blob(canvas, center[0], center[1], size * 0.45) * (0.35 * strength), color)
    line = np.linspace(-size, size, 480)
    fade = np.exp(-np.abs(line) / (size * 0.22))
    for angle, stretch in (
        (0.0, 1.0),
        (math.pi / 2.0, 1.0),
        (math.pi / 4.0, 0.35),
        (-math.pi / 4.0, 0.35),
    ):
        pts = np.stack(
            [
                center[0] + line * math.cos(angle) * stretch,
                center[1] + line * math.sin(angle) * stretch,
            ],
            1,
        )
        canvas.splat(pts, fade * 0.5 * strength, color, 0.9)


def _blob(canvas: Canvas, cx: float, cy: float, radius: float) -> np.ndarray:
    return np.exp(
        -((canvas.x - cx) ** 2 + (canvas.y - cy) ** 2) / (2.0 * max(radius, 1e-4) ** 2)
    ).astype(np.float32)


def orbit_ring(canvas: Canvas, noise: Noise, strength: float = 0.85) -> None:
    rng = np.random.default_rng(5)
    count = max(4000, int(42000 * min(1.0, canvas.w / 640.0)))
    angle = rng.random(count) * (2.0 * math.pi)
    nv = noise.value(np.cos(angle) * 1.3 + 0.3, np.sin(angle) * 1.3)
    scale = 1.0 + rng.normal(0.0, 0.006, count) + nv * 0.012
    rx, ry, tilt = 0.72, 0.185, -0.16
    ex = np.cos(angle) * rx * scale
    ey = np.sin(angle) * ry * scale
    x = ex * math.cos(tilt) - ey * math.sin(tilt)
    y = 0.34 + ex * math.sin(tilt) + ey * math.cos(tilt)
    bright = (0.35 + 0.9 * np.clip(nv + 0.3, 0.0, 1.0)) * strength
    back = np.sin(angle) < 0.0
    bright = np.where(back & (np.abs(x) < 0.44), bright * 0.08, bright)
    bright = np.where(back, bright * 0.6, bright)
    points = np.stack([x, y], 1)
    gain = 42000 / count
    canvas.splat(points, 0.020 * bright * gain, lerp(PAL["ring"], PAL["face"], 0.35), 1.1)
    canvas.splat(points[::3], 0.034 * bright[::3] * gain, PAL["ring"], 4.2)


def _bezier(p0, p1, p2, p3, count: int) -> np.ndarray:
    t = np.linspace(0.0, 1.0, count)[:, None]
    return (1.0 - t) ** 3 * p0 + 3 * (1.0 - t) ** 2 * t * p1 + 3 * (1.0 - t) * t**2 * p2 + t**3 * p3


def budget(size: int) -> dict[str, int]:
    """Fewer particles on a small bake. Weights are scaled back up so she stays as bright."""
    span = max(0.34, min(1.0, size / 680.0))
    area = max(0.16, span * span)
    return {
        "span": span,
        "area": area,
        "strands": max(120, int(820 * span)),
        "cap": max(80, int(520 * span)),
        "fringe": max(40, int(210 * span)),
        "sweep": max(24, int(120 * span)),
        "locks": max(10, int(36 * span)),
        "gas": max(6000, int(80000 * area)),
        "wisp": max(5000, int(60000 * area)),
        "neck": max(2500, int(16000 * area)),
        "ring_note": 1,
    }


def build_hair(counts: dict[str, int]) -> tuple[list, list]:
    rng = np.random.default_rng(11)
    part_rng = np.random.default_rng(909)
    flow = Noise(seed=44, res=256, limit=1.6)
    strands_n = counts["strands"]
    center = np.array([0.0, -0.08])
    theta = rng.uniform(-math.pi + 0.10, -0.10, strands_n)
    radius0 = rng.uniform(0.355, 0.43, strands_n)
    radius = (
        radius0
        - CROWN * 0.065 * top_weight(np.sin(theta))
        - SIDE * 0.060 * side_weight(np.sin(theta))
    )
    pos = center + radius[:, None] * np.stack([np.cos(theta), np.sin(theta)], 1)
    side = np.where(np.cos(theta) >= 0.0, 1.0, -1.0)
    restore = SIDE * SIDE_RESTORE * 0.060 * side_weight(np.sin(theta)) / 0.30
    steps = rng.integers(200, 340, strands_n)
    ds = 0.008
    limit = int(steps.max())
    path = np.zeros((limit, strands_n, 2), dtype=np.float64)
    for step in range(limit):
        delta = pos - center
        dist = np.hypot(delta[:, 0], delta[:, 1]) + 1e-6
        unit = delta / dist[:, None]
        tangent = np.stack([-unit[:, 1], unit[:, 0]], 1)
        flip = (tangent[:, 0] * side + tangent[:, 1]) < 0.0
        tangent[flip] *= -1.0
        fall = smooth((pos[:, 1] - (center[1] + 0.02)) / 0.30)[:, None]
        flare = 0.22 + 1.85 * smooth((pos[:, 1] - 0.22) / 0.85)
        down = np.stack([side * flare, np.ones(strands_n)], 1)
        down /= np.hypot(down[:, 0], down[:, 1])[:, None]
        target = (
            radius0
            - CROWN * 0.065 * top_weight(unit[:, 1])
            - SIDE * 0.060 * side_weight(unit[:, 1])
        )
        velocity = (
            (1.0 - fall) * tangent
            + fall * down
            + (1.0 - fall) * ((target - dist) * 5.0)[:, None] * unit
        )
        inside = inside_face(pos, 1.13) | (
            (np.abs(pos[:, 0]) < 0.10) & (pos[:, 1] > 0.2) & (pos[:, 1] < 0.6)
        )
        velocity[inside, 0] += side[inside] * 1.5
        band = smooth((pos[:, 1] + 0.04) / 0.05) * (1.0 - smooth((pos[:, 1] - 0.22) / 0.06))
        velocity[:, 0] += side * restore * band
        # Long locks fall almost straight. Curl stays small and slow past the shoulders.
        fall_amp = smooth((pos[:, 1] - 0.02) / 0.70)
        amp = (0.04 + 0.18 * float(smooth((step * ds - 1.2) / 1.8))) * (1.0 - 0.9 * fall_amp)
        cx, cy = flow.curl(pos[:, 0] * 0.28, pos[:, 1] * 0.22)
        norm = np.hypot(velocity[:, 0], velocity[:, 1])[:, None] + 1e-6
        velocity = velocity / norm
        curl = np.stack([np.asarray(cx).reshape(-1), np.asarray(cy).reshape(-1)], 1)
        velocity = velocity + np.asarray(amp).reshape(-1, 1) * curl
        velocity /= np.hypot(velocity[:, 0], velocity[:, 1])[:, None] + 1e-6
        pos = pos + velocity * ds
        path[step] = pos
    strands = []
    for index in range(strands_n):
        count = int(steps[index])
        pts = path[:count, index]
        arc = np.arange(count) * ds
        strands.append((pts, arc))

    bangs: list[np.ndarray] = []
    part = np.array([-0.075, -0.452])
    for index in range(counts["cap"]):
        right = index % 3 != 0
        depth = float(rng.random() ** 1.25)
        rx = 0.238 + 0.20 * depth
        ry = 0.255 + 0.215 * depth
        if right:
            end = -0.04 - 0.40 * float(rng.random())
        else:
            end = -math.pi + 0.04 + 0.40 * float(rng.random())
        start = -math.pi / 2.0 + (0.16 if right else -0.10) + float(rng.normal(0.0, 0.04))
        along = np.linspace(0.0, 1.0, 120)
        angle = start + (end - start) * (1.0 - (1.0 - along) ** 1.5)
        jitter = float(rng.normal(0.0, 0.006))
        tuck = np.clip(
            CROWN * 0.42 * top_weight(np.sin(angle)) + SIDE * 0.45 * side_weight(np.sin(angle)),
            0.0,
            0.9,
        )
        rx_e = rx - tuck * (rx - 0.238)
        ry_e = ry - tuck * (ry - 0.255)
        pts = np.stack(
            [np.cos(angle) * (rx_e + jitter), -0.06 + np.sin(angle) * (ry_e + jitter)], 1
        )
        blend = smooth(along / (0.30 + 0.15 * (1.0 - depth)))[:, None]
        jit0 = rng.normal(0.0, 0.012, 2) * np.array([1.8, 1.0])
        jit0 = jit0 + np.array([0.0, 0.012 + 0.02 * float(part_rng.random())])
        pts = part + jit0 + (pts - part) * blend
        tail_n = 40
        tail = pts[-1] + np.stack([np.zeros(tail_n), np.linspace(0.0, 0.26, tail_n)], 1)
        tail[:, 0] += math.copysign(1.0, math.cos(end)) * np.linspace(
            0.0, 0.02 + 0.03 * depth, tail_n
        )
        bangs.append(np.concatenate([pts, tail]))
    for _ in range(counts["fringe"]):
        depth = float(rng.random())
        across = float(np.clip(depth + rng.normal(0.0, 0.15), 0.0, 1.0))
        offset = rng.normal(0.0, 0.005, 2)
        origin = np.array(
            [-0.075 + 0.012 * depth + float(rng.normal(0.0, 0.006)), -0.445 + 0.15 * depth]
        )
        bangs.append(
            _bezier(
                origin + offset,
                origin + np.array([0.035, 0.085]) + offset,
                np.array([0.12 + 0.06 * across, -0.25 + 0.135 * across]) + offset,
                np.array([0.245 + 0.03 * across, -0.10 + 0.17 * across]) + offset,
                110,
            )
        )
    for _ in range(counts["sweep"]):
        depth = float(rng.random())
        across = float(np.clip(depth + rng.normal(0.0, 0.15), 0.0, 1.0))
        offset = rng.normal(0.0, 0.005, 2)
        origin = np.array(
            [-0.082 - 0.01 * depth + float(rng.normal(0.0, 0.006)), -0.445 + 0.14 * depth]
        )
        bangs.append(
            _bezier(
                origin + offset,
                origin + np.array([-0.025, 0.075]) + offset,
                np.array([-0.20 - 0.01 * across, -0.31 + 0.10 * across]) + offset,
                np.array([-0.252 - 0.01 * across, -0.15 + 0.12 * across]) + offset,
                100,
            )
        )
    for sign in (-1.0, 1.0):
        for _ in range(counts["locks"]):
            offset = rng.normal(0.0, 0.009, 2)
            depth = float(rng.uniform(0.0, 1.0))
            bangs.append(
                _bezier(
                    np.array([sign * 0.232, -0.22]) + offset,
                    np.array([sign * 0.272, -0.04]) + offset,
                    np.array([sign * (0.262 + 0.02 * depth), 0.18]) + offset,
                    np.array([sign * (0.48 + 0.22 * depth), 1.05 + 0.16 * depth]) + offset,
                    100,
                )
            )
    return strands, bangs


def hair_particles(strands: list, bangs: list, boost: float) -> dict:
    rng = np.random.default_rng(12)
    parts_p, parts_w, parts_c, parts_s, parts_f = [], [], [], [], []
    for pts, arc in strands:
        parts_p.append(pts)
        parts_s.append(arc)
        parts_f.append(np.zeros(len(pts), dtype=bool))
        parts_w.append(0.042 * np.exp(-arc / 1.6) * smooth(arc / 0.06 + 0.2) * boost)
        parts_c.append(np.clip(arc / 1.15, 0.0, 1.0))
    for pts in bangs:
        count = len(pts)
        arc = np.linspace(0.0, 0.5, count)
        parts_p.append(pts)
        parts_s.append(arc * 0.3)
        parts_f.append(np.ones(count, dtype=bool))
        weight = (
            0.034
            * np.ones(count)
            * smooth((0.5 - arc) / 0.18 + 0.1)
            * (0.05 + 0.95 * smooth(arc / 0.26))
        )
        parts_w.append(weight * boost)
        parts_c.append(arc * 0.8)
    points = np.concatenate(parts_p)
    weight = np.concatenate(parts_w)
    color = np.concatenate(parts_c)
    arc = np.concatenate(parts_s)
    front = np.concatenate(parts_f)
    jitter = 0.0012 + 0.03 * smooth((arc - 0.15) / 1.0)
    jitter = np.where(front, 0.0016, jitter)
    copies = 2
    gassy = gasify(points, copies, jitter, rng)
    return {
        "points": points,
        "weight": weight,
        "color": color,
        "arc": arc,
        "front": front,
        "gassy": gassy,
        "gassy_arc": np.repeat(arc, copies),
        "gassy_w": np.repeat(weight, copies) / copies * 2.0,
        "gassy_c": np.repeat(color, copies),
        "gassy_front": np.repeat(front, copies),
        "spark": rng.random(len(points)) < 0.012,
        "spark_jit": rng.normal(0.0, 0.01, (len(points), 2)),
    }


def face_gas(noise: Noise, count: int, boost: float) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(13)
    raw = np.stack(
        [rng.uniform(-HALF, HALF, count * 3), rng.uniform(TOP, CHIN, count * 3)],
        1,
    )
    keep = np.abs(raw[:, 0]) < face_w(raw[:, 1]) * 0.98
    pts = raw[keep][:count]
    if len(pts) < 16:
        pts = raw[:count]
    depth = np.abs(pts[:, 0]) / np.maximum(face_w(pts[:, 1]), 1e-4)
    weight = 0.0016 * (1.0 - 0.5 * depth**2) * smooth((pts[:, 1] + 0.33) / 0.1) * boost
    return noise.advect(pts, 3, 0.003), weight


class Rig:
    """One built face. Drawing a layer does not change the next launch."""

    def __init__(self, size: int) -> None:
        counts = budget(size)
        self.noise = Noise(seed=21, res=320 if size < 420 else 384)
        strands, bangs = build_hair(counts)
        boost = 1.0 / counts["span"]
        self.hair = hair_particles(strands, bangs, boost)
        area_boost = 1.0 / counts["area"]
        self.gas, self.gas_w = face_gas(self.noise, counts["gas"], area_boost)
        rng = np.random.default_rng(77)
        self.dust = rng.random(len(self.gas)) < 0.004
        neck_n = counts["neck"]
        y0 = rng.uniform(0.28, 0.62, neck_n)
        x0 = rng.normal(0.0, 0.05, neck_n) * (1.0 + 2.2 * np.clip(y0 - 0.40, 0.0, 1.0))
        self.neck = self.noise.advect(np.stack([x0, y0], 1), 6, 0.006)
        self.neck_w = 0.0018 * (1.0 - smooth((y0 - 0.36) / 0.30)) * smooth((y0 - 0.27) / 0.06)
        self.neck_w *= area_boost
        self.neck_c = np.clip((y0 - 0.3) / 0.4, 0.0, 1.0)
        wisp_n = counts["wisp"]
        cloud = rng.normal(0.0, 0.9, (wisp_n, 2))
        cloud[:, 1] += rng.random(wisp_n) * 0.75
        self.wisp = self.noise.advect(cloud, 5, 0.005)
        tone = np.clip(
            self.noise.value(self.wisp[:, 0] * 0.8, self.wisp[:, 1] * 0.8) * 3.0 + 0.2, 0.0, 1.0
        )
        self.wisp_w = 0.0048 * tone * area_boost
        self.wisp_c = lerp(PAL["wisp"], PAL["hair1"], tone * 0.4)
        self.star = self.world(np.array([[0.232, -0.372]]))[0]

    def world(self, points: np.ndarray) -> np.ndarray:
        y = stretch_y(points[:, 1])
        x = points[:, 0]
        stacked = np.stack([x, np.asarray(y, dtype=np.float64)], 1)
        return stacked

    def local_grids(self, canvas: Canvas) -> tuple[np.ndarray, np.ndarray]:
        return canvas.x, unstretch_y(canvas.y)


def edge_window(height: int, width: int, margin: float = 0.08, bottom: float = 0.20) -> np.ndarray:
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    x = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]
    x_fade = smooth(x / margin) * smooth((1.0 - x) / margin)
    y_fade = smooth(y / margin) * smooth((1.0 - y) / bottom)
    return (x_fade * y_fade).astype(np.float32)


def premul(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    window = edge_window(rgb.shape[0], rgb.shape[1])
    cover = np.clip(alpha, 0.0, 1.0).astype(np.float32) * window
    out = np.empty((rgb.shape[0], rgb.shape[1], 4), dtype=np.uint8)
    straight = np.clip(rgb, 0.0, 1.0).astype(np.float32)
    out[..., 0] = np.clip(straight[..., 0] * cover * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out[..., 1] = np.clip(straight[..., 1] * cover * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out[..., 2] = np.clip(straight[..., 2] * cover * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(cover * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return out


def premul_light(rgb: np.ndarray) -> np.ndarray:
    """Light to add. The color is not multiplied by a second darkness mask.

    Hair bands were going dark because each band's brightness was used as
    alpha and then multiplied into the color again. Plus-compositing that
    premultiplied color left streaks. Alpha here only marks coverage.
    """
    window = edge_window(rgb.shape[0], rgb.shape[1])
    straight = np.clip(rgb, 0.0, 1.0).astype(np.float32) * window[..., None]
    alpha = np.clip(straight.max(axis=-1) * 3.2, 0.0, 1.0)
    out = np.empty((*straight.shape[:2], 4), dtype=np.uint8)
    out[..., 0] = np.clip(straight[..., 0] * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out[..., 1] = np.clip(straight[..., 1] * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out[..., 2] = np.clip(straight[..., 2] * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(alpha * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return out


def _band_weights(arc: np.ndarray) -> dict[str, np.ndarray]:
    """Soft root, middle and tip weights. They add up to 1."""
    u = np.clip(arc / 1.7, 0.0, 1.0)
    root = np.clip(1.0 - u / 0.42, 0.0, 1.0)
    tip = np.clip((u - 0.52) / 0.48, 0.0, 1.0)
    mid = np.clip(1.0 - root - tip, 0.0, 1.0)
    return {"root": root, "mid": mid, "tip": tip}


def paint_wisps(rig: Rig, width: int) -> np.ndarray:
    width, height = raster_size(width)
    canvas = Canvas(width, height)
    canvas.splat(rig.world(rig.wisp), rig.wisp_w, rig.wisp_c, 9.0)
    return premul_light(canvas.lit(0.9))


def _splat_hair(canvas: Canvas, rig: Rig, mask: np.ndarray, weight: np.ndarray) -> None:
    hair = rig.hair
    if not np.any(mask):
        return
    pts = rig.world(hair["gassy"][mask])
    col = lerp(PAL["hair0"], PAL["hair1"], hair["gassy_c"][mask])
    canvas.splat(pts, hair["gassy_w"][mask] * weight[mask], col, 0.8)


def _splat_core(canvas: Canvas, rig: Rig, mask: np.ndarray, weight: np.ndarray) -> None:
    hair = rig.hair
    chosen = np.flatnonzero(mask)
    half = chosen[::2]
    if len(half) == 0:
        return
    pts = rig.world(hair["points"][half])
    col = lerp(PAL["hair0"], PAL["hair1"], hair["color"][half])
    canvas.splat(pts, hair["weight"][half] * weight[half] * 0.4, col, 3.2)


def _splat_sparks(canvas: Canvas, rig: Rig, mask: np.ndarray, weight: np.ndarray) -> None:
    hair = rig.hair
    sparks = mask & hair["spark"]
    if not np.any(sparks):
        return
    gain = (
        0.25
        * np.exp(-hair["color"][sparks])
        * np.clip(hair["weight"][sparks] / 0.025, 0.0, 1.0)
        * weight[sparks]
    )
    pts = rig.world(hair["points"][sparks] + hair["spark_jit"][sparks])
    col = lerp(PAL["hair0"], PAL["hair1"], 0.25 + 0.45 * hair["color"][sparks])
    canvas.splat(pts, gain, col, 0.8)


def paint_hair_layers(rig: Rig, width: int) -> dict[str, np.ndarray]:
    """One hair pass, split so the bands add back to that same picture.

    Front hair is part of the same sum. Tone-mapping it on its own and then
    adding it turned the overlap white.
    """
    width, height = raster_size(width)
    hair = rig.hair
    back_g = ~hair["gassy_front"]
    back = ~hair["front"]
    weights_g = _band_weights(hair["gassy_arc"])
    weights = _band_weights(hair["arc"])
    bases: dict[str, np.ndarray] = {}
    for name in ("root", "mid", "tip"):
        canvas = Canvas(width, height)
        _splat_hair(canvas, rig, back_g, weights_g[name])
        _splat_core(canvas, rig, back, weights[name])
        _splat_sparks(canvas, rig, back, weights[name])
        colored, _dark = canvas.base_light()
        bases[name] = colored
    front = Canvas(width, height)
    _splat_hair(front, rig, hair["gassy_front"], np.ones(hair["gassy_front"].shape))
    _splat_core(front, rig, hair["front"], np.ones(hair["front"].shape))
    _splat_sparks(front, rig, hair["front"], np.ones(hair["front"].shape))
    colored, _dark = front.base_light()
    bases["front"] = colored
    total = bases["root"] + bases["mid"] + bases["tip"] + bases["front"]
    shown = film(total, 0.58, width)
    # Crown and fringe were blowing out to white along the part. Hold them in lavender.
    peak = shown.max(axis=-1, keepdims=True)
    hot = np.clip((peak - 0.38) / 0.62, 0.0, 1.0).astype(np.float32)
    lavender = np.array([0.58, 0.46, 0.82], dtype=np.float32)
    shown = shown * (1.0 - 0.7 * hot) + lavender * peak * (0.7 * hot)
    energy = np.maximum(total.sum(axis=-1, keepdims=True), 1e-5)
    layers: dict[str, np.ndarray] = {}
    for name, part in bases.items():
        share = part.sum(axis=-1, keepdims=True) / energy
        layers[name] = premul_light(shown * share.astype(np.float32))
    return layers


def _ss(a: float, b: float, x: np.ndarray) -> np.ndarray:
    return smooth((x - a) / (b - a))


def _gauss(x, y, cx, cy, sx, sy=None) -> np.ndarray:
    sy = sx if sy is None else sy
    return np.exp(-((x - cx) ** 2 / (2 * sx * sx) + (y - cy) ** 2 / (2 * sy * sy)))


def paint_face(rig: Rig, width: int) -> np.ndarray:
    width, height = raster_size(width)
    canvas = Canvas(width, height)
    x, y = rig.local_grids(canvas)
    canvas.splat(rig.world(rig.gas), rig.gas_w, lerp(PAL["face"], PAL["hair0"], 0.3), 2.0)
    dust = rig.gas[rig.dust]
    if len(dust):
        canvas.splat(rig.world(dust), np.full(len(dust), 0.04), PAL["white"], 0.8)
    canvas.splat(rig.world(rig.neck), rig.neck_w, lerp(PAL["hair0"], PAL["hair1"], rig.neck_c), 2.0)
    _skin(canvas, rig, x, y)
    rgb = canvas.lit(1.05)
    luma = rgb.max(axis=-1)
    halo = smooth(np.clip((luma - 0.02) / 0.06, 0.0, 1.0))
    alpha = np.maximum(_skin_alpha(x, y), halo * 0.72)
    return premul(rgb, alpha)


def _skin_alpha(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    width = face_w(y)
    depth = np.abs(x) / np.maximum(width, 1e-4)
    face = smooth((1.0 - depth) / 0.18) * (width > 0) * _ss(-0.40, -0.20, y)
    neck_w = 0.09 + 0.18 * np.clip(y - 0.40, 0.0, 1.0)
    neck = smooth((neck_w - np.abs(x)) / 0.09) * _ss(0.18, 0.32, y) * (1.0 - _ss(0.32, 0.78, y))
    return np.clip(face + neck * 0.85, 0.0, 1.0).astype(np.float32)


def _skin(canvas: Canvas, rig: Rig, x: np.ndarray, y: np.ndarray) -> None:
    width = face_w(y)
    depth = np.abs(x) / np.maximum(width, 1e-4)
    inside = smooth((1.0 - depth) / 0.16) * (width > 0) * _ss(-0.36, -0.22, y)
    shape = 0.30 + 0.70 * np.clip(1.0 - depth**2, 0.0, 1.0) ** 1.4
    vert = 1.0 - 0.16 * _ss(0.05, 0.33, y)
    hi = (
        0.36 * _gauss(x, y, 0.0, -0.17, 0.08, 0.055)
        + 0.16 * _gauss(x, y, 0.0, 0.08, 0.014, 0.05)
        + 0.12 * (_gauss(x, y, 0.125, 0.06, 0.05) + _gauss(x, y, -0.125, 0.06, 0.05))
        + 0.08 * _gauss(x, y, 0.0, CHIN - 0.045, 0.03, 0.02)
    )
    tex = 0.92 + 0.16 * rig.noise.value(x * 2.5, y * 2.5)
    hairline = -0.29 + 2.6 * x**2
    skin = inside * (shape * vert + hi) * tex * _ss(hairline - 0.02, hairline + 0.06, y)
    neck_w = 0.068 + 0.16 * np.clip(y - 0.42, 0.0, 1.0)
    neck = (
        smooth((neck_w - np.abs(x)) / 0.07) * _ss(0.20, 0.30, y) * (1.0 - _ss(0.30, 0.80, y)) * 0.24
    )
    neck *= 1.0 - 0.6 * inside
    neck *= np.clip(0.55 + 0.9 * (rig.noise.value(x * 3.5, y * 2.5) + 0.12), 0.2, 1.4)
    rim = 0.16 * np.exp(-(((depth - 0.95) / 0.07) ** 2)) * (width > 0) * _ss(-0.30, -0.15, y)
    flat = np.where(width > 0, depth, 1.0)
    glow = GLOW_P
    col = lerp(PAL["face"], PAL["hair0"], np.clip(glow["c0"] + glow["c1"] * flat**1.8, 0.0, 1.0))
    col = col * 0.78 + PAL["blush"] * 0.22
    core = _gauss(x, y, 0.0, 0.03, 0.12, 0.15)
    ridge = np.clip(1.0 - np.abs(rig.noise.value(x * 3.2 + 1.3, y * 3.2) * 6.0), 0.0, 1.0) ** 3
    edge = 1.0 - glow["edge"] * np.clip(flat, 0.0, 1.0) ** 2
    canvas.buf(0)[:] += (glow["base"] * skin * edge)[..., None].astype(np.float32) * col.astype(
        np.float32
    )
    canvas.light((inside * glow["core"] * core).astype(np.float32), PAL["glow"])
    filament = inside * glow["fil"] * ridge * (0.5 + 0.5 * core)
    canvas.light(filament.astype(np.float32), lerp(PAL["hair0"], PAL["hair1"], 0.4))
    canvas.buf(0)[:] += (0.50 * neck)[..., None].astype(np.float32) * PAL["hair0"].astype(
        np.float32
    )
    canvas.light(rim.astype(np.float32), lerp(PAL["hair0"], PAL["face"], 0.35))
    canvas.shade(
        (
            0.10
            * _ss(0.30, 0.34, y)
            * (1.0 - _ss(0.34, 0.40, y))
            * smooth((0.09 - np.abs(x)) / 0.03)
        ).astype(np.float32)
    )
    for sign in (-1.0, 1.0):
        canvas.light(
            (0.36 * _gauss(x, y, sign * 0.150, 0.100, 0.042, 0.030)).astype(np.float32),
            PAL["blush"],
        )
    _cheekbones(canvas, x, y, inside, depth, width)
    _brows(canvas, x, y)
    _nose(canvas, x, y)


def _cheekbones(
    canvas: Canvas,
    x: np.ndarray,
    y: np.ndarray,
    inside: np.ndarray,
    depth: np.ndarray,
    width: np.ndarray,
) -> None:
    """A faint cheekbone, a soft hollow under it, and a little jaw and chin light."""
    bone = lerp(PAL["face"], PAL["white"], 0.3)
    for sign in (-1.0, 1.0):
        along = (x - sign * 0.168) * 0.94 + sign * (y - 0.050) * 0.34
        across = (y - 0.050) * 0.94 - sign * (x - sign * 0.168) * 0.34
        highlight = np.exp(-((along / 0.040) ** 2) - ((across / 0.0135) ** 2))
        canvas.light((0.075 * highlight * inside).astype(np.float32), bone)
        canvas.shade(
            (0.085 * _gauss(x, y, sign * 0.182, 0.128, 0.030, 0.024) * inside).astype(np.float32)
        )
    jaw = np.exp(-(((depth - 0.86) / 0.07) ** 2)) * _ss(0.09, 0.19, y) * (1.0 - _ss(0.27, 0.31, y))
    canvas.shade((0.07 * jaw * (width > 0)).astype(np.float32))
    canvas.light(
        (0.05 * _gauss(x, y, 0.0, CHIN - 0.040, 0.020, 0.012) * inside).astype(np.float32),
        PAL["face"],
    )


def _brows(canvas: Canvas, x: np.ndarray, y: np.ndarray) -> None:
    for sign in (-1.0, 1.0):
        u = (x * sign - BROW_X) / BROW_HW
        curve = BROW_Y - 0.013 * (1.0 - ((u - 0.15) / 1.15) ** 2) + 0.003 * u
        thick = 0.0038 * (1.0 - 0.55 * _ss(-0.6, 1.0, u))
        field = np.exp(-(((y - curve) / thick) ** 2)) * smooth((1.0 - np.abs(u)) / 0.22)
        canvas.shade((0.26 * field).astype(np.float32))
        canvas.light((0.08 * field).astype(np.float32), PAL["hair0"])


def _nose(canvas: Canvas, x: np.ndarray, y: np.ndarray) -> None:
    canvas.light((0.22 * _gauss(x, y, 0.0, NOSE_Y - 0.010, 0.010)).astype(np.float32), PAL["face"])
    bridge = NOSE_Y + 0.008 + 0.006 * (x / 0.02) ** 2
    canvas.shade(
        (
            0.30 * np.exp(-(((y - bridge) / 0.0032) ** 2)) * smooth((0.022 - np.abs(x)) / 0.010)
        ).astype(np.float32)
    )
    for sign in (-1.0, 1.0):
        canvas.shade(
            (0.45 * _gauss(x, y, sign * 0.0115, NOSE_Y + 0.008, 0.0036, 0.0026)).astype(np.float32)
        )


def paint_eyes(rig: Rig, width: int, blink: float, gaze: tuple[float, float]) -> np.ndarray:
    width, height = raster_size(width)
    canvas = Canvas(width, height)
    x, y = rig.local_grids(canvas)
    alpha = np.zeros((height, width), dtype=np.float32)
    for sign in (-1.0, 1.0):
        opening, lash = _one_eye(canvas, rig, x, y, sign, blink, gaze)
        alpha = np.maximum(alpha, opening * 1.15 + lash)
    rgb = canvas.lit(1.05)
    return premul(rgb, np.clip(alpha, 0.0, 1.0))


def _one_eye(canvas: Canvas, rig: Rig, x, y, sign: float, blink: float, gaze: tuple[float, float]):
    """Eyes are a little smaller, scaled evenly around each eye so the iris stays round."""
    k = EYE_SCALE
    cx = sign * EYE_X
    cy = EYE_Y
    x = cx + (x - cx) / k
    y = cy + (y - cy) / k
    gaze = (gaze[0] / k, gaze[1] / k)
    u = (x - cx) * sign / EYE_HW
    ey = y - cy
    uc = np.clip(u, -1.0, 1.0)
    q = np.clip(1.0 - uc**2, 0.0, 1.0)
    tilt = 0.007
    upper = -0.0300 * q**0.75 * (1.0 - 0.12 * uc) - tilt * uc
    lower = 0.0115 * q**1.25 - tilt * uc * 0.55
    closed = 0.008 * q - tilt * uc * 0.75
    up = upper * (1.0 - blink) + closed * blink
    lo = lower * (1.0 - blink) + closed * blink
    edge = max(float(canvas.px) * 1.2, 0.004) / k
    inside_u = smooth((1.0 - np.abs(u)) / 0.05)
    opening = smooth((ey - up) / edge) * smooth((lo - ey) / edge) * inside_u
    canvas.light((0.44 * opening).astype(np.float32), lerp(PAL["face"], PAL["white"], 0.45))
    canvas.shade((opening * 0.45 * np.exp(-np.clip(ey - up, 0.0, None) / 0.009)).astype(np.float32))
    icx = cx + gaze[0] - sign * 0.002
    icy = cy + 0.0035 + gaze[1]
    radius = 0.0325
    dx = x - icx
    dy = y - icy
    dist = np.hypot(dx, dy)
    di = dist / radius
    iris = smooth((1.0 - di) / 0.05) * opening
    ang = np.arctan2(dy, dx)
    fib = 0.85 + 0.15 * np.sin(19 * ang + 3 * di) * np.sin(7 * ang + 1.3)
    canvas.shade((iris * (0.55 + 0.8 * _ss(0.80, 1.0, di))).astype(np.float32))
    icol = lerp(
        PAL["iris0"],
        PAL["iris1"],
        np.clip(1.0 - di, 0.0, 1.0) * 0.8 + 0.2 * _ss(-0.3, 1.0, dy / radius),
    )
    canvas.light(
        (iris * fib * (0.38 + 0.65 * _ss(-0.5, 0.9, dy / radius))).astype(np.float32), icol
    )
    pupil = smooth((1.0 - dist / 0.0120) / 0.18) * opening
    canvas.shade((pupil * 1.6).astype(np.float32))
    canvas.light(
        (2.4 * _gauss(x, y, icx - 0.0095, icy - 0.0100, 0.0047) * opening).astype(np.float32),
        PAL["white"],
    )
    canvas.light(
        (0.9 * _gauss(x, y, icx + 0.0085, icy + 0.0075, 0.0020) * opening).astype(np.float32),
        PAL["white"],
    )
    thick = 0.0024 + 0.0024 * _ss(-0.4, 1.0, u)
    lash = np.exp(-(((ey - up + 0.0012) / thick) ** 2)) * smooth((1.06 - np.abs(u + 0.03)) / 0.06)
    canvas.shade((1.05 * lash).astype(np.float32))
    canvas.light((0.10 * lash).astype(np.float32), PAL["hair0"])
    _outer_lashes(canvas, rig, cx, cy, sign, blink, k)
    return opening.astype(np.float32), lash.astype(np.float32)


def _to_eye(cx: float, cy: float, px: float, py: float, k: float) -> tuple[float, float]:
    return cx + (px - cx) * k, cy + (py - cy) * k


def _outer_lashes(
    canvas: Canvas, rig: Rig, cx: float, cy: float, sign: float, blink: float, k: float
) -> None:
    """A few outer lashes and a small wing. Positions scale with the eye."""
    tilt = 0.007
    pts = []
    for index, (uu, length) in enumerate(((0.70, 0.010), (0.86, 0.013), (1.0, 0.015))):
        qq = 1.0 - uu**2
        yy = (-0.0300 * qq**0.75 * (1.0 - 0.12 * uu) - tilt * uu) * (1.0 - blink) + (
            0.008 * qq - tilt * uu * 0.75
        ) * blink
        px, py = _to_eye(cx, cy, cx + sign * uu * EYE_HW, cy + yy, k)
        up = np.array([sign * (0.55 + 0.25 * index), -1.0])
        down = np.array([sign * (0.7 + 0.2 * index), 0.55])
        direction = up * (1.0 - blink) + down * blink
        direction = direction / (np.hypot(direction[0], direction[1]) + 1e-6)
        tt = np.linspace(0.0, length, 50)[:, None]
        bend = np.array([sign, 0.0]) * (tt / length) ** 2 * 0.004
        raw = np.array([px, py]) + direction * tt * k + bend * k
        pts.append(raw)
    stacked = np.concatenate(pts)
    weights = np.tile(np.linspace(1.0, 0.15, 50), 3)
    canvas.splat_shade(rig.world(stacked), 0.10 * weights, 0.7)
    tt = np.linspace(0.0, 1.0, 60)[:, None]
    yy0 = -tilt * (1.0 - blink) + (-tilt * 0.75) * blink
    ox, oy = _to_eye(cx, cy, cx + sign * EYE_HW, cy + yy0, k)
    wing = (
        np.array([ox, oy])
        + np.array([sign * 0.010 * k, (-0.004 * (1.0 - blink) + 0.001 * blink) * k]) * tt
    )
    canvas.splat_shade(rig.world(wing), 0.16 * (1.0 - tt[:, 0]) + 0.03, 0.8)


def paint_mouth(rig: Rig, width: int, openness: float) -> np.ndarray:
    """Pale lips on a little skin light, so the parting is a line and not a black hole."""
    width, height = raster_size(width)
    canvas = Canvas(width, height)
    x, y = rig.local_grids(canvas)
    alpha = _mouth(canvas, x, y, openness)
    rgb = canvas.lit(1.02)
    return premul(rgb, alpha)


def _mouth(canvas: Canvas, x, y, openness: float) -> np.ndarray:
    mw = MOUTH_HW * (1.0 - 0.13 * openness)
    u = x / mw
    uc = np.clip(u, -1.0, 1.0)
    q = np.clip(1.0 - uc**2, 0.0, 1.0)
    my = y - MOUTH_Y
    line = -0.0072 * (1.0 - 0.45 * openness) * uc**2 + 0.0016 * np.exp(-((uc / 0.22) ** 2))
    upper = line - openness * 0.0085 * q
    lower = line + openness * 0.029 * q**0.85
    edge = max(float(canvas.px) * 1.2, 0.0035)
    in_u = smooth((1.0 - np.abs(u)) / 0.06)
    gap = smooth((my - upper) / edge) * smooth((lower - my) / edge) * in_u
    depth = smooth((my - upper) / 0.004) * smooth((lower - my) / 0.004)
    plum = np.array([0.42, 0.16, 0.26], dtype=np.float32)
    canvas.light(
        (0.42 * openness * gap * _gauss(x, my, 0.0, lower - 0.006, 0.6 * mw, 0.007)).astype(
            np.float32
        ),
        PAL["lip"],
    )
    teeth = (
        gap * np.exp(-(((my - upper - 0.0028) / 0.0026) ** 2)) * smooth((0.55 - np.abs(u)) / 0.2)
    )
    teeth = teeth * _ss(0.3, 0.7, openness)
    canvas.light((0.20 * teeth).astype(np.float32), PAL["teeth"])
    bow = 0.0038 * np.exp(-(((np.abs(uc) - 0.30) / 0.20) ** 2)) - 0.0016 * np.exp(
        -((uc / 0.13) ** 2)
    )
    top = upper - (0.0105 * q**0.5 + bow)
    lip = lerp(PAL["face"], PAL["blush"], 0.45)
    upper_lip = smooth((my - top) / edge) * smooth((upper - my) / edge) * in_u
    bottom = lower + 0.0125 * q**0.7
    lower_lip = smooth((my - lower) / edge) * smooth((bottom - my) / (edge * 2.4)) * in_u
    bed = upper_lip + lower_lip
    canvas.light((0.42 * bed).astype(np.float32), PAL["face"])
    canvas.light((0.34 * upper_lip).astype(np.float32), lip)
    canvas.light((0.48 * lower_lip).astype(np.float32), lip)
    canvas.light((0.55 * gap).astype(np.float32), plum)
    canvas.light(
        (0.14 * _gauss(x, my, 0.0, lower + 0.0075, 0.36 * mw, 0.0030)).astype(np.float32),
        PAL["shine"],
    )
    part = np.exp(-(((my - line) / 0.0021) ** 2)) * smooth((1.03 - np.abs(u)) / 0.06)
    closed = 1.0 - float(_ss(0.0, 0.18, openness))
    canvas.shade((0.55 * part * closed).astype(np.float32))
    canvas.shade((0.18 * gap * (0.6 + 0.4 * depth)).astype(np.float32))
    corner_y = (-0.0075 + 0.0018 * math.exp(-((1.0 / 0.22) ** 2))) * (
        1.0 - 0.45 * openness
    ) - 0.0012
    for sign in (-1.0, 1.0):
        canvas.shade(
            (
                0.22
                * (1.0 - 0.7 * float(_ss(0.1, 0.5, openness)))
                * _gauss(x, my, sign * mw * 1.03, corner_y, 0.0030, 0.0026)
            ).astype(np.float32)
        )
    canvas.shade(
        (0.10 * _gauss(x, my, 0.0, 0.0165 + openness * 0.029 + 0.012, 0.022, 0.0055)).astype(
            np.float32
        )
    )
    return np.clip(bed * 1.15 + gap * 0.95 + part * closed, 0.0, 1.0).astype(np.float32)


def paint_ring(rig: Rig, width: int) -> np.ndarray:
    width, height = raster_size(width)
    canvas = Canvas(width, height)
    orbit_ring(canvas, rig.noise, 1.0)
    return premul_light(canvas.lit(1.05))


def paint_star(rig: Rig, width: int) -> np.ndarray:
    width, height = raster_size(width)
    canvas = Canvas(width, height)
    sparkle(canvas, rig.star, 0.078, PAL["star"], 1.05)
    return premul_light(canvas.lit(1.15))


BLINK_LEVELS = (0.0, 0.25, 0.5, 0.75, 1.0)
GAZE_LEVELS = ((0.0, 0.0), (0.012, -0.01), (-0.008, 0.004))
MOUTH_LEVELS = tuple(i / 7.0 for i in range(8))


def bake_layers(size: int) -> dict[str, np.ndarray]:
    """Every cached layer for one bake. Keys are plain names. Size is the width."""
    rig = Rig(size)
    hair = paint_hair_layers(rig, size)
    layers: dict[str, np.ndarray] = {
        "wisps": paint_wisps(rig, size),
        "hair_tip": hair["tip"],
        "hair_mid": hair["mid"],
        "hair_root": hair["root"],
        "face": paint_face(rig, size),
        "hair_front": hair["front"],
        "ring": paint_ring(rig, size),
        "star": paint_star(rig, size),
    }
    for index, blink in enumerate(BLINK_LEVELS):
        layers[f"eye_{index}"] = paint_eyes(rig, size, blink, (0.0, 0.0))
    for index, gaze in enumerate(GAZE_LEVELS[1:], start=1):
        layers[f"gaze_{index}"] = paint_eyes(rig, size, 0.0, gaze)
    layers["gaze_0"] = layers["eye_0"]
    for index, openness in enumerate(MOUTH_LEVELS):
        layers[f"mouth_{index}"] = paint_mouth(rig, size, openness)
    return layers
