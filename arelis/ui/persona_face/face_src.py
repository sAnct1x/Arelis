# ruff: noqa: E731, F841, B007, B905, N806, E741
"""Approved nebula face, v2, with the v2.3 switches applied by the bake.

Pass 2 reuses the particle canvas: smooth noise and gaussian glow, open eyes,
an animatable mouth, and a shade buffer so features can sit darker than the glow.
"""

from __future__ import annotations

import numpy as np

from arelis.ui.persona_face.nebula_src import (
    PALETTES,
    Canvas,
    Noise,
    background,
    hexrgb,
    lerpc,
    smooth,
)
from arelis.ui.persona_face.scene_bits import gasify, orbit_ring, sparkle

PAL = PALETTES["night_light"]

# ---------------- head geometry (head local units, y points down) ----------
TOP, WID, CHIN = -0.44, 0.03, 0.305  # crown, widest (cheekbones), chin
A = 0.255  # half width at the cheekbones
EYE_Y, EYE_X, EYE_HW = 0.014, 0.114, 0.059
BROW_Y, BROW_X, BROW_HW = -0.066, 0.118, 0.062
NOSE_Y = 0.121
MOUTH_Y, MOUTH_HW = 0.190, 0.047
PIVOT = np.array([0.0, 0.36])  # head turns around the neck


def half_w(y):
    y = np.asarray(y, float)
    uu = np.clip((WID - y) / (WID - TOP), 0, 1)
    up = A * np.sqrt(np.clip(1 - uu**2, 0, 1))
    ud = np.clip((y - WID) / (CHIN - WID), 0, 1)
    dn = A * np.clip(1 - ud**2.15, 0, 1) ** 0.64
    w = np.where(y < WID, up, dn)
    return np.where((y > TOP) & (y < CHIN), w, 0.0)


# v2.1: cheek/jaw width factor for the skin only (hair keeps the v2 head shape).
# 1.0 reproduces v2; 0.95 narrows the cheeks and jaw by 5%, blending in from the
# temples down to the cheekbones so the forehead and hairline stay put.
CHEEK = 1.0


def face_w(y):
    y = np.asarray(y, float)
    return half_w(y) * (1 - (1 - CHEEK) * smooth((y + 0.20) / 0.20))


# v2.2: CROWN pulls the hair closer to the skull on top and on the upper sides
# (0 = v2/v2.1 volume, 1 = v2.2). It fades to nothing at the sides, so the side
# locks, fringe and length are unchanged. PART_FIX softens the bright spot where
# the cap strands meet at the part.
CROWN = 0.0
_prng = np.random.default_rng(909)
PART_FIX = False
# v2.2 polish: GLOW gives the skin a faint inner starlight so it reads as nebula,
# NECK lets the neck dissolve into gas lower down. Both off reproduces v2.1.
GLOW = False
NECK = False
# v2.3: SIDE pulls in the upper side volume (temples / sides of the crown) and
# tapers to nothing at the top and at ear level. VSTRETCH makes the whole head a
# touch taller (stretched about VY); the eyes, brows, nose, mouth and blush keep
# their own shapes and only move with the stretch. 0 / 1.0 reproduce v2.2.
SIDE = 0.0
SIDE_RESTORE = 1.0
VSTRETCH = 1.0
VY = -0.05
GLOW_P = dict(c0=0.14, c1=0.66, edge=0.30, base=0.56, core=0.16, fil=0.16)


def side_weight(sin_up):
    return np.exp(-(((sin_up + 0.50) / 0.34) ** 2))


def top_weight(sin_up):
    """0 at the sides, 1 straight up (y points down, so up is sin < 0)."""
    return np.clip(-sin_up, 0, 1) ** 2


def inside_face(p, k=1.0):
    return np.abs(p[:, 0]) < half_w(p[:, 1]) * k


def g2(X, Y, cx, cy, sx, sy=None):
    sy = sx if sy is None else sy
    return np.exp(-((X - cx) ** 2 / (2 * sx * sx) + (Y - cy) ** 2 / (2 * sy * sy)))


def ss(e0, e1, x):
    return smooth((x - e0) / (e1 - e0))


# ---------------- canvas with a shade (darkening) buffer --------------------
class Canvas2(Canvas):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.shades = {}
        x0, x1, y0, y1 = self.view
        self.X = (x0 + np.arange(self.W) * (x1 - x0) / self.W)[None, :].repeat(self.H, 0)
        self.Y = (y0 + np.arange(self.H) * (y1 - y0) / self.H)[:, None].repeat(self.W, 1)
        self.px = (x1 - x0) / self.W
        # particle weights were tuned at 640 px per unit; keep brightness the same at other scales
        self.dens = (self.W / (x1 - x0) / 640.0) ** 2

    def splat(self, xy, w, color, sigma=0.8):
        super().splat(xy, np.asarray(w, float) * self.dens, color, sigma)

    def sbuf(self, sigma):
        if sigma not in self.shades:
            self.shades[sigma] = np.zeros((self.H, self.W))
        return self.shades[sigma]

    def splat_shade(self, xy, w, sigma=0.8):
        if len(xy) == 0:
            return
        px, py = self.to_px(xy)
        w = np.broadcast_to(np.asarray(w, float) * self.dens, px.shape)
        ok = (px >= 0) & (px < self.W - 1) & (py >= 0) & (py < self.H - 1)
        px, py, w = px[ok], py[ok], w[ok]
        i, j = px.astype(int), py.astype(int)
        fx, fy = px - i, py - j
        b = self.sbuf(sigma)
        n = self.W * self.H
        for di, dj, ww in (
            (0, 0, (1 - fx) * (1 - fy)),
            (1, 0, fx * (1 - fy)),
            (0, 1, (1 - fx) * fy),
            (1, 1, fx * fy),
        ):
            b += np.bincount((j + dj) * self.W + (i + di), w * ww, minlength=n).reshape(
                self.H, self.W
            )

    def light(self, field, color):
        if isinstance(color, str):
            color = hexrgb(color)
        self.buf(0)[...] += field[..., None] * np.asarray(color, float)

    def shade(self, field):
        self.sbuf(0)[...] += field

    def render(
        self,
        bg,
        bloom=((6, 0.35), (22, 0.28), (60, 0.22)),
        exposure=1.0,
        tint=(1.0, 1.18, 0.78),
        as_array=False,
        mask=None,
    ):
        acc = np.zeros((self.H, self.W, 3))
        for s, b in self.layers.items():
            acc += self.blur(b, s) * (2 * np.pi * s * s if s > 0.5 else 1)
        S = np.zeros((self.H, self.W))
        for s, b in self.shades.items():
            S += (
                self.blur(np.repeat(b[..., None], 3, -1), s)[..., 0] * (2 * np.pi * s * s)
                if s > 0.5
                else b
            )
        T = np.exp(-np.clip(S, 0, None)[..., None] * np.asarray(tint))
        a = acc * T
        if mask is not None:
            a = a * mask[..., None]
        lit = a.copy()
        for s, k in bloom:
            lit += k * self.blur(a, s)
        lit *= exposure * T**0.6
        if mask is not None:
            lit *= np.clip(mask * 1.15, 0, 1)[..., None]
        out = 1 - (1 - bg * T**0.3) * np.exp(-lit)
        out = np.clip(out, 0, 1)
        if as_array:
            return out
        from PIL import Image

        return Image.fromarray((out * 255).astype(np.uint8))


# ---------------- smooth time drift (sum of travelling sines) ---------------
class Drift:
    def __init__(self, seed, n=5, kmin=1.5, kmax=4.0, wmin=0.15, wmax=0.45):
        r = np.random.default_rng(seed)
        ang = r.random(n) * 2 * np.pi
        k = r.uniform(kmin, kmax, n)
        self.kv = np.stack([np.cos(ang) * k, np.sin(ang) * k], 1)
        self.w = r.uniform(wmin, wmax, n) * r.choice([-1, 1], n)
        self.ph = r.random((n, 2)) * 2 * np.pi
        self.a = 1 / np.sqrt(n)

    def __call__(self, xy, t):
        d = np.zeros_like(xy)
        for kv, w, ph in zip(self.kv, self.w, self.ph):
            arg = xy @ kv + w * t * 2 * np.pi
            d[:, 0] += np.sin(arg + ph[0])
            d[:, 1] += np.cos(arg + ph[1])
        return d * self.a


# ---------------- hair (vectorised version of the pass 1 strands) -----------
def build_hair(seed=11, n_strands=820):
    r = np.random.default_rng(seed)
    HN = Noise(seed=44, octaves=((3, 1.0), (6, 0.45)))
    c = np.array([0.0, -0.08])
    th = r.uniform(-np.pi + 0.10, -0.10, n_strands)
    R0 = r.uniform(0.355, 0.43, n_strands)
    Rs = R0 - CROWN * 0.065 * top_weight(np.sin(th)) - SIDE * 0.060 * side_weight(np.sin(th))
    p = c + Rs[:, None] * np.stack([np.cos(th), np.sin(th)], 1)
    side = np.where(np.cos(th) >= 0, 1.0, -1.0)
    restore = (
        SIDE * SIDE_RESTORE * 0.060 * side_weight(np.sin(th)) / 0.30
    )  # lower locks keep their place
    steps = r.integers(115, 215, n_strands)
    ds = 0.008
    P = np.zeros((215, n_strands, 2))
    s = 0.0
    for k in range(215):
        d = p - c
        rr = np.hypot(d[:, 0], d[:, 1]) + 1e-6
        u = d / rr[:, None]
        tg = np.stack([-u[:, 1], u[:, 0]], 1)
        flip = (tg[:, 0] * side + tg[:, 1]) < 0
        tg[flip] *= -1
        g = smooth((p[:, 1] - (c[1] + 0.02)) / 0.30)[:, None]
        flare = 0.16 + 1.25 * smooth((p[:, 1] - 0.34) / 0.55)
        down = np.stack([side * flare, np.ones(n_strands)], 1)
        down /= np.hypot(down[:, 0], down[:, 1])[:, None]
        Rt = R0 - CROWN * 0.065 * top_weight(u[:, 1]) - SIDE * 0.060 * side_weight(u[:, 1])
        v = (1 - g) * tg + g * down + (1 - g) * ((Rt - rr) * 5)[:, None] * u
        ins = inside_face(p, 1.13) | ((np.abs(p[:, 0]) < 0.10) & (p[:, 1] > 0.2) & (p[:, 1] < 0.6))
        v[ins, 0] += side[ins] * 1.5
        if SIDE:
            v[:, 0] += (
                side
                * restore
                * smooth((p[:, 1] + 0.04) / 0.05)
                * (1 - smooth((p[:, 1] - 0.22) / 0.06))
            )
        amp = 0.1 + 7.0 * smooth((k * ds - 0.45) / 0.9)
        cx, cy = HN.curl(p[:, 0], p[:, 1])
        v = v / (np.hypot(v[:, 0], v[:, 1])[:, None] + 1e-6) + amp * np.stack([cx, cy], 1)
        v /= np.hypot(v[:, 0], v[:, 1])[:, None] + 1e-6
        p = p + v * ds
        P[k] = p
    allp, alls = [], []
    for i in range(n_strands):
        allp.append(P[: steps[i], i])
        alls.append(np.arange(steps[i]) * ds)
    strands = [(a, b) for a, b in zip(allp, alls)]

    # soft bangs: a side part, one sweep across the forehead, one to the other side,
    # plus thin face framing locks down past the cheeks
    def bez(P0, P1, P2, P3, n=130):
        tt = np.linspace(0, 1, n)[:, None]
        return (
            (1 - tt) ** 3 * P0
            + 3 * (1 - tt) ** 2 * tt * P1
            + 3 * (1 - tt) * tt**2 * P2
            + tt**3 * P3
        )

    bangs = []
    part = np.array([-0.075, -0.452])
    # cap: strands combed from the side part over the skull to both sides
    for i in range(560):
        right = i % 3 != 0
        k = r.random() ** 1.25
        rx, ry = 0.238 + 0.20 * k, 0.255 + 0.215 * k
        th1 = (-0.04 - 0.40 * r.random()) if right else (-np.pi + 0.04 + 0.40 * r.random())
        th0 = -np.pi / 2 + (0.16 if right else -0.10) + r.normal(0, 0.04)
        tt = np.linspace(0, 1, 160)
        th = th0 + (th1 - th0) * (1 - (1 - tt) ** 1.5)
        j = r.normal(0, 0.006)
        tw_ = np.clip(
            CROWN * 0.42 * top_weight(np.sin(th)) + SIDE * 0.45 * side_weight(np.sin(th)), 0, 0.9
        )
        rxe = rx - tw_ * (rx - 0.238)
        rye = ry - tw_ * (ry - 0.255)
        pts = np.stack([np.cos(th) * (rxe + j), -0.06 + np.sin(th) * (rye + j)], 1)
        bl = smooth(tt / (0.30 + 0.15 * (1 - k)))[:, None]
        jit0 = r.normal(0, 0.012, 2) * [1.0, 0.5]
        if PART_FIX:
            jit0 = jit0 * [1.8, 1.0] + [
                0.0,
                0.012 + 0.02 * _prng.random(),
            ]  # own rng: other strands unchanged
        pts = part + jit0 + (pts - part) * bl
        n2 = 50
        tail = pts[-1] + np.stack([np.zeros(n2), np.linspace(0, 0.26, n2)], 1)
        tail[:, 0] += np.sign(np.cos(th1)) * np.linspace(0, 0.02 + 0.03 * k, n2)
        bangs.append(np.concatenate([pts, tail]))
    # fringe: strands leave the part line and sweep across the forehead
    for i in range(230):
        f2 = r.random()
        f = np.clip(f2 + r.normal(0, 0.15), 0, 1)
        o = r.normal(0, 0.005, 2)
        P0 = np.array([-0.075 + 0.012 * f2 + r.normal(0, 0.006), -0.445 + 0.15 * f2])
        pts = bez(
            P0 + o,
            P0 + np.array([0.035, 0.085]) + o,
            np.array([0.12 + 0.06 * f, -0.25 + 0.135 * f]) + o,
            np.array([0.245 + 0.03 * f, -0.10 + 0.17 * f]) + o,
            160,
        )
        bangs.append(pts)
    # and a softer sweep to the other side
    for i in range(130):
        f2 = r.random()
        f = np.clip(f2 + r.normal(0, 0.15), 0, 1)
        o = r.normal(0, 0.005, 2)
        P0 = np.array([-0.082 - 0.01 * f2 + r.normal(0, 0.006), -0.445 + 0.14 * f2])
        pts = bez(
            P0 + o,
            P0 + np.array([-0.025, 0.075]) + o,
            np.array([-0.20 - 0.01 * f, -0.31 + 0.10 * f]) + o,
            np.array([-0.252 - 0.01 * f, -0.15 + 0.12 * f]) + o,
            140,
        )
        bangs.append(pts)
    # thin face framing locks past the cheeks
    for sx in (-1, 1):
        for i in range(36):
            o = r.normal(0, 0.009, 2)
            f = r.uniform(0, 1)
            pts = bez(
                np.array([sx * 0.232, -0.22]) + o,
                np.array([sx * 0.272, -0.04]) + o,
                np.array([sx * (0.262 + 0.02 * f), 0.18]) + o,
                np.array([sx * (0.205 + 0.06 * f), 0.38 + 0.06 * f]) + o,
                140,
            )
            bangs.append(pts)
    return strands, bangs


def hair_particles(strands, bangs, seed=12):
    r = np.random.default_rng(seed)
    P, W, C, J, S, F = [], [], [], [], [], []
    for pts, s in strands:
        P.append(pts)
        S.append(s)
        F.append(np.zeros(len(pts), bool))
        W.append(0.03 * np.exp(-s / 1.6) * smooth(s / 0.06 + 0.2))
        C.append(np.clip(s / 1.15, 0, 1))
        J.append(0.0012 + 0.03 * smooth((s - 0.5) / 1.0))
    for pts in bangs:
        n = len(pts)
        s = np.linspace(0, 0.5, n)
        P.append(pts)
        S.append(s * 0.3)
        F.append(np.ones(n, bool))
        W.append(
            0.034 * np.ones(n) * smooth((0.5 - s) / 0.18 + 0.1) * (0.05 + 0.95 * smooth(s / 0.26))
        )
        C.append(s * 0.8)
        J.append(0.0016 + 0 * s)
    P = np.concatenate(P)
    W = np.concatenate(W)
    C = np.concatenate(C)
    J = np.concatenate(J)
    S = np.concatenate(S)
    F = np.concatenate(F)
    k = 2
    Pg = gasify(P, k, J, r)
    return dict(
        P=P,
        W=W,
        C=C,
        S=S,
        F=F,
        Pg=Pg,
        Sg=np.repeat(S, k),
        Wg=np.repeat(W, k) / k * 1.6,
        Cg=np.repeat(C, k),
        sel=r.random(len(P)) < 0.012,
        jit=r.normal(0, 0.01, (len(P), 2)),
    )


# ---------------- face gas particles (texture over the smooth face) --------
def face_gas(noise, seed=13, n=170000):
    r = np.random.default_rng(seed)
    pts = np.stack([r.uniform(-A, A, n * 3), r.uniform(TOP, CHIN, n * 3)], 1)
    pts = pts[np.abs(pts[:, 0]) < face_w(pts[:, 1]) * 0.98][:n]
    d = np.abs(pts[:, 0]) / np.maximum(face_w(pts[:, 1]), 1e-4)
    w = 0.0016 * (1 - 0.5 * d**2) * smooth((pts[:, 1] + 0.33) / 0.1)
    pts = noise.advect(pts, 4, 0.003)
    return pts, w


# ---------------- the rig -------------------------------------------------
class Rig:
    def __init__(self, seed=21):
        self.noise = Noise(seed=seed)
        self.strands, self.bangs = build_hair()
        self.hair = hair_particles(self.strands, self.bangs)
        self.gas, self.gas_w = face_gas(self.noise)
        rd = np.random.default_rng(77)
        self._dust = rd.random(len(self.gas)) < 0.0018
        # neck gas: particles from under the chin, carried down and outward
        n = 60000
        y0 = rd.uniform(0.28, 0.62, n)
        x0 = rd.normal(0, 0.05, n) * (1 + 2.2 * np.clip(y0 - 0.40, 0, 1))
        ng = self.noise.advect(np.stack([x0, y0], 1), 10, 0.006)
        self.neck_gas = ng
        self.neck_amp = np.clip((y0 - 0.32) / 0.3, 0, 1)
        self.neck_w = 0.0018 * (1 - smooth((y0 - 0.36) / 0.30)) * smooth((y0 - 0.27) / 0.06)
        self.neck_c = np.clip((y0 - 0.3) / 0.4, 0, 1)
        self.d_hair = Drift(101, kmin=1.2, kmax=3.0, wmin=0.05, wmax=0.16)
        self.d_gas = Drift(102, kmin=2.0, kmax=5.0, wmin=0.05, wmax=0.15)
        self.d_wisp = Drift(103, kmin=0.8, kmax=2.2, wmin=0.03, wmax=0.09)
        r = np.random.default_rng(9)
        xy = r.normal(0, 0.9, (200000, 2))
        self.wisp = self.noise.advect(xy, 40, 0.01)
        v = np.clip(self.noise.val(self.wisp[:, 0] * 0.8, self.wisp[:, 1] * 0.8) * 3 + 0.2, 0, 1)
        self.wisp_w = 0.0016 * v
        self.wisp_c = lerpc(PAL["wisp"], PAL["hair1"], v * 0.4)

    # local <-> world
    @staticmethod
    def to_world(p, pose):
        rot, tx, ty, sc = pose
        c, s = np.cos(rot), np.sin(rot)
        p = np.stack([p[:, 0], VY + (p[:, 1] - VY) * VSTRETCH], 1) if VSTRETCH != 1.0 else p
        q = (p - PIVOT) * sc
        return (
            np.stack([q[:, 0] * c - q[:, 1] * s, q[:, 0] * s + q[:, 1] * c], 1) + PIVOT + [tx, ty]
        )

    @staticmethod
    def to_local(X, Y, pose):
        rot, tx, ty, sc = pose
        c, s = np.cos(rot), np.sin(rot)
        x, y = X - PIVOT[0] - tx, Y - PIVOT[1] - ty
        lx, ly = (x * c + y * s) / sc + PIVOT[0], (-x * s + y * c) / sc + PIVOT[1]
        if VSTRETCH != 1.0:
            ly = VY + (ly - VY) / VSTRETCH
        return lx, ly

    def splat_front_hair(self, cv, t, pose, *, cover_only: bool = False):
        """Front strands and sparkles. Also stores the fringe cover for the skin."""
        pal = PAL
        hair = self.hair
        amp = 0.004 + 0.05 * smooth((hair["Sg"] - 0.25) / 1.1)
        gassy = self.to_world(hair["Pg"] + amp[:, None] * self.d_hair(hair["Pg"], t), pose)
        amp2 = 0.004 + 0.05 * smooth((hair["S"] - 0.25) / 1.1)
        points = self.to_world(hair["P"] + amp2[:, None] * self.d_hair(hair["P"], t), pose)
        front = hair["F"]
        cov = Canvas(cv.W, cv.H, view=cv.view)
        chosen = points[front]
        if len(chosen):
            cov.splat(chosen, np.full(len(chosen), 1.0), np.ones(3), 0.8)
        blurred = cov.blur(cov.buf(0.8), 1.6 * cv.W / 768)[..., 0] * 2 * np.pi * 0.64
        self._cover = np.clip(blurred * (0.9 * (768 / cv.W) ** 2), 0, 1) ** 0.7
        if cover_only:
            return
        cv.splat(gassy, hair["Wg"], lerpc(pal["hair0"], pal["hair1"], hair["Cg"]), 0.8)
        cv.splat(
            points[::2],
            hair["W"][::2] * 0.25,
            lerpc(pal["hair0"], pal["hair1"], hair["C"][::2]),
            3.0,
        )
        sel = hair["sel"]
        tw = 0.6 + 0.4 * np.sin(t * 2.3 + np.arange(sel.sum()) * 1.7)
        spark = 0.25 * np.exp(-hair["C"][sel]) * tw
        if PART_FIX:
            spark = spark * np.clip(hair["W"][sel] / 0.025, 0, 1)
        cv.splat(
            points[sel] + hair["jit"][sel],
            spark,
            lerpc(pal["face"], pal["hair1"], hair["C"][sel] * 0.5),
            0.8,
        )

    # ---------------- per frame ----------------
    def draw(
        self,
        cv,
        t=0.0,
        mouth=0.0,
        blink=0.0,
        gaze=(0.0, 0.0),
        pose=(0.0, 0.0, 0.0, 1.0),
        brow=0.0,
        wisp_strength=1.0,
        ring=True,
        star=True,
        ring_rx=0.70,
        ring_ry=0.165,
        parts="all",
    ):
        pal = PAL
        X, Y = self.to_local(cv.X, cv.Y, pose)
        if parts in ("all", "wisps"):
            wp = self.wisp + 0.035 * self.d_wisp(self.wisp, t)
            cv.splat(wp, self.wisp_w * wisp_strength, self.wisp_c, 9.0)
        if parts == "wisps":
            return
        if parts in ("all", "hair"):
            self.splat_front_hair(cv, t, pose)
        if parts == "hair":
            return
        if not hasattr(self, "_cover"):
            self.splat_front_hair(cv, t, pose, cover_only=True)
        # face gas texture (with the jaw dropping a little when the mouth opens)
        g = self.gas + 0.004 * self.d_gas(self.gas, t)
        g[:, 1] += mouth * 0.016 * ss(MOUTH_Y - 0.03, CHIN, g[:, 1])
        cv.splat(self.to_world(g, pose), self.gas_w, lerpc(pal["face"], pal["hair0"], 0.3), 2.0)
        if GLOW:
            dust = self.gas[self._dust]
            tw2 = 0.5 + 0.5 * np.sin(t * 1.9 + np.arange(len(dust)) * 2.3)
            cv.splat(
                self.to_world(dust + 0.003 * self.d_gas(dust, t), pose),
                0.05 * tw2,
                hexrgb("#ffffff"),
                0.8,
            )
        if NECK:
            ng = self.neck_gas + 0.012 * self.d_wisp(self.neck_gas, t) * self.neck_amp[:, None]
            cv.splat(
                self.to_world(ng, pose),
                self.neck_w,
                lerpc(pal["hair0"], pal["hair1"], self.neck_c),
                2.0,
            )
        self.face_fields(cv, X, Y, t, mouth, blink, gaze, brow)
        if ring:
            r = np.random.default_rng(5)
            orbit_ring(
                cv,
                pal,
                self.noise,
                r,
                0.85,
                c=(pose[1] * 0.5, 0.30 + pose[2] * 0.5),
                rx=ring_rx,
                ry=ring_ry,
                tilt=-0.15,
            )
        if star:
            sp = self.to_world(np.array([[0.232, -0.372]]), pose)[0]
            sparkle(cv, sp, 0.078, hexrgb(pal["star"]), 0.85 + 0.12 * np.sin(t * 1.7))

    def face_fields(self, cv, X, Y, t, m, b, gaze, brow):
        fy = lambda c: c + (Y - c) * VSTRETCH  # keeps a feature's own shape unstretched
        pal = PAL
        face, hair0, blush = hexrgb(pal["face"]), hexrgb(pal["hair0"]), hexrgb(pal["blush"])
        e = cv.px * 1.2
        # ---- skin: soft luminous oval, a little brighter on forehead, nose, cheeks
        Yf = Y - m * 0.016 * ss(MOUTH_Y - 0.03, CHIN, Y)
        hw = face_w(Yf)
        d = np.abs(X) / np.maximum(hw, 1e-4)
        ins = smooth((1 - d) / 0.16) * (hw > 0) * ss(-0.36, -0.22, Yf)
        shape = 0.30 + 0.70 * np.clip(1 - d**2, 0, 1) ** 1.4
        vert = 1.0 - 0.16 * ss(0.05, 0.33, Yf)
        hi = (
            0.22 * g2(X, Yf, 0, -0.17, 0.08, 0.06)
            + 0.16 * g2(X, Yf, 0, 0.08, 0.014, 0.05)
            + 0.12 * (g2(X, Yf, 0.125, 0.06, 0.05) + g2(X, Yf, -0.125, 0.06, 0.05))
            + 0.08 * g2(X, Yf, 0, CHIN - 0.045, 0.03, 0.02)
        )
        tex = 0.92 + 0.16 * self.noise.val(X * 2.5 + 0.02 * t, Y * 2.5 - 0.01 * t)
        yh = -0.29 + 2.6 * X**2
        skin = (
            ins
            * (shape * vert + hi)
            * tex
            * (1 - 0.92 * self._cover)
            * ss(yh - 0.02, yh + 0.06, Yf)
        )
        # neck, dimmer, fading into the gas
        if NECK:  # longer, softer neck that turns into drifting gas
            nw = 0.068 + 0.16 * np.clip(Y - 0.42, 0, 1)
            neck = (
                smooth((nw - np.abs(X)) / 0.07) * ss(0.20, 0.30, Y) * (1 - ss(0.30, 0.80, Y)) * 0.24
            )
            neck *= 1 - 0.6 * ins
            neck = neck * np.clip(
                0.55 + 0.9 * (self.noise.val(X * 3.5 + 0.03 * t, Y * 2.5 - 0.04 * t) + 0.12),
                0.2,
                1.4,
            )
        else:
            nw = 0.070 + 0.06 * np.clip(Y - 0.36, 0, 1)
            neck = (
                smooth((nw - np.abs(X)) / 0.05) * ss(0.20, 0.30, Y) * (1 - ss(0.30, 0.52, Y)) * 0.24
            )
            neck *= 1 - 0.6 * ins
            neck = neck * (0.85 + 0.3 * self.noise.val(X * 3 + 0.03 * t, Y * 3))
        rim = 0.16 * np.exp(-(((d - 0.95) / 0.07) ** 2)) * (hw > 0) * ss(-0.30, -0.15, Yf)
        dd = np.where(hw > 0, d, 1.0)
        col = lerpc(pal["face"], pal["hair0"], np.clip(0.10 + 0.50 * dd**2, 0, 1))
        col = col * 0.80 + hexrgb(pal["blush"]) * 0.20
        if GLOW:
            # lit from inside: a soft starlight core, faint nebula filaments, more
            # translucent lavender toward the edges (less flat grey)
            mask = ins * (1 - 0.92 * self._cover) * ss(yh - 0.02, yh + 0.06, Yf)
            core = g2(X, Yf, 0.0, 0.03, 0.12, 0.15)
            ridge = (
                np.clip(
                    1 - np.abs(self.noise.val(X * 3.2 + 0.02 * t + 1.3, Y * 3.2 - 0.015 * t) * 6),
                    0,
                    1,
                )
                ** 3
            )
            G = GLOW_P
            col = (
                lerpc(pal["face"], pal["hair0"], np.clip(G["c0"] + G["c1"] * dd**1.8, 0, 1)) * 0.78
                + hexrgb(pal["blush"]) * 0.22
            )
            edge = 1 - G["edge"] * np.clip(dd, 0, 1) ** 2
            cv.buf(0)[...] += (G["base"] * skin * edge)[..., None] * col
            cv.light(mask * G["core"] * core, "#fff0fb")
            cv.light(
                mask * G["fil"] * ridge * (0.5 + 0.5 * core),
                lerpc(pal["hair0"], pal["hair1"], 0.4 + 0.0 * X),
            )
            cv.buf(0)[...] += (0.50 * neck)[..., None] * hexrgb(pal["hair0"])
        else:
            cv.buf(0)[...] += (0.68 * skin)[..., None] * col + (0.50 * neck)[..., None] * hexrgb(
                pal["hair0"]
            )
        cv.light(rim, lerpc(pal["hair0"], pal["face"], 0.35))
        cv.shade(
            0.10 * ss(0.30, 0.34, Y) * (1 - ss(0.34, 0.40, Y)) * smooth((0.09 - np.abs(X)) / 0.03)
        )  # under chin
        # ---- cheeks
        for sx in (-1, 1):
            cv.light(0.36 * g2(X, fy(0.100), sx * 0.150, 0.100, 0.042, 0.030), blush)
        # ---- brows
        for sx in (-1, 1):
            u = (X * sx - BROW_X) / BROW_HW
            yb = BROW_Y - brow - 0.013 * (1 - ((u - 0.15) / 1.15) ** 2) + 0.003 * u
            th = 0.0062 * (1 - 0.6 * ss(-0.6, 1.0, u))
            f = np.exp(-(((fy(BROW_Y) - yb) / th) ** 2)) * smooth((1 - np.abs(u)) / 0.18)
            cv.shade(0.55 * f)
            cv.light(0.10 * f, hair0)
        # ---- eyes
        for sx in (-1, 1):
            self.eye(cv, X, fy(EYE_Y), sx, b, gaze, e)
        # ---- nose (just a hint)
        Yn = fy(NOSE_Y)
        cv.light(0.22 * g2(X, Yn, 0.0, NOSE_Y - 0.010, 0.010), face)
        yn = NOSE_Y + 0.008 + 0.006 * (X / 0.02) ** 2
        cv.shade(0.30 * np.exp(-(((Yn - yn) / 0.0032) ** 2)) * smooth((0.022 - np.abs(X)) / 0.010))
        for sx in (-1, 1):
            cv.shade(0.45 * g2(X, Yn, sx * 0.0115, NOSE_Y + 0.008, 0.0036, 0.0026))
        cv.shade(0.10 * g2(X, Yn, 0.021, NOSE_Y - 0.035, 0.004, 0.028))
        # ---- mouth
        self.mouth(cv, X, fy(MOUTH_Y), m, e)

    def eye(self, cv, X, Y, sx, b, gaze, e):
        pal = PAL
        cx, cy = sx * EYE_X, EYE_Y
        u = (X - cx) * sx / EYE_HW
        ey = Y - cy
        uc = np.clip(u, -1, 1)
        q = np.clip(1 - uc**2, 0, 1)
        tilt = 0.007
        upper = -0.0300 * q**0.75 * (1 - 0.12 * uc) - tilt * uc
        lower = 0.0115 * q**1.25 - tilt * uc * 0.55
        closed = 0.008 * q - tilt * uc * 0.75
        up = upper * (1 - b) + closed * b
        lo = lower * (1 - b) + closed * b
        inside_u = smooth((1 - np.abs(u)) / 0.05)
        O = smooth((ey - up) / e) * smooth((lo - ey) / e) * inside_u
        # whites, with a soft shadow under the upper lid
        cv.light(0.44 * O, lerpc(pal["face"], "#ffffff", 0.45))
        cv.shade(O * 0.45 * np.exp(-np.clip(ey - up, 0, None) / 0.009))
        # iris + pupil, clipped by the lids
        icx, icy = cx + gaze[0] - sx * 0.002, cy + 0.0035 + gaze[1]
        R = 0.0325
        dx, dy = X - icx, Y - icy
        dist = np.hypot(dx, dy)
        di = dist / R
        I = smooth((1 - di) / 0.05) * O
        ang = np.arctan2(dy, dx)
        fib = 0.85 + 0.15 * np.sin(19 * ang + 3 * di) * np.sin(7 * ang + 1.3)
        cv.shade(I * (0.85 + 0.9 * ss(0.80, 1.0, di)))
        icol = lerpc(
            "#8a6ae0", "#efc4ff", np.clip(1 - di, 0, 1) * 0.8 + 0.2 * ss(-0.3, 1.0, dy / R)
        )
        cv.light(I * fib * (0.62 + 0.7 * ss(-0.5, 0.9, dy / R)), icol)
        P = smooth((1 - dist / 0.0120) / 0.18) * O
        cv.shade(P * 1.6)
        # catchlights (they sparkle a little brighter than anything else in the face)
        cv.light(2.4 * g2(X, Y, icx - 0.0095, icy - 0.0100, 0.0047) * O, "#ffffff")
        cv.light(0.9 * g2(X, Y, icx + 0.0085, icy + 0.0075, 0.0020) * O, "#ffffff")
        # lash line (upper lid), crease, faint lower lid
        thick = 0.0024 + 0.0024 * ss(-0.4, 1.0, u)
        lash = np.exp(-(((ey - up + 0.0012) / thick) ** 2)) * smooth(
            (1.06 - np.abs(u + 0.03)) / 0.06
        )
        cv.shade(1.05 * lash)
        cv.light(0.10 * lash, pal["hair0"])
        crease = np.exp(-(((ey - (upper - 0.0085 * q**0.8 - 0.0015)) / 0.0020) ** 2)) * smooth(
            (0.75 - np.abs(u + 0.05)) / 0.25
        )
        cv.shade(0.18 * crease * (1 - b))
        low = (
            np.exp(-(((ey - lo - 0.0015) / 0.0018) ** 2))
            * ss(-0.5, 0.6, u)
            * smooth((1.0 - np.abs(u)) / 0.1)
        )
        cv.shade(0.30 * low * (1 - b))
        # a few lashes at the outer corner (point up when open, down when closed)
        r = np.random.default_rng(3)
        pts = []
        for k, (uu, ln) in enumerate(((0.70, 0.010), (0.86, 0.013), (1.0, 0.015))):
            qq = 1 - uu**2
            yy = (-0.0300 * qq**0.75 * (1 - 0.12 * uu) - tilt * uu) * (1 - b) + (
                0.008 * qq - tilt * uu * 0.75
            ) * b
            px, py = cx + sx * uu * EYE_HW, cy + yy
            a_up = np.array([sx * (0.55 + 0.25 * k), -1.0])
            a_dn = np.array([sx * (0.7 + 0.2 * k), 0.55])
            dv = a_up * (1 - b) + a_dn * b
            dv /= np.hypot(*dv)
            tt = np.linspace(0, ln, 50)[:, None]
            bend = np.array([sx, 0.0]) * (tt / ln) ** 2 * 0.004
            pts.append(np.array([px, py]) + dv * tt + bend)
        pts = np.concatenate(pts)
        wts = np.tile(np.linspace(1, 0.15, 50), 3)
        cv.splat_shade(self._w(pts), 0.10 * wts, 0.7)
        # wing at the outer corner
        tt = np.linspace(0, 1, 60)[:, None]
        yy0 = -tilt * (1 - b) + (-tilt * 0.75) * b
        w0 = np.array([cx + sx * EYE_HW * 1.0, cy + yy0])
        wing = w0 + np.array([sx * 0.010, -0.004 * (1 - b) + 0.001 * b]) * tt
        cv.splat_shade(self._w(wing), 0.16 * (1 - tt[:, 0]) + 0.03, 0.8)

    def mouth(self, cv, X, Y, m, e):
        pal = PAL
        mw = MOUTH_HW * (1 - 0.13 * m)
        u = X / mw
        uc = np.clip(u, -1, 1)
        q = np.clip(1 - uc**2, 0, 1)
        my = Y - MOUTH_Y
        line = -0.0072 * (1 - 0.45 * m) * uc**2 + 0.0016 * np.exp(-((uc / 0.22) ** 2))
        yU = line - m * 0.0085 * q**1.0
        yL = line + m * 0.029 * q**0.85
        inu = smooth((1 - np.abs(u)) / 0.06)
        Mi = smooth((my - yU) / e) * smooth((yL - my) / e) * inu
        depth = smooth((my - yU) / 0.004) * smooth((yL - my) / 0.004)
        cv.shade(1.25 * Mi * (0.6 + 0.4 * depth))
        cv.light(0.42 * m * Mi * g2(X, my, 0, yL - 0.006, 0.6 * mw, 0.007), "#d77aa8")
        teeth = (
            Mi
            * np.exp(-(((my - yU - 0.0028) / 0.0026) ** 2))
            * smooth((0.55 - np.abs(u)) / 0.2)
            * ss(0.3, 0.7, m)
        )
        cv.light(0.20 * teeth, "#f4eeff")
        # lips: upper (softer), lower (catches the light)
        bow = 0.0038 * np.exp(-(((np.abs(uc) - 0.30) / 0.20) ** 2)) - 0.0016 * np.exp(
            -((uc / 0.13) ** 2)
        )
        yT = yU - (0.0105 * q**0.5 + bow)
        lipc = lerpc(pal["face"], pal["blush"], 0.62)
        U = smooth((my - yT) / e) * smooth((yU - my) / e) * inu
        cv.light(0.30 * U, lipc)
        cv.shade(0.10 * U)
        yB = yL + 0.0165 * q**0.7
        Lw = smooth((my - yL) / e) * smooth((yB - my) / (e * 3)) * inu
        cv.light(0.40 * Lw, lipc)
        cv.light(0.14 * g2(X, my, 0, yL + 0.0075, 0.36 * mw, 0.0030), "#ffd6ef")
        # parting line when closed, little smile corners, soft hollow under the lip
        part = np.exp(-(((my - line) / 0.0021) ** 2)) * smooth((1.03 - np.abs(u)) / 0.06)
        cv.shade(0.95 * part * (1 - ss(0.0, 0.18, m)))
        for sx in (-1, 1):
            cv.shade(
                0.32
                * (1 - 0.7 * ss(0.1, 0.5, m))
                * g2(X, my, sx * mw * 1.03, line_at(1.0) * (1 - 0.45 * m) - 0.0012, 0.0030, 0.0026)
            )
        cv.shade(0.14 * g2(X, my, 0, 0.0165 + m * 0.029 + 0.012, 0.022, 0.0055))

    def _w(self, p):  # eye/mouth particle helpers are drawn in local space
        return self.to_world(p, self._pose)


def line_at(u):
    return -0.0075 * u**2 + 0.0018 * np.exp(-((u / 0.22) ** 2))


def render_frame(
    rig,
    W,
    H,
    view,
    t=0.0,
    mouth=0.0,
    blink=0.0,
    gaze=(0, 0),
    pose=(0, 0, 0, 1),
    brow=0.0,
    bg=None,
    exposure=1.0,
    as_array=False,
    **kw,
):
    cv = Canvas2(W, H, view=view)
    rig._pose = pose
    rig.draw(cv, t, mouth, blink, gaze, pose, brow, **kw)
    if bg is None:
        bg = background(W, H, PAL, stars=int(900 * W * H / 1024**2))
    return cv.render(bg, exposure=exposure, as_array=as_array)
