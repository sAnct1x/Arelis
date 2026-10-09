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
    t: float = 0.0
    # v12 motion. All zero is the approved rest pose.
    wink: float = 0.0
    smile: float = 0.0
    roll_deg: float = 0.0
    nod: float = 0.0
    turn: float = 0.0
    glance: float = 0.0


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
        # The slow envelope drives head sway. A dt=0 push (a state change) must
        # not jump it straight to the target.
        if dt > 0.0:
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


# Head limits. The face is a flat plate, so the turn is only a little parallax
# and a squash; past these it starts to read as a warp.
MAX_ROLL_DEG = 3.0
MAX_NOD = 1.0
MAX_TURN = 1.0
HAIR_REACH = 1.35


def _soft_clip(x: float, limit: float) -> float:
    """Smooth saturation: linear near zero, never a hard stop."""
    return limit * math.tanh(x / limit)


def _bump(age: float, rise: float, hold: float, fall: float) -> float:
    """0 -> 1 -> 0 with eased ends. Zero outside the event, so nothing snaps."""
    if age <= 0.0:
        return 0.0
    if age < rise:
        return _smooth(age / rise)
    age -= rise
    if age < hold:
        return 1.0
    age -= hold
    if age < fall:
        return 1.0 - _smooth(age / fall)
    return 0.0


class _Events:
    """Random, non-periodic events. Each gap is hashed from its own serial."""

    def __init__(self, seed: int, first: float, low: float, high: float) -> None:
        self._seed = seed
        self._serial = 1
        self._low = low
        self._high = high
        self.start: float | None = None
        self.next = first + (high - low) * 0.5 * (0.5 + 0.5 * _hash(0, seed))
        self.size = 1.0

    def roll(self) -> float:
        value = 0.5 + 0.5 * _hash(self._serial, self._seed + 3)
        self._serial += 1
        return value

    def fire(self, t: float, size: float = 1.0) -> None:
        self.start = t
        self.size = size

    def due(self, t: float, allowed: bool) -> bool:
        if t < self.next:
            return False
        gap = self._low + (self._high - self._low) * self.roll()
        self.next = t + gap
        return allowed

    def age(self, t: float) -> float:
        return -1.0 if self.start is None else t - self.start

    def active(self, t: float, length: float) -> bool:
        """Still playing. A new one must not restart it mid-way, or it snaps."""
        return self.start is not None and 0.0 <= t - self.start < length


def _ease_to(current: float, target: float, dt: float, tau: float) -> float:
    """Exponential ease that holds still on dt=0 (a state change mid-frame)."""
    if dt <= 0.0:
        return current
    return current + (1.0 - math.exp(-dt / tau)) * (target - current)


def _follow_abs(current: float, target: float, dt: float, out: float, back: float) -> float:
    """Ease toward target, faster away from zero; holds still on dt=0."""
    tau = out if abs(target) > abs(current) else back
    if dt <= 0.0:
        return current
    return current + (1.0 - math.exp(-dt / tau)) * (target - current)


def wink_amount(age: float) -> float:
    """A wink is a slower, held blink on one eye."""
    return _bump(age, 0.11, 0.16, 0.22)


# Event lengths, so a new event never cuts one that is still playing.
WINK_S = 0.11 + 0.16 + 0.22
NOD_S = 0.32 + 0.10 + 0.55
LOOK_S = 0.7 + 1.6 + 0.9


class Motion:
    """Continuous sway, breath, hair drift, gaze, blinks, and the mouth."""

    def __init__(self, seed: int = 7) -> None:
        self._seed = int(seed)
        self._mouth = Mouth(seed=seed + 11)
        self._blinks = _Blinks(seed)
        # v12: winks, smiles, nods, looks and glances are random events.
        self._winks = _Events(seed + 31, 14.0, 22.0, 70.0)
        self._smiles = _Events(seed + 32, 9.0, 14.0, 34.0)
        self._nods = _Events(seed + 33, 4.0, 5.0, 13.0)
        self._looks = _Events(seed + 34, 6.0, 7.0, 18.0)
        self._glances = _Events(seed + 35, 2.0, 2.2, 6.5)
        self._smile = 0.0
        self._glance = 0.0
        self._glance_to = 0.0
        self._smile_hold = 1.8
        self._look_side = 1.0
        self._was_speaking = False
        self.chat_side = -1.0
        self._calm: float | None = None
        self._hair_rate = 1.0
        self._hair_offset = 0.0
        self._talk = 0.0

    def cue(self, name: str, t: float) -> None:
        """Panel cues: a greeting or a finished reply smiles; tests can wink."""
        if name == "smile":
            self._smiles.fire(t, 1.0)
            self._smile_hold = 2.2
        elif name == "wink" and not self._winks.active(t, WINK_S):
            self._winks.fire(t, 1.0)
        elif name == "nod" and not self._nods.active(t, NOD_S):
            self._nods.fire(t, 1.0)
        elif name == "look" and not self._looks.active(t, LOOK_S):
            self._looks.fire(t, 1.0)
            self._look_side = -self._look_side
        elif name == "glance":
            self._glances.fire(t, 1.0)
            self._glance_to = 0.85 if self._glance_to <= 0.0 else -0.85

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
        goal = 0.72 if state == "thinking" else 1.0
        if model_busy:
            goal *= 0.5
        # Calm eases in and out, so a state change never jumps her pose.
        if self._calm is None:
            self._calm = goal
        self._calm = _ease_to(self._calm, goal, dt, 0.6)
        calm = self._calm
        # Busy hair walks the same noise more slowly, and with less reach. The
        # clock keeps its place when the rate changes, so the hair never skips.
        rate = 0.45 if model_busy else 1.0
        if rate != self._hair_rate:
            self._hair_offset += (self._hair_rate - rate) * t
            self._hair_rate = rate
        hair_t = rate * t + self._hair_offset
        talk_goal = 1.0 if speaking else 0.0
        self._talk = _follow_abs(self._talk, talk_goal, dt, 0.5, 0.8)
        sway = 0.55 * calm * fbm(t, self._seed + 1, (0.11, 0.23, 0.41, 0.67))
        bob = 0.35 * calm * fbm(t, self._seed + 2, (0.09, 0.19, 0.37))
        breath = calm * fbm(t, self._seed + 3, (0.07, 0.13, 0.29))
        hair_root = 0.25 * calm * fbm(hair_t, self._seed + 4, (0.08, 0.16, 0.33))
        hair_mid = 0.55 * calm * fbm(hair_t, self._seed + 5, (0.1, 0.21, 0.39))
        hair_tip = 1.0 * calm * fbm(hair_t, self._seed + 6, (0.12, 0.22, 0.45, 0.7))
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
        # The slow envelope decays on its own after speech, so no snap at the end.
        extra = self._mouth.slow
        sway -= 0.25 * extra * calm
        bob += 0.2 * extra * calm
        lively = not model_busy and state != "thinking"
        head = self._head(t, dt, calm, lively=lively, speaking=speaking)
        # Hair reaches a little further along the same noise. Soft clip, so it
        # eases at the ends of the baked sweep instead of stopping there.
        hair_tip = _soft_clip(HAIR_REACH * hair_tip, 1.0)
        self._was_speaking = speaking
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
            t=t,
            **head,
        )

    def _head(self, t: float, dt: float, calm: float, *, lively: bool, speaking: bool) -> dict:
        """Wink, smile, tilt, nod, turn and glance. Noise plus eased events."""
        seed = self._seed
        # Wink: rare and random, never while she talks or the model works.
        if self._winks.due(t, lively and not speaking and not self._winks.active(t, WINK_S)):
            self._winks.fire(t)
        wink = wink_amount(self._winks.age(t))
        # Smile: cued on a greeting or a finished reply, sometimes when idle.
        if self._smiles.due(t, lively and not speaking):
            self._smiles.fire(t, 0.6 + 0.4 * self._smiles.roll())
            self._smile_hold = 1.2 + 1.8 * self._smiles.roll()
        target = self._smiles.size * _bump(self._smiles.age(t), 0.0, self._smile_hold, 0.0)
        if not lively:
            target *= 0.4
        self._smile = _follow_abs(self._smile, target, dt, 0.35, 0.70)
        smile = max(0.0, min(1.0, self._smile))
        # Tilt: slow noise, a little more while smiling.
        roll = 2.1 * calm * fbm(t, seed + 41, (0.045, 0.10, 0.21)) + 0.9 * smile
        # Nods: an occasional dip and lift; small, more often while talking.
        if self._nods.due(t, lively and not self._nods.active(t, NOD_S)):
            self._nods.fire(t, 0.55 + 0.45 * self._nods.roll())
        if speaking and self._nods.next - t > 4.0:
            self._nods.next = t + 1.6 + 2.4 * self._nods.roll()
        nod = self._nods.size * _bump(self._nods.age(t), 0.32, 0.10, 0.55)  # NOD_S
        nod = nod * calm + 0.18 * calm * fbm(t, seed + 42, (0.07, 0.15))
        # Turn: slow drift plus a look to one side now and then; toward the chat
        # while she speaks.
        if self._looks.due(t, lively and not speaking and not self._looks.active(t, LOOK_S)):
            self._looks.fire(t)
            self._look_side = 1.0 if self._looks.roll() > 0.5 else -1.0
        look = self._look_side * _bump(self._looks.age(t), 0.7, 1.6, 0.9)
        turn = 0.35 * calm * fbm(t, seed + 43, (0.03, 0.07, 0.13)) + 0.75 * calm * look
        turn += 0.45 * self.chat_side * self._talk * calm
        # Glance: a saccade (fast), a hold, then settle back (slower).
        if self._glances.due(t, True):
            side = 1.0 if self._glances.roll() > 0.5 else -1.0
            self._glances.fire(t, 0.55 + 0.45 * self._glances.roll())
            self._glance_to = side
        aim = self._glance_to * self._glances.size * _bump(self._glances.age(t), 0.0, 0.7, 0.0)
        if speaking:
            # Mostly toward the chat, back to the user between glances.
            aim = 0.8 * self.chat_side * self._talk if abs(aim) < 0.01 else aim * 0.5
        if look:
            aim += 0.6 * look
        aim *= (0.5 + 0.5 * calm) * (1.0 - wink)
        # Out fast (a saccade), back slower (the settle).
        self._glance = _follow_abs(self._glance, aim, dt, 0.045, 0.16)
        return {
            "wink": wink,
            "smile": smile,
            "roll_deg": _soft_clip(roll, MAX_ROLL_DEG),
            "nod": _soft_clip(nod, MAX_NOD),
            "turn": _soft_clip(turn, MAX_TURN),
            "glance": max(-1.0, min(1.0, self._glance)),
        }
