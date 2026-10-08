"""Idle motion and mouth opening. No Qt here, so the timing can be tested on its own."""

from __future__ import annotations

import math
from dataclasses import dataclass

# Orb, calm face, speech, thinking or a busy model, and the bloom or fold.
ORB_MS = 100
CALM_MS = 50
SPEAK_MS = 33
BUSY_MS = 83
BLOOM_MS = 33

ATTACK_S = 0.040
RELEASE_S = 0.075
MOUTH_GATE = 0.10
MOUTH_SPAN = 0.70
SLOW_ATTACK_S = 0.25
SLOW_RELEASE_S = 0.60


def frame_interval_ms(
    *,
    form: str,
    state: str,
    model_busy: bool,
    transitioning: bool,
) -> int:
    """Timer interval for this pose, in milliseconds."""
    if transitioning or state == "speaking":
        return SPEAK_MS
    if model_busy or state == "thinking":
        return BUSY_MS
    if form == "orb":
        return ORB_MS
    return CALM_MS


def _smooth(u: float) -> float:
    u = 0.0 if u < 0.0 else (1.0 if u > 1.0 else u)
    return u * u * (3.0 - 2.0 * u)


def blink_amount(age: float) -> float:
    """Fast close, short hold, slower open. Age is seconds from the start of the blink."""
    if age <= 0.0:
        return 0.0
    if age < 0.115:
        return _smooth(age / 0.075)
    opened = _smooth((age - 0.115) / 0.14)
    return 1.0 - opened if opened < 1.0 else 0.0


def _hash(index: int, seed: int) -> float:
    n = (int(index) * 374761393 + int(seed) * 668265263) & 0xFFFFFFFF
    n ^= n >> 13
    n = (n * 1274126177) & 0xFFFFFFFF
    return ((n & 0xFFFFFF) / float(0xFFFFFF)) * 2.0 - 1.0


def value_noise(t: float, freq: float, seed: int) -> float:
    """Smooth 1D value noise. Knots are hashed, so the curve does not repeat."""
    x = t * freq
    i = math.floor(x)
    f = x - i
    f = f * f * (3.0 - 2.0 * f)
    return _hash(i, seed) * (1.0 - f) + _hash(i + 1, seed) * f


def fbm(t: float, seed: int, freqs: tuple[float, ...]) -> float:
    total = 0.0
    weight = 0.0
    amp = 1.0
    for step, freq in enumerate(freqs):
        total += amp * value_noise(t, freq, seed + step * 17)
        weight += amp
        amp *= 0.5
    if weight <= 0.0:
        return 0.0
    return total / weight


def _follow(current: float, target: float, dt: float, attack: float, release: float) -> float:
    tau = attack if target > current else release
    if dt <= 0.0 or tau <= 0.0:
        return target
    a = 1.0 - math.exp(-dt / tau)
    return current + a * (target - current)


def mouth_from_follower(level: float) -> float:
    gated = (level - MOUTH_GATE) / MOUTH_SPAN
    gated = 0.0 if gated < 0.0 else (1.0 if gated > 1.0 else gated)
    return 0.95 * (gated**0.85)


@dataclass
class Frame:
    sway_deg: float
    bob: float
    breath: float
    hair_root: float
    hair_mid: float
    hair_tip: float
    wisp_x: float
    wisp_y: float
    gaze_x: float
    gaze_y: float
    star: float
    ring: float
    blink: float
    blink_edge: bool
    mouth: float
    slow: float


class Mouth:
    """Loudness follower: fast open, slow close, lips shut under the gate."""

    def __init__(self, seed: int = 5) -> None:
        self.openness = 0.0
        self.slow = 0.0
        self._level = 0.0
        self._t = 0.0
        self._seed = seed

    def step(self, loudness: float | None, dt: float, *, speaking: bool) -> float:
        dt = 0.0 if dt < 0.0 else float(dt)
        self._t += dt
        if not speaking:
            env = 0.0
        elif loudness is None:
            env = _syllable(self._t, self._seed)
        else:
            env = 0.0 if loudness < 0.0 else (1.0 if loudness > 1.0 else float(loudness))
        self._level = _follow(self._level, env, dt, ATTACK_S, RELEASE_S)
        self.slow = _follow(self.slow, env, dt, SLOW_ATTACK_S, SLOW_RELEASE_S)
        self.openness = mouth_from_follower(self._level) if speaking or self._level > 0.0 else 0.0
        if not speaking:
            self.openness = mouth_from_follower(self._level)
        return self.openness


def _syllable(t: float, seed: int) -> float:
    """A few bumps a second, with short pauses. Noise, not a loop."""
    wave = 0.5 + 0.5 * fbm(t, seed + 3, (3.2, 4.8, 6.4))
    bump = max(0.0, (wave - 0.15) / 0.85) ** 0.9
    pause = fbm(t, seed + 21, (0.6, 1.3, 2.4))
    if pause < -0.48:
        return 0.0
    return max(0.0, min(1.0, 0.25 + 0.75 * bump))


class _Blinks:
    def __init__(self, seed: int) -> None:
        self._seed = seed + 90
        self._next = 1.1 + 1.4 * (0.5 + 0.5 * _hash(1, self._seed))
        self._started: float | None = None
        self._double = False
        self._serial = 2

    def step(self, t: float) -> tuple[float, bool]:
        edge = False
        if self._started is None and t >= self._next:
            self._started = t
            edge = True
            self._double = _hash(self._serial, self._seed) > 0.62
            self._serial += 1
        if self._started is None:
            return 0.0, False
        age = t - self._started
        amount = blink_amount(age)
        if age > 0.27 and amount <= 0.0:
            if self._double:
                self._double = False
                self._started = t
                return blink_amount(0.001), True
            gap = 2.35 + 4.15 * (0.5 + 0.5 * _hash(self._serial, self._seed + 4))
            self._serial += 1
            self._next = t + gap
            self._started = None
            return 0.0, edge
        return amount, edge


class Motion:
    """Continuous sway, breath, hair drift, gaze, blinks, and the mouth."""

    def __init__(self, seed: int = 7) -> None:
        self._seed = int(seed)
        self._mouth = Mouth(seed=seed + 11)
        self._blinks = _Blinks(seed)

    def step(
        self,
        t: float,
        dt: float,
        *,
        state: str,
        speaking: bool,
        model_busy: bool,
        loudness: float | None,
    ) -> Frame:
        calm = 0.72 if state == "thinking" else 1.0
        if model_busy:
            calm *= 0.5
        sway = 0.55 * calm * fbm(t, self._seed + 1, (0.11, 0.23, 0.41, 0.67))
        bob = 0.35 * calm * fbm(t, self._seed + 2, (0.09, 0.19, 0.37))
        breath = calm * fbm(t, self._seed + 3, (0.07, 0.13, 0.29))
        hair_root = 0.25 * calm * fbm(t, self._seed + 4, (0.08, 0.16, 0.33))
        hair_mid = 0.55 * calm * fbm(t, self._seed + 5, (0.1, 0.21, 0.39))
        hair_tip = 1.0 * calm * fbm(t, self._seed + 6, (0.12, 0.22, 0.45, 0.7))
        wisp_x = calm * fbm(t, self._seed + 7, (0.05, 0.11, 0.19))
        wisp_y = calm * fbm(t, self._seed + 8, (0.04, 0.09, 0.17))
        gaze_x = 0.004 * calm * fbm(t, self._seed + 12, (0.08, 0.15, 0.28))
        gaze_y = 0.003 * calm * fbm(t, self._seed + 13, (0.07, 0.14, 0.26))
        if state == "thinking":
            gaze_x += 0.012 * calm
            gaze_y -= 0.01 * calm
        star = 0.82 + 0.18 * (0.5 + 0.5 * fbm(t, self._seed + 14, (0.6, 1.3, 2.1)))
        if state == "thinking":
            star = min(1.35, star + 0.28)
        ring = 0.78 + 0.22 * (0.5 + 0.5 * fbm(t, self._seed + 15, (0.15, 0.33)))
        blink, edge = self._blinks.step(t)
        mouth = self._mouth.step(loudness, dt, speaking=speaking)
        extra = self._mouth.slow if speaking else 0.0
        sway -= 0.25 * extra * calm
        bob += 0.2 * extra * calm
        return Frame(
            sway_deg=max(-0.6, min(0.6, sway)),
            bob=bob,
            breath=breath,
            hair_root=hair_root,
            hair_mid=hair_mid,
            hair_tip=hair_tip,
            wisp_x=wisp_x,
            wisp_y=wisp_y,
            gaze_x=gaze_x,
            gaze_y=gaze_y,
            star=star,
            ring=ring,
            blink=blink,
            blink_edge=edge,
            mouth=mouth,
            slow=self._mouth.slow,
        )
