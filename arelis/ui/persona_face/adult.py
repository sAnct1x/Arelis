"""v2.3 switches, the early-20s rig, and the v2.4 back hair.

The back layer is the same strand field as the approved v2.4 renderer:
darker, softer lavender, drawn behind the head, neck and shoulders.
"""

from __future__ import annotations

import numpy as np

from arelis.ui.persona_face import face_src as face2
from arelis.ui.persona_face.face_src import WID, Noise, g2, inside_face, smooth, ss
from arelis.ui.persona_face.scene_bits import gasify

BACK = 1.35

EYE_SCALE = 0.91
CHIN_ADULT = 0.312
JAW_P, JAW_Q = 1.85, 0.70
CHEEKBONE = 1.0

_APPLIED = False


def apply_v23() -> None:
    """The switches in render_v23.py, then the adult chin and jaw."""
    global _APPLIED
    if _APPLIED:
        return
    face2.CHEEK = 0.95
    # Wider cheeks so the face fills the trimmed hair. Jaw test stays under 0.36.
    face2.A = 0.275
    face2.CROWN = 1.0
    face2.PART_FIX = True
    face2.GLOW = True
    face2.NECK = True
    face2.SIDE = 1.0
    face2.VSTRETCH = 1.04
    face2.GLOW_P = {"c0": 0.14, "c1": 0.66, "edge": 0.34, "base": 0.55, "core": 0.26, "fil": 0.19}
    face2.CHIN = CHIN_ADULT
    face2.face_w = face_w_adult
    _APPLIED = True


def half_w_adult(y):
    """Same upper head as v2.3. Below the cheekbones the jaw tapers sooner."""
    y = np.asarray(y, float)
    uu = np.clip((WID - y) / (WID - face2.TOP), 0, 1)
    up = face2.A * np.sqrt(np.clip(1 - uu**2, 0, 1))
    ud = np.clip((y - WID) / (CHIN_ADULT - WID), 0, 1)
    dn = face2.A * np.clip(1 - ud**JAW_P, 0, 1) ** JAW_Q
    w = np.where(y < WID, up, dn)
    return np.where((y > face2.TOP) & (y < CHIN_ADULT), w, 0.0)


def face_w_adult(y):
    y = np.asarray(y, float)
    return half_w_adult(y) * (1 - (1 - face2.CHEEK) * smooth((y + 0.20) / 0.20))


def build_back_hair(seed: int = 31, n: int = 900) -> dict:
    """Strands from the back of the skull, falling over the shoulders.

    Same construction as the v2.4 renderer. Roots sit behind the head.
    The front fringe and the side locks are a different pass.
    """
    if face2.HAIR_V3:
        n = face2.BACK_STRANDS
    r = np.random.default_rng(seed)
    hn = Noise(seed=45, octaves=((2, 1.0), (5, 0.35)))
    th = r.uniform(-np.pi + 0.35, -0.35, n)
    rad = r.uniform(0.22, 0.30, n)
    p = np.array([0.0, -0.10]) + rad[:, None] * np.stack([np.cos(th), np.sin(th) * 0.86], 1)
    side = np.sign(p[:, 0] + 1e-6)
    spread = r.uniform(0.12, 0.7, n)
    steps = r.integers(100, 150, n)
    ds = 0.0075
    path = np.zeros((150, n, 2))
    for k in range(150):
        y = p[:, 1]
        flare = side * spread * (0.03 + 0.14 * smooth((y - 0.16) / 0.36))
        v = np.stack([flare, np.ones(n)], 1)
        amp = 0.05 + 0.9 * smooth((k * ds - 0.5) / 1.0)
        cx, cy = hn.curl(p[:, 0] * 1.3, p[:, 1] * 1.3)
        v = v / (np.hypot(v[:, 0], v[:, 1])[:, None] + 1e-6) + amp * 0.35 * np.stack([cx, cy], 1)
        low = smooth((p[:, 1] - 0.20) / 0.16)
        wide = np.clip((np.abs(p[:, 0]) - 0.08) / 0.22, 0.0, 1.0)
        v[:, 0] += -np.sign(p[:, 0] + 1e-6) * 0.65 * low * wide
        v /= np.hypot(v[:, 0], v[:, 1])[:, None] + 1e-6
        p = p + v * ds
        path[k] = p
    sample = np.abs(path[0, :, 0])
    side_end = np.clip((sample - 0.04) / 0.34, 0.0, 1.0)
    ends = 0.655 - 0.04 * side_end
    if face2.HAIR_V3:
        rt = np.random.default_rng(seed + 500)
        ends = face2.HEM_MID - face2.HEM_SIDE * side_end**1.4 + rt.normal(0, face2.HEM_RAND, n)
    pts, arc = [], []
    for i in range(n):
        one = path[: steps[i], i]
        over = np.flatnonzero(one[:, 1] > ends[i])
        if len(over):
            one = one[: max(int(over[0]), 6)]
        pts.append(one)
        arc.append(np.arange(len(one)) * ds)
    points = np.concatenate(pts)
    length = np.concatenate(arc)
    weight = 0.020 * smooth(length / 0.25) * np.exp(-np.clip(length - 0.55, 0, None) / 0.35)
    if face2.HAIR_V3:
        total = np.concatenate([np.full(len(a), a[-1] if len(a) else 0.0) for a in arc])
        weight = weight * (0.15 + 0.85 * smooth((total - length) / 0.12))
    # Plate hem fades the tips. Leave the particle weight alone.
    color = np.clip(length / 1.6, 0, 1)
    keep = ~inside_face(points, 1.02)
    points, length, weight, color = points[keep], length[keep], weight[keep], color[keep]
    copies = 2
    jitter = 0.0012 + 0.02 * smooth((length - 0.5) / 1.0)
    gassy = gasify(points, copies, jitter, r)
    return {
        "P": points,
        "S": length,
        "W": weight,
        "C": color,
        "Pg": gassy,
        "Sg": np.repeat(length, copies),
        "Wg": np.repeat(weight, copies) / copies * 1.6,
        "Cg": np.repeat(color, copies),
    }


class AdultRig(face2.Rig):
    """The approved age-up: smaller eyes, a longer chin, cheekbone and jaw."""

    def __init__(self, seed: int = 21) -> None:
        apply_v23()
        super().__init__(seed)
        self.skip_eyes = False
        self.skip_mouth = False

    def eye(self, cv, X, Y, sx, b, gaze, e):
        if self.skip_eyes:
            return
        cx, cy = sx * face2.EYE_X, face2.EYE_Y
        k = EYE_SCALE
        xs = cx + (X - cx) / k
        ys = cy + (Y - cy) / k
        w0 = self._w
        self._w = lambda p: w0(np.stack([cx + (p[:, 0] - cx) * k, cy + (p[:, 1] - cy) * k], 1))
        try:
            super().eye(cv, xs, ys, sx, b, (gaze[0] / k, gaze[1] / k), e / k)
        finally:
            self._w = w0

    def mouth(self, cv, X, Y, m, e, smile=0.0):
        if self.skip_mouth:
            return
        if smile:
            super().mouth(cv, X, Y, m, e, smile=smile)
            return
        super().mouth(cv, X, Y, m, e)

    def face_fields(self, cv, X, Y, t, m, b, gaze, brow):
        super().face_fields(cv, X, Y, t, m, b, gaze, brow)
        if CHEEKBONE <= 0:
            return
        pal = face2.PAL
        yf = Y - m * 0.016 * ss(face2.MOUTH_Y - 0.03, CHIN_ADULT, Y)
        hw = face_w_adult(yf)
        d = np.abs(X) / np.maximum(hw, 1e-4)
        inside = smooth((1 - d) / 0.16) * (hw > 0) * (1 - 0.92 * self._cover)
        c = CHEEKBONE
        for sx in (-1, 1):
            u = (X - sx * 0.168) * 0.94 + sx * (yf - 0.050) * 0.34
            v = (yf - 0.050) * 0.94 - sx * (X - sx * 0.168) * 0.34
            hi = np.exp(-((u / 0.040) ** 2) - ((v / 0.0135) ** 2))
            cv.light(0.075 * c * hi * inside, face2.lerpc(pal["face"], "#ffffff", 0.3))
            cv.shade(0.085 * c * g2(X, yf, sx * 0.182, 0.128, 0.030, 0.024) * inside)
        jaw = np.exp(-(((d - 0.86) / 0.07) ** 2)) * ss(0.09, 0.19, yf) * (1 - ss(0.27, 0.31, yf))
        cv.shade(0.07 * c * jaw * (hw > 0))
        cv.light(0.05 * c * g2(X, yf, 0, CHIN_ADULT - 0.040, 0.020, 0.012) * inside, pal["face"])


class V24Rig(AdultRig):
    """Age-up face plus the back hair layer from the v2.4 renderer."""

    def __init__(self, seed: int = 21) -> None:
        super().__init__(seed)
        self.back = build_back_hair()
        # Approved back strands, kept for the hair seen through the translucent neck.
        keep, face2.HAIR_V3 = face2.HAIR_V3, False
        try:
            self.back_e8488a1 = build_back_hair() if keep else self.back
        finally:
            face2.HAIR_V3 = keep

    def draw_back(self, cv, t, pose, back=None) -> None:
        pal = face2.PAL
        back = self.back if back is None else back
        dark0 = face2.lerpc(pal["hair0"], "#2a2140", 0.45)
        dark1 = face2.lerpc(pal["hair1"], "#3a2c5c", 0.40)
        v3 = face2.HAIR_V3 and back is self.back
        r0, r1 = (face2.ROOT_AMP, face2.TIP_AMP) if v3 else (0.004, 0.05)
        amp = r0 + r1 * smooth((back["Sg"] - 0.30) / 1.1)
        gassy = self.to_world(back["Pg"] + amp[:, None] * self.d_hair(back["Pg"], t), pose)
        cv.splat(gassy, back["Wg"] * BACK, dark0 + (dark1 - dark0) * back["Cg"][:, None], 0.8)
        amp2 = r0 + r1 * smooth((back["S"] - 0.30) / 1.1)
        points = self.to_world(back["P"] + amp2[:, None] * self.d_hair(back["P"], t), pose)
        cv.splat(
            points[::2],
            back["W"][::2] * 0.22 * BACK,
            dark0 + (dark1 - dark0) * back["C"][::2][:, None],
            3.0,
        )

    def draw(
        self,
        cv,
        t=0.0,
        mouth=0.0,
        blink=0.0,
        gaze=(0.0, 0.0),
        pose=(0.0, 0.0, 0.0, 1.0),
        brow=0.0,
        **kw,
    ):
        parts = kw.get("parts", "all")
        if parts in ("all", "back"):
            self.draw_back(cv, t, pose)
        if parts == "back":
            return
        super().draw(cv, t, mouth, blink, gaze, pose, brow, **kw)
