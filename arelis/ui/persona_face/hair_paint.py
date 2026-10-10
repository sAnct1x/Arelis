# ruff: noqa: N806
"""Hair v4: one painted mass instead of the strand-particle cap.

The hair is two sweeps that meet at a centre part. Each sweep is the band
between an inner and an outer guide curve (head units, y down); every strand
is an interpolation between the two, so the flow follows the comb from the
part over the dome and down into the curtains. The right sweep's inner edge
is the side-swept bang across her right forehead.

Strands are drawn as a dense point field (several samples per pixel), each
carrying its own shade: fine strand texture across the flow, lock structure
with darker gaps, sheen bands on the dome and the waves. The rest plate is
built once per size; the sway phases are a cheap horizontal warp of it.
"""

from __future__ import annotations

import math

import numpy as np

from arelis.ui.persona_face import face_src as face2
from arelis.ui.persona_face.nebula_src import Canvas, smooth

# Guide curves, viewer's left and right. Point i of an inner curve pairs with
# point i of its outer curve. Both sweeps root on the part, from the hairline
# apex (index 0 of the inner curves) to the top of the dome (index 0 outer).
PART_APEX = (-0.058, -0.250)
PART_TOP = (-0.020, -0.428)
LEFT_INNER = (
    PART_APEX,
    (-0.090, -0.222),
    (-0.115, -0.180),
    (-0.150, -0.126),
    (-0.181, -0.065),
    (-0.209, 0.000),
    (-0.230, 0.070),
    (-0.230, 0.135),
    (-0.200, 0.200),
    (-0.160, 0.255),
    (-0.142, 0.315),
    (-0.110, 0.405),
    (-0.098, 0.500),
    (-0.096, 0.640),
    (-0.096, 0.780),
)
LEFT_OUTER = (
    PART_TOP,
    (-0.085, -0.424),
    (-0.160, -0.390),
    (-0.235, -0.330),
    (-0.300, -0.255),
    (-0.354, -0.165),
    (-0.392, -0.075),
    (-0.404, 0.010),
    (-0.370, 0.100),
    (-0.348, 0.200),
    (-0.375, 0.300),
    (-0.436, 0.400),
    (-0.470, 0.500),
    (-0.490, 0.620),
    (-0.505, 0.780),
)
RIGHT_INNER = (
    PART_APEX,
    (-0.010, -0.207),
    (0.045, -0.162),
    (0.095, -0.115),
    (0.135, -0.062),
    (0.142, -0.010),
    (0.174, 0.048),
    (0.225, 0.105),
    (0.224, 0.150),
    (0.200, 0.200),
    (0.152, 0.255),
    (0.136, 0.315),
    (0.126, 0.405),
    (0.122, 0.500),
    (0.120, 0.640),
    (0.120, 0.780),
)
RIGHT_OUTER = (
    PART_TOP,
    (0.050, -0.426),
    (0.130, -0.396),
    (0.205, -0.346),
    (0.270, -0.276),
    (0.322, -0.200),
    (0.362, -0.110),
    (0.385, -0.020),
    (0.374, 0.075),
    (0.346, 0.165),
    (0.364, 0.255),
    (0.412, 0.355),
    (0.450, 0.455),
    (0.485, 0.590),
    (0.505, 0.780),
)

# Measured hair palette, dark gap to white sheen (shade 0..1).
PALETTE_AT = (0.0, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 1.0)
PALETTE = (
    (70, 54, 104),
    (104, 85, 141),
    (128, 107, 168),
    (167, 142, 205),
    (201, 176, 236),
    (223, 202, 245),
    (237, 222, 246),
    (251, 245, 252),
)
NECK_LIGHT = (204, 182, 220)
NECK_DARK = (160, 136, 194)
GAP = (96, 78, 136)
LOCKS = 6
# The parting of the lock that frames each cheek, in u, per side.
FRAME_U = {-1: 0.22, 1: 0.32}
# Curtain groove: its u along the curtain, per side, by height.
GROOVE_Y = (0.18, 0.28, 0.40, 0.50, 0.62)
GROOVE_U = {-1: (0.66, 0.58, 0.45, 0.36, 0.32), 1: (0.74, 0.60, 0.44, 0.33, 0.30)}
# Sheen ribbons per side: (u centre, drift of the centre along s, u width,
# start s, end s, strength). Measured off the target's light pattern.
SHEEN = {
    -1: ((0.44, -0.12, 0.13, 0.02, 0.50, 0.30), (0.56, 0.0, 0.10, 0.55, 0.92, 0.18)),
    1: ((0.26, 0.20, 0.14, 0.04, 0.34, 0.30), (0.52, 0.0, 0.10, 0.55, 0.92, 0.18)),
}
FRINGE = 0.016
BANG_FRINGE = 0.032
CONTRAST = 1.12
WAVE_AMP = 0.013
WAVE_LEN = 0.36
# Bottom fade into the void, head units.
FADE_FROM, FADE_TO = 0.47, 0.63
# Sway warp, head units at the hem.
SWAY = 0.010

_REST: dict = {}


def _catmull(points, count: int) -> np.ndarray:
    """Uniform Catmull-Rom through the points, count samples, ends included."""
    pts = np.asarray(points, dtype=np.float64)
    ext = np.vstack([2 * pts[0] - pts[1], pts, 2 * pts[-1] - pts[-2]])
    t = np.linspace(0.0, len(pts) - 1.0, count)
    seg = np.minimum(t.astype(int), len(pts) - 2)
    f = (t - seg)[:, None]
    p0, p1, p2, p3 = ext[seg], ext[seg + 1], ext[seg + 2], ext[seg + 3]
    return 0.5 * (
        2 * p1
        + (-p0 + p2) * f
        + (2 * p0 - 5 * p1 + 4 * p2 - p3) * f * f
        + (-p0 + 3 * p1 - 3 * p2 + p3) * f * f * f
    )


def _hash_table(seed: int, size: int = 4096) -> np.ndarray:
    return np.random.default_rng(seed).random(size)


def _noise1(x: np.ndarray, table: np.ndarray) -> np.ndarray:
    """Smooth 1D value noise in 0..1."""
    i = np.floor(x).astype(np.int64)
    f = x - i
    f = f * f * (3 - 2 * f)
    n = len(table)
    return table[i % n] * (1 - f) + table[(i + 1) % n] * f


def _noise2(a: np.ndarray, b: np.ndarray, table: np.ndarray) -> np.ndarray:
    """Smooth 2D value noise in 0..1 on an integer lattice."""
    i = np.floor(a).astype(np.int64)
    j = np.floor(b).astype(np.int64)
    fa = a - i
    fb = b - j
    fa = fa * fa * (3 - 2 * fa)
    fb = fb * fb * (3 - 2 * fb)
    n = len(table)

    def at(di, dj):
        return table[((i + di) * 7919 + (j + dj) * 104729) % n]

    top = at(0, 0) * (1 - fa) + at(1, 0) * fa
    bottom = at(0, 1) * (1 - fa) + at(1, 1) * fa
    return top * (1 - fb) + bottom * fb


def _palette(shade: np.ndarray) -> np.ndarray:
    pal = np.asarray(PALETTE, dtype=np.float64) / 255.0
    return np.stack([np.interp(shade, PALETTE_AT, pal[:, c]) for c in range(3)], -1)


def _splat(acc: np.ndarray, px: np.ndarray, py: np.ndarray, weight: np.ndarray, rgb) -> None:
    """Bilinear deposit of weight and weight*rgb into acc (H, W, 4)."""
    height, width = acc.shape[:2]
    ok = (px >= 0) & (px < width - 1) & (py >= 0) & (py < height - 1) & (weight > 0)
    px, py, weight, rgb = px[ok], py[ok], weight[ok], rgb[ok]
    i = px.astype(np.int64)
    j = py.astype(np.int64)
    fx = px - i
    fy = py - j
    n = width * height
    flat = acc.reshape(n, 4)
    for di, dj, ww in (
        (0, 0, (1 - fx) * (1 - fy)),
        (1, 0, fx * (1 - fy)),
        (0, 1, (1 - fx) * fy),
        (1, 1, fx * fy),
    ):
        idx = (j + dj) * width + (i + di)
        w = weight * ww
        flat[:, 3] += np.bincount(idx, w, minlength=n)
        for c in range(3):
            flat[:, c] += np.bincount(idx, w * rgb[:, c], minlength=n)


def _sweep(acc, view, width, height, inner, outer, side: int, seed: int) -> None:
    """Paint one sweep of strands into acc (weight-summed, not yet normalised)."""
    x0, x1, y0, y1 = view
    px_size = (x1 - x0) / width
    c0 = _catmull(inner, 64)
    c1 = _catmull(outer, 64)
    length = max(
        float(np.hypot(*np.diff(c0, axis=0).T).sum()), float(np.hypot(*np.diff(c1, axis=0).T).sum())
    )
    span = float(np.max(np.hypot(*(c1 - c0).T)))
    # Two to three samples per pixel along and across the flow.
    nt = int(length / px_size * 2.6) + 8
    nu = int(span / px_size * 2.6) + 8
    c0 = _catmull(inner, nt)
    c1 = _catmull(outer, nt)
    # The outer rim runs a little past the outer curve as a thin, dark,
    # broken fringe of strand ends, so the edge is soft instead of cut.
    fringe = FRINGE / max(span, 1e-6)
    # The bang's lower edge over the forehead is a wider, sheer fringe the
    # brow shows through.
    fringe_in = (BANG_FRINGE if side > 0 else 0.0) / max(span, 1e-6)
    nu = int(nu * (1 + fringe + fringe_in))
    u = (np.arange(nu) + 0.5) / nu * (1 + fringe + fringe_in) - fringe_in
    s = np.linspace(0.0, 1.0, nt)
    U = u[:, None]
    S = s[None, :]
    P = c0[None] * (1 - U[..., None]) + c1[None] * U[..., None]
    if fringe_in > 0:
        # Run the sheer fringe a fixed distance past the inner curve.
        tangent = np.gradient(c0, axis=0)
        normal = np.stack([-tangent[:, 1], tangent[:, 0]], -1)
        normal /= np.maximum(np.hypot(*normal.T), 1e-9)[:, None]
        flip = np.sign(((c1 - c0) * normal).sum(-1, keepdims=True))
        away = -normal * np.where(flip == 0, 1.0, flip)
        out_t = np.clip(-U / fringe_in, 0.0, 1.0)[..., None]
        P = np.where(U[..., None] < 0, c0[None] + away[None] * out_t * BANG_FRINGE, P)
    x = P[..., 0]
    y = P[..., 1]
    tab = _hash_table(seed)
    tab2 = _hash_table(seed + 1)
    tab3 = _hash_table(seed + 2)
    tab4 = _hash_table(seed + 3)
    # Locks of uneven width, with a slow wobble along the flow.
    warped = U + 0.05 * (_noise1(U * 3.0 + 5.0, tab4) - 0.5)
    lock_u = warped * LOCKS + 0.30 * (_noise1(S * 3.0 + U * 2.0, tab) - 0.5)
    lock_id = np.floor(lock_u)
    lock_f = lock_u - lock_id
    lock_key = (lock_id.astype(np.int64) * 7 + 3) % len(tab)
    # Soft waves below the jaw, a different phase per lock.
    low = smooth((y - 0.10) / 0.25)
    phase = 2 * math.pi * _noise1(lock_u * 0.6 + 11.0, tab2)
    wave = np.sin(2 * math.pi * (y - 0.12) / WAVE_LEN + phase * 0.35 + side * 0.6)
    x = x + side * WAVE_AMP * low * wave
    # Area each sample stands for, in pixels, so coverage sums to one.
    gx_u = np.gradient(x, axis=0)
    gy_u = np.gradient(y, axis=0)
    gx_s = np.gradient(x, axis=1)
    gy_s = np.gradient(y, axis=1)
    area = np.abs(gx_u * gy_s - gy_u * gx_s) / (px_size * px_size)
    area = np.minimum(area, 4.0)
    # Fine strands across the flow, two or three pixels apart, that drift a
    # little along their length so they never read as ruled lines.
    across = span / px_size
    drift = _noise1(S * 7.0 + U * 4.0, tab3) - 0.5
    fine = _noise1(U * across / 2.2 + drift * 6.0, tab3)
    mid = _noise1(U * across / 7.0 + drift * 3.0 + 17.0, tab2)
    lock_gain = tab[lock_key] - 0.5
    gap_depth = 0.35 + 0.65 * tab2[lock_key]
    gap = np.exp(-((np.minimum(lock_f, 1 - lock_f) / 0.09) ** 2)) * gap_depth
    gap = gap * smooth(U / 0.06)
    # Each lock is a soft cylinder: lit down its middle.
    roll = np.sin(math.pi * lock_f) ** 0.8
    # The mass is lit from the front: brightest over the inner middle of
    # each sweep, turning darker toward the outer rim.
    body = np.exp(-(((U - 0.36) / 0.32) ** 2))
    # Broad sheen patches, long along the flow, and a few bright streaks.
    patch = _noise2(warped * 4.0 + drift, S * 3.2 + 0.7 * U, tab4)
    patch = smooth((patch - 0.35) / 0.55)
    streak = _noise1(warped * 7.0 + drift * 1.2 + 3.0, tab4) ** 3
    streak = streak * _noise2(warped * 3.0 + 5.0, S * 2.2, tab)
    # The ring of sheen round the dome, a little in from its outline; the
    # crown by the part sits in shade above it.
    wide = np.hypot(*(c1 - c0).T)[None, :]
    inset = (1 - U) * wide
    dome = np.exp(-(((inset - 0.075) / 0.040) ** 2)) * (1 - smooth((y + 0.02) / 0.16))
    crown = np.exp(-(((x + 0.02) / 0.11) ** 2)) * (1 - smooth((y + 0.36) / 0.10))
    # Each curtain splits into an inner fall and an outer lock that takes the
    # flare; a deep groove runs between them.
    groove_u = np.interp(y, GROOVE_Y, GROOVE_U[side])
    groove = np.exp(-(((U - groove_u) / 0.035) ** 2)) * smooth((y - GROOVE_Y[0]) / 0.08)
    fall = np.sin(math.pi * np.clip(U / np.maximum(groove_u, 0.05), 0, 1)) ** 0.7
    outer = np.sin(math.pi * np.clip((U - groove_u) / np.maximum(1 - groove_u, 0.05), 0, 1)) ** 0.7
    split = np.where(U < groove_u, fall, outer) * smooth((y - GROOVE_Y[0]) / 0.10)
    # Higher up, the lock that frames the cheek parts from the rest.
    frame_u = FRAME_U[side]
    frame = np.exp(-(((U - frame_u) / 0.045) ** 2))
    frame = frame * smooth((y + 0.06) / 0.08) * (1 - smooth((y - 0.16) / 0.10))
    crest = 0.5 + 0.5 * np.sin(
        2 * math.pi * (y - 0.12) / WAVE_LEN + phase * 0.35 + side * 0.6 + 1.2
    )
    # The long sheen ribbon each sweep carries down from the part, and the
    # one down the middle of each curtain.
    ribbon = 0.0
    for centre, slope, width_u, s0, s1, amount in SHEEN[side]:
        env = smooth((S - s0) / 0.05) * (1 - smooth((S - s1) / 0.12))
        ribbon = ribbon + amount * env * np.exp(-(((U - centre - slope * S) / width_u) ** 2))
    ribbon = ribbon * (0.75 + 0.5 * patch)
    shade = (
        0.27
        + ribbon
        + 0.26 * body
        + 0.20 * lock_gain
        + 0.12 * roll * (0.3 + 0.7 * low)
        + 0.07 * (fine - 0.5)
        + 0.08 * (mid - 0.5)
        + 0.22 * patch
        + 0.24 * streak
        + 0.30 * dome
        - 0.12 * crown
        + 0.08 * crest * low
        - 0.30 * gap * (0.25 + 0.75 * low)
        - 0.55 * groove
        - 0.40 * frame
        + 0.16 * split
    )
    # A soft crease at the part with the hair lifting off it, darker toward
    # the outer rim, and the shadow the head casts behind the jaw.
    shade -= 0.11 * (1 - smooth(S / 0.03))
    shade += 0.08 * np.exp(-(((S - 0.07) / 0.05) ** 2))
    shade -= 0.42 * smooth((U - 0.66) / 0.34)
    shade -= 0.14 * (1 - smooth(U / 0.10)) * smooth((y - 0.12) / 0.10)
    if side > 0:
        # The bang catches the light along its lower edge.
        bang_band = smooth((y + 0.22) / 0.06) * (1 - smooth((y - 0.0) / 0.06))
        shade += 0.16 * np.exp(-(((U - 0.07) / 0.09) ** 2)) * bang_band
    else:
        bang_band = np.zeros_like(y)
    shade = 0.5 + CONTRAST * (shade - 0.5)
    past = np.clip((U - 1.0) / fringe, 0.0, 1.0)
    shade = shade * (1 - 0.55 * past)
    shade = np.clip(shade, 0.0, 1.0)
    rgb = _palette(shade)
    # Edge strands taper over the last few percent at both edges.
    edge = U * span / max(px_size, 1e-6)
    soft = np.clip(edge / 3.0 + (fine - 0.5) * 1.6, 0.0, 1.0)
    ends = np.clip((fine - past * 0.9) * 2.5, 0.0, 1.0) * (1 - past) ** 0.7
    soft = soft * np.where(U > 1.0, ends, 1.0)
    if fringe_in > 0:
        before = np.clip(-U / fringe_in, 0.0, 1.0)
        # Strands that leave the edge for a stretch and end, not ruled lines.
        stretch = _noise2(U * across / 3.0 + 31.0, S * length / 0.045, tab2)
        sheer = np.clip((stretch - 0.35 - before * 0.45) * 2.4, 0.0, 1.0)
        sheer = sheer * (1 - before) ** 0.8 * 0.75
        soft = np.where(U < 0.0, sheer * bang_band, soft)
        soft = np.where((U >= 0.0) & (edge < 3.0), np.maximum(soft, bang_band * 0.9), soft)
    # Strands leave the part one by one, so the part is a soft crease.
    roots = np.clip(S * length / 0.006 + (fine - 0.5) * 1.5, 0.0, 1.0)
    weight = area * soft * roots * (1 - smooth((y - FADE_FROM) / (FADE_TO - FADE_FROM)))
    px = (x - x0) / (x1 - x0) * width
    py = (y - y0) / (y1 - y0) * height
    _splat(
        acc,
        px.ravel(),
        py.ravel(),
        weight.ravel(),
        rgb.reshape(-1, 3),
    )


def _resolve(acc: np.ndarray) -> np.ndarray:
    """Weighted sums to premultiplied colour and coverage (float, 0..1)."""
    w = acc[..., 3]
    alpha = np.clip(w, 0.0, 1.0)
    rgb = acc[..., :3] / np.maximum(w, 1e-6)[..., None]
    return np.concatenate([rgb * alpha[..., None], alpha[..., None]], -1)


def _over(top: np.ndarray, base: np.ndarray) -> np.ndarray:
    return top + base * (1 - top[..., 3:4])


def _grid(view, width, height):
    x0, x1, y0, y1 = view
    X = (x0 + np.arange(width) * (x1 - x0) / width)[None, :].repeat(height, 0)
    Y = (y0 + np.arange(height) * (y1 - y0) / height)[:, None].repeat(width, 1)
    return X, Y


def _inner_x(curve, y: np.ndarray) -> np.ndarray:
    pts = _catmull(curve, 400)
    low = pts[pts[:, 1] > 0.2]
    order = np.argsort(low[:, 1])
    return np.interp(y, low[order, 1], low[order, 0])


def _window(X, Y, px_size) -> np.ndarray:
    """Where the face and neck sit in front of the hair (soft, 0..1)."""
    ly = face2.VY + (Y - face2.VY) / face2.VSTRETCH
    hw = face2.face_w(ly)
    face = smooth((hw * 0.93 - np.abs(X)) / max(0.006, 2 * px_size)) * (hw > 0)
    face = face * smooth((Y - 0.06) / 0.07)
    left = _inner_x(LEFT_INNER, Y) + 0.010
    right = _inner_x(RIGHT_INNER, Y) - 0.010
    feather = max(0.004, 1.5 * px_size)
    neck = smooth((X - left) / feather) * smooth((right - X) / feather) * smooth((Y - 0.20) / 0.04)
    return np.maximum(face, neck)


def _neck(X, Y, px_size) -> np.ndarray:
    """A plain neck under the chin that fades into the void (premultiplied)."""
    half = 0.205 - 0.060 * smooth((Y - 0.24) / 0.20) + 0.010 * smooth((Y - 0.45) / 0.20)
    across = np.abs(X) / half
    alpha = smooth((1 - across) / max(0.08, 3 * px_size / 0.1))
    alpha = (
        alpha * smooth((Y - 0.16) / 0.05) * (1 - smooth((Y - FADE_FROM) / (FADE_TO - FADE_FROM)))
    )
    light = np.asarray(NECK_LIGHT, dtype=np.float64) / 255.0
    dark = np.asarray(NECK_DARK, dtype=np.float64) / 255.0
    # Shade toward where the curtains cover the sides, and under the jaw.
    side = smooth((np.abs(X) - 0.03) / 0.10)
    chin = 1 - smooth((Y - 0.30) / 0.10)
    mix = np.clip(0.80 * side + 0.40 * chin, 0, 1)[..., None]
    rgb = light * (1 - mix) + dark * mix
    return np.concatenate([rgb * alpha[..., None], alpha[..., None]], -1)


def paint_rest(view, width: int, height: int) -> dict:
    """The rest hair, the neck and the face window, float premultiplied. Cached per size."""
    key = (tuple(view), int(width), int(height))
    if key in _REST:
        return _REST[key]
    x0, x1, _y0, _y1 = view
    px_size = (x1 - x0) / width
    left = np.zeros((height, width, 4))
    right = np.zeros((height, width, 4))
    _sweep(left, view, width, height, LEFT_INNER, LEFT_OUTER, -1, 41)
    _sweep(right, view, width, height, RIGHT_INNER, RIGHT_OUTER, 1, 57)
    left = _resolve(left)
    right = _resolve(right)
    # Gap fill: dark hair under the locks, so a parting between waves is
    # darker lavender, never the void.
    cover = np.maximum(left[..., 3], right[..., 3])
    sigma = max(1.0, 0.010 / px_size)
    soft = Canvas.blur(np.repeat(cover[..., None], 3, -1), sigma)[..., 0]
    # Only well inside the mass, so it never rims the outline.
    gap_a = np.clip((soft - 0.62) / 0.25, 0, 1)
    gap = np.concatenate(
        [
            np.asarray(GAP, dtype=np.float64)[None, None] / 255.0 * gap_a[..., None],
            gap_a[..., None],
        ],
        -1,
    )
    hair = _over(right, _over(left, gap))
    X, Y = _grid(view, width, height)
    out = {
        "hair": hair.astype(np.float32),
        "window": _window(X, Y, px_size).astype(np.float32),
        "neck": _neck(X, Y, px_size).astype(np.float32),
        "Y": Y.astype(np.float32),
        "X": X.astype(np.float32),
        "px": px_size,
    }
    _REST.clear()
    _REST[key] = out
    return out


SWAY_REST = 0.35


def _swing(X: np.ndarray, Y: np.ndarray, t: float) -> np.ndarray:
    swing = math.sin(1.15 * t) + 0.35 * np.sin(1.9 * t + 3.0 * Y)
    spread = 0.35 * math.sin(0.7 * t + 0.4) * np.tanh(X / 0.08)
    return swing + spread


def _sway(rest: dict, t: float) -> np.ndarray:
    """Horizontal shift in pixels, zero on the dome, largest at the tips.

    Measured from the first phase, so phase 0 is the painted rest plate.
    """
    X, Y = rest["X"], rest["Y"]
    reach = smooth((Y - 0.05) / 0.55) ** 1.5
    move = _swing(X, Y, t) - _swing(X, Y, SWAY_REST)
    return (SWAY * reach * move / rest["px"]).astype(np.float32)


def _warp(image: np.ndarray, shift: np.ndarray) -> np.ndarray:
    """Sample each row at x - shift, bilinear. image (H, W, C) float."""
    height, width = image.shape[:2]
    xs = np.arange(width, dtype=np.float32)[None, :] - shift
    xs = np.clip(xs, 0.0, width - 1.001)
    i = xs.astype(np.int64)
    f = (xs - i)[..., None]
    rows = np.arange(height)[:, None]
    return image[rows, i] * (1 - f) + image[rows, i + 1] * f


def _pack(premul: np.ndarray) -> np.ndarray:
    return np.clip(premul * 255.0 + 0.5, 0, 255).astype(np.uint8)


def plates(view, width: int, height: int, t: float, *, still: bool = False):
    """Back (hair behind the face, then the neck) and front (hair over the face).

    The two hair halves split by the face window, so where neither the face
    nor the neck is, the hair is drawn exactly once.
    """
    rest = paint_rest(view, width, height)
    hair = rest["hair"]
    window = rest["window"]
    if not still:
        shift = _sway(rest, t)
        both = _warp(np.concatenate([hair, window[..., None]], -1), shift)
        hair = both[..., :4]
        # The face part of the window stays with the face; the neck part
        # rides with the curtains.
        face_part = rest["window"] * (1 - smooth((rest["Y"] - 0.30) / 0.06))
        window = np.maximum(face_part, both[..., 4])
    w = window[..., None]
    back = _over(rest["neck"], hair * w)
    front = hair * (1 - w)
    return _pack(back), _pack(front)
