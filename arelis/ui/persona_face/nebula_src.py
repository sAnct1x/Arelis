# ruff: noqa: N806
"""Particle canvas from the approved nebula face renderer.

Procedural particles, smooth noise, and gaussian glow. numpy and Pillow only.
"""

from __future__ import annotations

import numpy as np
from PIL import Image


def hexrgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)])


PALETTES = {
    "violet_teal": dict(
        core="#fff7ff",
        face="#efe6ff",
        hair0="#b79cff",
        hair1="#5fe0d6",
        ring="#8a62c8",
        blush="#f39ac4",
        star="#fffaf0",
        wisp="#5b3f9a",
        bg0="#03061a",
        bg1="#140f33",
    ),
    "gold_rose": dict(
        core="#fffaf0",
        face="#ffe6c8",
        hair0="#ffb04a",
        hair1="#ff6f98",
        ring="#ffa860",
        blush="#ff7f9a",
        star="#fff3d6",
        wisp="#8a3a5a",
        bg0="#07040f",
        bg1="#22112a",
    ),
    "night_light": dict(
        core="#ffffff",
        face="#f1eaff",
        hair0="#a58aff",
        hair1="#e9a6d8",
        ring="#8050b0",
        blush="#f5a3c7",
        star="#ffffff",
        wisp="#4a3480",
        bg0="#020418",
        bg1="#161436",
    ),
}


class Noise:
    """Smooth multi-octave value noise over [-L, L]^2, plus curl."""

    def __init__(self, seed=0, res=512, L=1.6, octaves=((6, 1.0), (12, 0.5), (24, 0.25))):
        rng = np.random.default_rng(seed)
        f = np.zeros((res, res))
        for g, a in octaves:
            small = rng.random((g, g)).astype(np.float32)
            im = Image.fromarray(small, mode="F").resize((res, res), Image.Resampling.BICUBIC)
            f += a * (np.asarray(im) - 0.5)
        self.f, self.res, self.L = f, res, L
        gy, gx = np.gradient(f)
        self.cx, self.cy = gy, -gx  # curl
        m = np.abs(np.stack([self.cx, self.cy])).max()
        self.cx /= m
        self.cy /= m

    def _s(self, arr, x, y):
        u = np.clip((x + self.L) / (2 * self.L) * (self.res - 1), 0, self.res - 1.001)
        v = np.clip((y + self.L) / (2 * self.L) * (self.res - 1), 0, self.res - 1.001)
        i, j = u.astype(int), v.astype(int)
        fu, fv = u - i, v - j
        return (
            arr[j, i] * (1 - fu) * (1 - fv)
            + arr[j, i + 1] * fu * (1 - fv)
            + arr[j + 1, i] * (1 - fu) * fv
            + arr[j + 1, i + 1] * fu * fv
        )

    def val(self, x, y):
        return self._s(self.f, x, y)

    def curl(self, x, y):
        return self._s(self.cx, x, y), self._s(self.cy, x, y)

    def advect(self, xy, steps, dt, amp=1.0):
        x, y = xy[:, 0].copy(), xy[:, 1].copy()
        amp = np.broadcast_to(amp, x.shape)
        for _ in range(steps):
            cx, cy = self.curl(x, y)
            x += cx * dt * amp
            y += cy * dt * amp
        return np.stack([x, y], 1)


class Canvas:
    def __init__(self, W=1024, H=1024, view=(-1, 1, -1, 1)):
        self.W, self.H, self.view = W, H, view
        self.layers = {}  # sigma -> buffer

    def buf(self, sigma):
        if sigma not in self.layers:
            self.layers[sigma] = np.zeros((self.H, self.W, 3))
        return self.layers[sigma]

    def to_px(self, xy):
        x0, x1, y0, y1 = self.view
        return (xy[:, 0] - x0) / (x1 - x0) * self.W, (xy[:, 1] - y0) / (y1 - y0) * self.H

    def splat(self, xy, w, color, sigma=0.8):
        """additively deposit particles (bilinear) into the layer with blur sigma"""
        if len(xy) == 0:
            return
        px, py = self.to_px(xy)
        w = np.broadcast_to(np.asarray(w, float), px.shape)
        color = np.asarray(color, float)
        if color.ndim == 1:
            color = np.broadcast_to(color, (len(px), 3))
        ok = (px >= 0) & (px < self.W - 1) & (py >= 0) & (py < self.H - 1)
        px, py, w, color = px[ok], py[ok], w[ok], color[ok]
        i, j = px.astype(int), py.astype(int)
        fx, fy = px - i, py - j
        b = self.buf(sigma)
        n = self.W * self.H
        for di, dj, ww in (
            (0, 0, (1 - fx) * (1 - fy)),
            (1, 0, fx * (1 - fy)),
            (0, 1, (1 - fx) * fy),
            (1, 1, fx * fy),
        ):
            idx = (j + dj) * self.W + (i + di)
            for c in range(3):
                b[..., c] += np.bincount(idx, w * ww * color[:, c], minlength=n).reshape(
                    self.H, self.W
                )

    def blob(self, center, radius, color, strength):
        """smooth gaussian glow, radius in view units"""
        x0, x1, y0, y1 = self.view
        X = np.linspace(x0, x1, self.W)[None, :]
        Y = np.linspace(y0, y1, self.H)[:, None]
        g = np.exp(-((X - center[0]) ** 2 + (Y - center[1]) ** 2) / (2 * radius**2)) * strength
        self.buf(0)[...] += g[..., None] * np.asarray(color)

    @staticmethod
    def blur(img, sigma):
        if sigma <= 0:
            return img
        H, W = img.shape[:2]
        fy = np.fft.fftfreq(H)[:, None]
        fx = np.fft.rfftfreq(W)[None, :]
        k = np.exp(-2 * (np.pi * sigma) ** 2 * (fx**2 + fy**2))
        return np.stack(
            [np.fft.irfft2(np.fft.rfft2(img[..., c]) * k, s=(H, W)) for c in range(3)], -1
        )

    def render(self, bg, bloom=((6, 0.35), (22, 0.28), (60, 0.22)), exposure=1.0):
        acc = np.zeros((self.H, self.W, 3))
        for s, b in self.layers.items():
            acc += self.blur(b, s) * (2 * np.pi * s * s if s > 0.5 else 1)
        lit = acc.copy()
        for s, a in bloom:
            lit += a * self.blur(acc, s)
        lit *= exposure
        out = 1 - (1 - bg) * np.exp(-lit)
        return Image.fromarray((np.clip(out, 0, 1) ** (1 / 1.0) * 255).astype(np.uint8))


def background(W, H, pal, seed=1, stars=900, glow=0.55, center=(0.5, 0.48)):
    rng = np.random.default_rng(seed)
    X = np.linspace(0, 1, W)[None, :]
    Y = np.linspace(0, 1, H)[:, None]
    d = np.sqrt((X - center[0]) ** 2 + (Y - center[1]) ** 2)
    t = np.clip(1 - d / 0.75, 0, 1) ** 2 * glow
    bg = hexrgb(pal["bg0"]) * (1 - t[..., None]) + hexrgb(pal["bg1"]) * t[..., None]
    # faint dust stars
    sx = rng.integers(0, W, stars)
    sy = rng.integers(0, H, stars)
    b = rng.random(stars) ** 6 * 0.55 + 0.04
    st = np.zeros((H, W))
    np.add.at(st, (sy, sx), b)
    st = Canvas.blur(np.repeat(st[..., None], 3, -1), 0.6)[..., 0] * 6
    bg = 1 - (1 - bg) * np.exp(-st[..., None] * np.array([0.9, 0.9, 1.0]))
    return bg


def lerpc(c0, c1, t):
    t = np.asarray(t)[..., None]
    return hexrgb(c0) * (1 - t) + hexrgb(c1) * t


def smooth(t):
    t = np.clip(t, 0, 1)
    return t * t * (3 - 2 * t)
