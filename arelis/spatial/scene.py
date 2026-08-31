"""One sphere. Free, it falls on the plane. Held, z is size. Disc stays a 2D type."""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache

from arelis.spatial.depth import world_to_apparent

NEAR_SLACK = 0.04
TRAIL_WINDOW = 0.10
# Keep the flick even if unpinch lands late.
PEAK_HOLD = 0.40
REGRAB_LOCK = 0.16
# World is 0-1. A still hand jitters well below this; a flick does not.
STILL_SPEED = 0.45
RESTITUTION = 0.72
MASS = 1.0
MASS_MIN = 0.25
MASS_MAX = 8.0
MASS_STEP = 1.6
# Last released body still counts as "this" for a spoken verb.
LAST_BIND = 2.0
# World is 0–1, +y is down (image space). 2.4 makes a drop from center
# take ~0.6 s and a flick arc before the floor — not 9.81 in fake metres.
GRAVITY = 2.4
# After a bounce, park if the outgoing normal speed is this small.
# Stops gravity+restitution from micro-bouncing on the floor forever.
REST_SPEED = 0.15
# Take 20260823T215537Z: six pose gaps > 80 ms, max 208 ms. Held
# bodies sat still, then jumped. Keep last pointer velocity for
# that beat. Do not invent motion after a quarter second.
HITCH_GAP = 0.045
HITCH_HOLD = 0.25
# World units / s. Caps a resume teleport; ordinary motion fits.
XY_SLEW = 2.0
RADIUS_MIN = 0.035
RADIUS_MAX = 0.28
SCALE_SPAN_MIN = 0.02
# Two pinch points closer than this are the same hand (MediaPipe Left+Right).
SCALE_PAIR_MIN = 0.10
# Per finished frame, not vs the join span. Join-relative scale
# made grow easy and shrink after a grow almost impossible.
SCALE_RATIO_MIN = 0.92
SCALE_RATIO_MAX = 1.08
# How far past the disc a pinch may sit and still count. 0.34 used to
# pair a ghost second hand across a third of the world.
SCALE_REACH = 0.12
# One dropped scaler frame must not end the stretch — MediaPipe does that.
SCALE_HOLD = 0.12
# Pinch the rim, not the face. Band grows with the disc so a small
# one stays hittable and a large one still has an interior miss.
RIM_BAND = 0.04
RIM_FRAC = 0.50
# C920 FOV is wide; 1:1 image→world feels like a low-DPI mouse.
REACH_DEFAULT = 1.45
REACH_MIN = 1.00
REACH_MAX = 2.50
BODY_CAP = 12
# Regular n-gons. Sphere stays a circle (sides 0).
SPAWN_KINDS: tuple[tuple[str, int], ...] = (
    ("triangle", 3),
    ("square", 4),
    ("pentagon", 5),
    ("hexagon", 6),
    ("octagon", 8),
    ("sphere", 0),
)


def clamp_reach(reach: float) -> float:
    return min(REACH_MAX, max(REACH_MIN, float(reach)))


@lru_cache(maxsize=64)
def _gain_k(gain: float) -> float:
    """k such that the tanh remap has slope `gain` at the frame center.

    0.5 * k / tanh(k/2) = gain. Linear gain + clamp used to park the
    outer ~15% of the C920 on the world wall (take 20260823T054502Z).
    """
    if gain <= 1.0:
        return 0.0
    target = 2.0 * gain
    k = 2.0 * gain
    for _ in range(16):
        half = 0.5 * k
        th = math.tanh(half)
        if abs(th) < 1e-12:
            return 0.0
        sech2 = 1.0 - th * th
        f = k / th - target
        df = (th - half * sech2) / (th * th)
        if abs(df) < 1e-12:
            break
        k -= f / df
        if k < 1e-6:
            k = 1e-6
        if abs(f) < 1e-12:
            break
    return k


def _remap_axis(u: float, gain: float) -> float:
    """Map a 0–1 sensor axis onto 0–1. Center slope is gain; the rim still moves."""
    v = min(1.0, max(0.0, float(u)))
    if gain <= 1.0 + 1e-9:
        return v
    k = _gain_k(gain)
    scale = math.tanh(0.5 * k)
    if scale < 1e-12:
        return v
    return 0.5 + 0.5 * math.tanh(k * (v - 0.5)) / scale


def image_to_world(
    x: float, y: float, *, reach: float = REACH_DEFAULT
) -> tuple[float, float]:
    """Sensor x → operator x.

    The C920 is not a mirror. You face it, so image +x is your right.
    The world is your body: move left, the disc goes left. Invert x.
    y stays sensor-up (image +y is down; we keep that so a raised
    hand still goes up once the preview is also mirrored).

    reach > 1 amplifies around the frame center so a small hand move
    covers more of the plane. The curve still uses the whole sensor —
    linear gain used to clamp the rim to the wall. Mouse on the world
    is still 1:1 pixels.
    """
    gain = clamp_reach(reach)
    return (
        _remap_axis(1.0 - float(x), gain),
        _remap_axis(float(y), gain),
    )


def _starter_bodies() -> list[Disc]:
    """One sphere. The plane discs were rung 1–2. This body can fall."""
    return [Disc(x=0.50, y=0.50, z=0.42, radius=0.14, kind="sphere")]


@dataclass
class Disc:
    x: float = 0.50
    y: float = 0.50
    z: float = 0.50
    radius: float = 0.08
    kind: str = "disc"
    attached: bool = False
    holder: str = ""
    scaler: str = ""
    vx: float = 0.0
    vy: float = 0.0
    last_release_speed: float = 0.0
    mass: float = MASS
    frozen: bool = False
    size_locked: bool = False
    axes_on: bool = False
    _trail: deque[tuple[float, float, float]] = field(
        default_factory=lambda: deque(maxlen=24)
    )
    _peak_vx: float = 0.0
    _peak_vy: float = 0.0
    _peak_speed: float = 0.0
    _peak_t: float = 0.0
    _released_at: float = -1.0
    _last_holder: str = ""
    _scale_last: float = 0.0
    _scale_seen: set[str] = field(default_factory=set)
    _hold_dx: float = 0.0
    _hold_dy: float = 0.0
    _hold_dz: float = 0.0
    _scaler_lost_at: float = -1.0
    _pointer_t: float = -1.0
    _pointer_wall: float = -1.0
    _hitch_vx: float = 0.0
    _hitch_vy: float = 0.0
    sides: int = 0
    angle: float = 0.0
    tilt: float = 0.0
    _spin_last: float | None = None
    _orbit_last: float | None = None
    _tilt_last: float | None = None


def polygon_xy(body: Disc) -> list[tuple[float, float]]:
    """Regular n-gon in the plane. Empty for a circle."""
    n = int(body.sides)
    if n < 3:
        return []
    pts: list[tuple[float, float]] = []
    r = float(body.radius)
    spin = float(body.angle) - math.pi / 2.0
    for i in range(n):
        a = spin + 2.0 * math.pi * i / n
        pts.append((body.x + r * math.cos(a), body.y + r * math.sin(a)))
    return pts


def spin_mark_xy(body: Disc) -> tuple[float, float]:
    """A pip on the rim so a sphere can show spin. Tilt pulls it inward."""
    reach = float(body.radius) * max(0.38, abs(math.cos(float(body.tilt))))
    a = float(body.angle) - math.pi / 2.0
    return (body.x + reach * math.cos(a), body.y + reach * math.sin(a))


def _wrap(delta: float) -> float:
    while delta > math.pi:
        delta -= 2.0 * math.pi
    while delta < -math.pi:
        delta += 2.0 * math.pi
    return delta


@dataclass
class WorldScene:
    """Bodies on one plane. A fist near one grabs. Two pinches stretch that one."""

    bodies: list[Disc] = field(default_factory=_starter_bodies)
    last_release_speed: float = 0.0
    last_energy: float = 0.0
    last_verb: str = ""
    _hit: Disc | None = field(default=None, repr=False)
    _pz: float | None = field(default=None, repr=False)
    _p_ang: float | None = field(default=None, repr=False)
    _grips: dict[str, tuple[float, float]] = field(default_factory=dict)
    _grip_kind: dict[str, str] = field(default_factory=dict)
    _undo: list[dict] = field(default_factory=list)
    gravity: bool = True
    selected: Disc | None = field(default=None, repr=False)
    _grip_z: dict[str, float] = field(default_factory=dict)

    @property
    def disc(self) -> Disc:
        if self._hit is not None:
            return self._hit
        if self.bodies:
            return self.bodies[0]
        raise RuntimeError("world is empty")

    def _bind(self, px: float, py: float, owner: str, pose: str) -> None:
        """Pick the body this pointer is on. A miss is none, not disc 0."""
        self._hit = None
        if owner:
            for body in self.bodies:
                if body.holder == owner or body.scaler == owner:
                    self._hit = body
                    return
        else:
            for body in self.bodies:
                if body.attached and not body.holder:
                    self._hit = body
                    return
        if pose == "open":
            return
        reach = NEAR_SLACK if pose == "fist" else SCALE_REACH
        best: Disc | None = None
        best_d = 1e9
        for body in self.bodies:
            dist = self._sep(body, px, py)
            if dist <= self._touch_radius(body) + reach and dist < best_d:
                best = body
                best_d = dist
        self._hit = best

    def spawn(self, kind: str) -> Disc | None:
        """Drop a body near center. None if the box is full or the kind is unknown."""
        name = str(kind or "").strip().lower()
        sides = next((count for label, count in SPAWN_KINDS if label == name), None)
        if sides is None:
            return None
        if len(self.bodies) >= BODY_CAP:
            return None
        radius = 0.10 if sides else 0.12
        x, y = 0.50, 0.36
        for step in range(12):
            gx = 0.50 + 0.07 * ((step % 4) - 1.5)
            gy = 0.36 + 0.07 * (step // 4)
            if all(
                math.hypot(gx - body.x, gy - body.y)
                >= radius + self._touch_radius(body) + 0.01
                for body in self.bodies
            ):
                x, y = gx, gy
                break
        body = Disc(
            x=x,
            y=y,
            z=0.42,
            radius=radius,
            kind=name if sides else "sphere",
            sides=sides,
        )
        self.bodies.append(body)
        return body

    def set_gravity(self, on: bool) -> None:
        """Room g. Off hangs unheld bodies so you can place. Not per-body freeze."""
        self.gravity = bool(on)
        if self.gravity:
            return
        for body in self.bodies:
            if body.attached or body.frozen:
                continue
            body.vy = 0.0

    def body_at(self, x: float, y: float) -> Disc | None:
        """Topmost body under the pointer. Last spawned wins a tie."""
        px, py = float(x), float(y)
        hit: Disc | None = None
        for body in self.bodies:
            if self._sep(body, px, py) <= self._touch_radius(body) + NEAR_SLACK:
                hit = body
        return hit

    def select_at(self, x: float, y: float) -> Disc | None:
        self.selected = self.body_at(x, y)
        return self.selected

    def delete(self, body: Disc | None = None) -> bool:
        """Remove a body. An empty box is valid — do not respawn."""
        target = body if body is not None else self.selected
        if target is None or target not in self.bodies:
            return False
        if target.attached:
            who = target.holder or target.scaler
            self.drop(who=who)
        self.bodies.remove(target)
        if self.selected is target:
            self.selected = None
        return True

    def _sep(self, body: Disc, px: float, py: float) -> float:
        """Pick in the plane. z is for place, not hit — a desk z is never 0.42."""
        return math.hypot(px - body.x, py - body.y)

    def _touch_radius(self, body: Disc) -> float:
        """The silhouette you can hit. Never smaller than the solid body."""
        if body.kind == "sphere":
            return max(body.radius, world_to_apparent(body.radius, body.z))
        return body.radius

    def _lock_hold(self) -> None:
        """Snap xy to the pointer. Keep z so a far estimator does not leap."""
        self._hold_dx = 0.0
        self._hold_dy = 0.0
        if self.disc.kind == "sphere" and self._pz is not None:
            self._hold_dz = self.disc.z - self._pz
        else:
            self._hold_dz = 0.0

    def _body_for(self, owner: str) -> Disc | None:
        if not owner:
            return None
        for body in self.bodies:
            if body.holder == owner or body.scaler == owner:
                return body
        return None

    def held_names(self) -> set[str]:
        names: set[str] = set()
        for body in self.bodies:
            if body.holder:
                names.add(body.holder)
            if body.scaler:
                names.add(body.scaler)
        return names

    def target(self, t: float | None = None) -> Disc | None:
        """The referent of “this”. One held body, or the last drop within τ.

        Two held at once is unbound — do not guess.
        """
        held = [body for body in self.bodies if body.attached]
        if len(held) == 1:
            return held[0]
        if len(held) > 1:
            return None
        now = time.perf_counter() if t is None else float(t)
        best: Disc | None = None
        best_at = -1.0
        for body in self.bodies:
            if body._released_at >= 0 and now - body._released_at <= LAST_BIND:
                if body._released_at >= best_at:
                    best = body
                    best_at = body._released_at
        return best

    def apply_verb(self, verb: str, t: float | None = None) -> dict | None:
        """Mutate the bound body this frame. None if nothing is selected."""
        name = str(verb or "").strip().lower()
        if name == "undo":
            return self._pop_undo()
        body = self.target(t)
        if body is None:
            self.last_verb = ""
            return None
        self._push_undo(body)
        if name == "heavier":
            body.mass = min(MASS_MAX, body.mass * MASS_STEP)
        elif name == "lighter":
            body.mass = max(MASS_MIN, body.mass / MASS_STEP)
        elif name == "freeze":
            body.frozen = True
            if not body.attached:
                body.vx = 0.0
                body.vy = 0.0
        elif name == "unfreeze":
            body.frozen = False
        else:
            self._undo.pop()
            self.last_verb = ""
            return None
        self.last_verb = name
        return {
            "verb": name,
            "mass": body.mass,
            "frozen": body.frozen,
        }

    def _body_index(self, body: Disc) -> int:
        for i, item in enumerate(self.bodies):
            if item is body:
                return i
        return 0

    def _push_undo(self, body: Disc) -> None:
        self._undo.append(
            {
                "i": self._body_index(body),
                "mass": body.mass,
                "frozen": body.frozen,
                "vx": body.vx,
                "vy": body.vy,
                "x": body.x,
                "y": body.y,
                "z": body.z,
            }
        )
        if len(self._undo) > 24:
            self._undo.pop(0)

    def _pop_undo(self) -> dict | None:
        if not self._undo:
            self.last_verb = ""
            return None
        snap = self._undo.pop()
        i = int(snap.get("i") or 0)
        if i < 0 or i >= len(self.bodies):
            self.last_verb = ""
            return None
        body = self.bodies[i]
        body.mass = float(snap["mass"])
        body.frozen = bool(snap["frozen"])
        body.vx = float(snap["vx"])
        body.vy = float(snap["vy"])
        body.x = float(snap["x"])
        body.y = float(snap["y"])
        body.z = float(snap.get("z", body.z))
        self.last_verb = "undo"
        return {"verb": "undo", "mass": body.mass, "frozen": body.frozen}

    @property
    def _trail(self):
        return self.disc._trail

    @property
    def _peak_vx(self) -> float:
        return self.disc._peak_vx

    @_peak_vx.setter
    def _peak_vx(self, value: float) -> None:
        self.disc._peak_vx = value

    @property
    def _peak_vy(self) -> float:
        return self.disc._peak_vy

    @_peak_vy.setter
    def _peak_vy(self, value: float) -> None:
        self.disc._peak_vy = value

    @property
    def _peak_speed(self) -> float:
        return self.disc._peak_speed

    @_peak_speed.setter
    def _peak_speed(self, value: float) -> None:
        self.disc._peak_speed = value

    @property
    def _peak_t(self) -> float:
        return self.disc._peak_t

    @_peak_t.setter
    def _peak_t(self, value: float) -> None:
        self.disc._peak_t = value

    @property
    def _released_at(self) -> float:
        return self.disc._released_at

    @_released_at.setter
    def _released_at(self, value: float) -> None:
        self.disc._released_at = value

    @property
    def _last_holder(self) -> str:
        return self.disc._last_holder

    @_last_holder.setter
    def _last_holder(self, value: str) -> None:
        self.disc._last_holder = value

    @property
    def _scale_last(self) -> float:
        return self.disc._scale_last

    @_scale_last.setter
    def _scale_last(self, value: float) -> None:
        self.disc._scale_last = value

    @property
    def _scale_seen(self) -> set[str]:
        return self.disc._scale_seen

    @_scale_seen.setter
    def _scale_seen(self, value: set[str]) -> None:
        self.disc._scale_seen = value

    @property
    def _hold_dx(self) -> float:
        return self.disc._hold_dx

    @_hold_dx.setter
    def _hold_dx(self, value: float) -> None:
        self.disc._hold_dx = value

    @property
    def _hold_dy(self) -> float:
        return self.disc._hold_dy

    @_hold_dy.setter
    def _hold_dy(self, value: float) -> None:
        self.disc._hold_dy = value

    @property
    def _hold_dz(self) -> float:
        return self.disc._hold_dz

    @_hold_dz.setter
    def _hold_dz(self, value: float) -> None:
        self.disc._hold_dz = value

    @property
    def _scaler_lost_at(self) -> float:
        return self.disc._scaler_lost_at

    @_scaler_lost_at.setter
    def _scaler_lost_at(self, value: float) -> None:
        self.disc._scaler_lost_at = value

    def apply_pointer(
        self,
        x: float,
        y: float,
        grabbing: bool,
        t: float | None = None,
        *,
        who: str = "",
        kind: str | None = None,
        z: float | None = None,
        angle: float | None = None,
    ) -> None:
        now = time.perf_counter() if t is None else float(t)
        px = min(1.0, max(0.0, float(x)))
        py = min(1.0, max(0.0, float(y)))
        self._pz = None if z is None else min(1.0, max(0.0, float(z)))
        self._p_ang = None if angle is None else float(angle)
        owner = str(who or "")
        pose = (kind or ("fist" if grabbing else "open")).lower()
        if pose not in ("open", "fist", "pinch"):
            pose = "fist" if grabbing else "open"
        self._expire_lost_scaler(now)
        if not self.bodies:
            return
        self._bind(px, py, owner, pose)
        try:
            if pose == "fist":
                self._apply_fist(px, py, owner, now)
            elif pose == "pinch":
                self._apply_pinch(px, py, owner, now)
            else:
                self._apply_open(owner, now)
        finally:
            self._hit = None
            self._pz = None
            self._p_ang = None

    def _mark_grip(self, owner: str, px: float, py: float, pose: str) -> None:
        if owner:
            self._grips[owner] = (px, py)
            self._grip_kind[owner] = pose
            if self._pz is not None:
                self._grip_z[owner] = self._pz

    def _clear_spin(self, body: Disc) -> None:
        body._spin_last = None
        body._orbit_last = None
        body._tilt_last = None

    def _follow_fist(self, px: float, py: float, now: float) -> None:
        hitch_dt = 0.0
        if self.disc._pointer_t >= 0:
            hitch_dt = now - self.disc._pointer_t
        self._place_held(px, py, hitch_dt=hitch_dt)
        self.disc.vx = 0.0
        self.disc.vy = 0.0
        self._trail.append((now, self.disc.x, self.disc.y))
        self._note_peak(now)
        self._mark_pointer(now)

    def _apply_fist(self, px: float, py: float, owner: str, now: float) -> None:
        if self._hit is None:
            return
        if self.disc.attached:
            if owner and owner == self.disc.scaler:
                return
            if owner and owner == self.disc.holder:
                self._mark_grip(owner, px, py, "fist")
                if self.disc.scaler:
                    return
                self._follow_fist(px, py, now)
                self._apply_fist_turn()
                return
            if owner and self.disc.holder and owner != self.disc.holder:
                return
            if owner and not self.disc.holder:
                if not self.near(px, py):
                    return
                self._mark_grip(owner, px, py, "fist")
                self.disc.holder = owner
                self._lock_hold()
                self._follow_fist(px, py, now)
                self._apply_fist_turn()
                return
        elif not self.near(px, py):
            return
        elif (
            owner
            and owner == self._last_holder
            and self._released_at >= 0
            and now - self._released_at < REGRAB_LOCK
        ):
            return
        self._mark_grip(owner, px, py, "fist")
        if not self.disc.attached:
            self._trail.clear()
            self._clear_peak()
            self._clear_hitch()
            self._clear_spin(self.disc)
            self.disc.holder = owner
            self._lock_hold()
        self.disc.attached = True
        self._follow_fist(px, py, now)
        self._apply_fist_turn()

    def _apply_fist_turn(self) -> None:
        """Palm angle delta. Fist rotate; pinch does not call this."""
        ang = self._p_ang
        if ang is None:
            return
        if self.disc._spin_last is not None:
            self.disc.angle += _wrap(ang - self.disc._spin_last)
        self.disc._spin_last = ang

    def _apply_pinch(self, px: float, py: float, owner: str, now: float) -> None:
        if self._hit is None:
            return
        if self.disc.attached:
            if self._grip_kind.get(self.disc.holder) == "fist":
                return
            if owner and owner == self.disc.scaler:
                self._scaler_lost_at = -1.0
                self._mark_grip(owner, px, py, "pinch")
                self._note_scale_hand(owner, now)
                return
            if owner and owner == self.disc.holder:
                self._mark_grip(owner, px, py, "pinch")
                if self.disc.scaler:
                    self._note_scale_hand(owner, now)
                elif self.disc.size_locked:
                    self._orbit_spin(px, py)
                else:
                    self._follow_fist(px, py, now)
                return
            if (
                owner
                and self.disc.holder
                and owner != self.disc.holder
                and self._grip_kind.get(self.disc.holder) == "pinch"
                and not self.disc.scaler
                and self._can_join_scale(px, py)
            ):
                self._mark_grip(owner, px, py, "pinch")
                self.disc.scaler = owner
                self._scaler_lost_at = -1.0
                self._begin_scale()
                self._scale_seen = {self.disc.holder, owner}
                self._update_scale(now)
                self._scale_seen.clear()
            return
        if not owner:
            return
        if not self._pinch_in_reach(px, py):
            return
        if self.disc.size_locked:
            self._mark_grip(owner, px, py, "pinch")
            partner = self._other_pinch(owner, px, py)
            if partner is None:
                self._orbit_spin(px, py)
                return
            self.disc.attached = True
            self.disc.holder = partner
            self.disc.scaler = owner
            self.disc.vx = 0.0
            self.disc.vy = 0.0
            self._lock_hold()
            self._scaler_lost_at = -1.0
            self._begin_scale()
            self._update_scale(now)
            return
        partner = self._other_pinch(owner, px, py)
        if partner is None:
            self._replace_close_pending(owner, px, py)
            if not self.near(px, py):
                self._mark_grip(owner, px, py, "pinch")
                return
            if (
                owner
                and owner == self._last_holder
                and self._released_at >= 0
                and now - self._released_at < REGRAB_LOCK
            ):
                return
            self._mark_grip(owner, px, py, "pinch")
            if not self.disc.attached:
                self._trail.clear()
                self._clear_peak()
                self._clear_hitch()
                self._clear_spin(self.disc)
                self.disc.holder = owner
                self._lock_hold()
            self.disc.attached = True
            self._follow_fist(px, py, now)
            return
        self._mark_grip(owner, px, py, "pinch")
        self.disc.attached = True
        self.disc.holder = partner
        self.disc.scaler = owner
        self.disc.vx = 0.0
        self.disc.vy = 0.0
        self._lock_hold()
        self._scaler_lost_at = -1.0
        self._begin_scale()
        self._update_scale(now)

    def _orbit_spin(self, px: float, py: float) -> None:
        """Size locked: one pinch orbits the rim. Does not grab or grow."""
        dx = px - self.disc.x
        dy = py - self.disc.y
        if math.hypot(dx, dy) < 1e-6:
            return
        ang = math.atan2(dy, dx)
        if self.disc._orbit_last is not None:
            self.disc.angle += _wrap(ang - self.disc._orbit_last)
        self.disc._orbit_last = ang

    def _pair_span_max(self) -> float:
        return 2.0 * (self.disc.radius + SCALE_REACH)

    def _pinch_in_reach(self, x: float, y: float) -> bool:
        return self._sep(self.disc, x, y) <= self._touch_radius(self.disc) + SCALE_REACH

    def _other_pinch(
        self, owner: str, px: float, py: float
    ) -> str | None:
        """A second pinch, far enough to be another hand, still on this disc."""
        for who, pose in self._grip_kind.items():
            if who == owner or pose != "pinch":
                continue
            grip = self._grips.get(who)
            if grip is None:
                continue
            if not self._pinch_in_reach(*grip):
                continue
            span = math.hypot(px - grip[0], py - grip[1])
            if SCALE_PAIR_MIN <= span <= self._pair_span_max():
                return who
        return None

    def _replace_close_pending(self, owner: str, px: float, py: float) -> None:
        """Same body, new label. Do not keep both as a stretch pair."""
        for who, pose in list(self._grip_kind.items()):
            if who == owner or pose != "pinch":
                continue
            if who in self.held_names():
                continue
            grip = self._grips.get(who)
            if grip is None:
                continue
            if math.hypot(px - grip[0], py - grip[1]) < SCALE_PAIR_MIN:
                self._pop_hands(who)

    def forget_pending(self, owner: str) -> None:
        if not owner or owner in self.held_names():
            return
        self._pop_hands(owner)

    def forget_absent(self, live: set[str], t: float) -> None:
        """Grips whose hand is gone this frame are not a secret second pinch."""
        names = set(self._grips) | self.held_names()
        for who in names:
            if not who or who in live:
                continue
            if who in self.held_names():
                self.drop(t=t, who=who)
            else:
                self.forget_pending(who)

    def _pop_hands(self, *names: str) -> None:
        for name in names:
            if name:
                self._grips.pop(name, None)
                self._grip_kind.pop(name, None)
                self._grip_z.pop(name, None)

    def _apply_open(self, owner: str, now: float) -> None:
        if owner:
            held = self._body_for(owner)
            if held is None:
                self._pop_hands(owner)
                for body in self.bodies:
                    if not body.attached:
                        body._orbit_last = None
                return
            self._hit = held
        if self._hit is None:
            if owner:
                self._pop_hands(owner)
            return
        self._clear_spin(self.disc)
        if owner and not self.disc.attached:
            self._pop_hands(owner)
            return
        if not self.disc.attached:
            return
        if self.disc.scaler and owner and owner == self.disc.scaler:
            self._end_scale()
            self._pop_hands(owner)
            if self._grip_kind.get(self.disc.holder) == "pinch" or not self.disc.holder:
                holder = self.disc.holder
                self.disc.attached = False
                self.disc.holder = ""
                self._pop_hands(holder)
            return
        if self.disc.scaler and owner and owner == self.disc.holder:
            scaler = self.disc.scaler
            self._end_scale()
            self.disc.attached = False
            self.disc.holder = ""
            self._pop_hands(owner, scaler)
            return
        if self.disc.holder and owner and self.disc.holder != owner:
            self._pop_hands(owner)
            return
        if self.disc.holder or not self.disc.scaler:
            self._release(now)
        holder, scaler = self.disc.holder, self.disc.scaler
        self.disc.attached = False
        self.disc.holder = ""
        self._end_scale()
        self._pop_hands(holder, scaler)

    def is_flicking(self, who: str = "") -> bool:
        """A still twist must not throw; a sling must."""
        if who:
            body = self._body_for(who)
        elif self.bodies:
            body = self.disc
        else:
            return False
        if body is None:
            if not self.bodies:
                return False
            body = self.disc
        return body._peak_speed >= STILL_SPEED

    def near(self, x: float, y: float) -> bool:
        if not self.bodies:
            return False
        return self._sep(self.disc, x, y) <= self._touch_radius(self.disc) + NEAR_SLACK

    def near_any(self, x: float, y: float) -> bool:
        px, py = float(x), float(y)
        for body in self.bodies:
            dist = math.hypot(px - body.x, py - body.y)
            if dist <= self._touch_radius(body) + NEAR_SLACK:
                return True
        return False

    def on_rim(self, x: float, y: float) -> bool:
        if not self.bodies:
            return False
        dist = math.hypot(float(x) - self.disc.x, float(y) - self.disc.y)
        band = max(RIM_BAND, self.disc.radius * RIM_FRAC)
        return abs(dist - self.disc.radius) <= band

    def _can_join_scale(self, x: float, y: float) -> bool:
        if not self._pinch_in_reach(x, y):
            return False
        holder = self._grips.get(self.disc.holder)
        if holder is None:
            return False
        span = math.hypot(float(x) - holder[0], float(y) - holder[1])
        return SCALE_PAIR_MIN <= span <= self._pair_span_max()

    def _place_held(self, px: float, py: float, *, hitch_dt: float = 0.0) -> None:
        lo = self.disc.radius
        hi = 1.0 - self.disc.radius
        tx = min(hi, max(lo, px + self._hold_dx))
        ty = min(hi, max(lo, py + self._hold_dy))
        if hitch_dt > HITCH_GAP:
            dist = math.hypot(tx - self.disc.x, ty - self.disc.y)
            cap = XY_SLEW * hitch_dt
            if dist > cap > 0:
                s = cap / dist
                tx = self.disc.x + (tx - self.disc.x) * s
                ty = self.disc.y + (ty - self.disc.y) * s
        self.disc.x = tx
        self.disc.y = ty
        if (
            self.disc.kind == "sphere"
            and self._pz is not None
            and not self.disc.size_locked
        ):
            # z is depth, not a plane radius. [r, 1-r] parked the ball mid-box.
            self.disc.z = min(1.0, max(0.0, self._pz + self._hold_dz))

    def _mark_pointer(self, now: float) -> None:
        """Last pointer + trail velocity. step() coasts that across a pose hitch."""
        self.disc._pointer_t = now
        self.disc._pointer_wall = time.perf_counter()
        vx, vy = self._trail_velocity(now)
        self.disc._hitch_vx = vx
        self.disc._hitch_vy = vy

    def _clear_hitch(self) -> None:
        self.disc._pointer_t = -1.0
        self.disc._pointer_wall = -1.0
        self.disc._hitch_vx = 0.0
        self.disc._hitch_vy = 0.0

    def _expire_lost_scaler(self, now: float) -> None:
        for body in list(self.bodies):
            self._hit = body
            if (
                self.disc.scaler
                and self._scaler_lost_at >= 0
                and now - self._scaler_lost_at > SCALE_HOLD
            ):
                holder = self.disc.holder
                scaler = self.disc.scaler
                self._end_scale()
                self._scaler_lost_at = -1.0
                if self._grip_kind.get(holder) != "fist":
                    self.disc.attached = False
                    self.disc.holder = ""
                    self._pop_hands(holder, scaler)
        self._hit = None

    def drop(self, t: float | None = None, *, who: str = "") -> None:
        """Detach. A lost scaler just leaves scale; a lost fist throws."""
        now = time.perf_counter() if t is None else float(t)
        if who:
            body = self._body_for(who)
            if body is None:
                self._pop_hands(who)
                return
            self._hit = body
            try:
                self._drop_hit(now, who=who)
            finally:
                self._hit = None
            return
        for body in self.bodies:
            self._hit = body
            self._drop_hit(now, who="")
        self._hit = None

    def _drop_hit(self, now: float, *, who: str) -> None:
        if who and self.disc.scaler and who == self.disc.scaler:
            if self._scaler_lost_at < 0:
                self._scaler_lost_at = now
            return
        if who and self.disc.scaler and who == self.disc.holder:
            holder, scaler = self.disc.holder, self.disc.scaler
            if self._grip_kind.get(who) == "pinch":
                self.disc.attached = False
                self.disc.holder = ""
                self._end_scale()
                self._pop_hands(holder, scaler)
                return
            self._release(now)
            self.disc.attached = False
            self.disc.holder = ""
            self._end_scale()
            self._pop_hands(holder, scaler)
            return
        holder, scaler = self.disc.holder, self.disc.scaler
        if self.disc.attached:
            self._release(now)
        self.disc.attached = False
        self.disc.holder = ""
        self._end_scale()
        self._pop_hands(holder, scaler)

    def energy(self, body: Disc | None = None) -> float:
        """Mechanical E = KE + PE. Floor is y = 1 − radius. Engine, not the 9B."""
        disc = body
        if disc is None:
            if not self.bodies:
                return 0.0
            disc = self.disc
        ke = 0.5 * disc.mass * (disc.vx**2 + disc.vy**2)
        height = max(0.0, (1.0 - disc.radius) - disc.y)
        pe = disc.mass * GRAVITY * height
        return ke + pe

    def _body_log(self, body: Disc) -> dict:
        return {
            "x": round(body.x, 6),
            "y": round(body.y, 6),
            "z": round(body.z, 6),
            "kind": body.kind,
            "vx": round(body.vx, 6),
            "vy": round(body.vy, 6),
            "r": round(body.radius, 6),
            "attached": body.attached,
            "holder": body.holder,
            "scaler": body.scaler,
            "mass": round(body.mass, 4),
            "frozen": body.frozen,
            "sides": body.sides,
            "angle": round(body.angle, 6),
            "tilt": round(body.tilt, 6),
            "size_locked": body.size_locked,
            "axes_on": body.axes_on,
            "energy": round(self.energy(body), 8),
        }

    def to_log(self) -> dict:
        """One row for a take. If it is not in a take, it did not happen."""
        bodies = [self._body_log(body) for body in self.bodies]
        if bodies:
            first = dict(bodies[0])
        else:
            first = {
                "x": 0.0,
                "y": 0.0,
                "z": 0.0,
                "kind": "",
                "vx": 0.0,
                "vy": 0.0,
                "r": 0.0,
                "attached": False,
                "holder": "",
                "scaler": "",
                "mass": 0.0,
                "frozen": False,
                "sides": 0,
                "angle": 0.0,
                "tilt": 0.0,
                "size_locked": False,
                "axes_on": False,
                "energy": 0.0,
            }
        first["bodies"] = bodies
        first["verb"] = self.last_verb
        first["gravity"] = self.gravity
        return first

    def reset(self) -> None:
        self.bodies = _starter_bodies()
        self._hit = None
        self.last_release_speed = 0.0
        self.last_energy = 0.0
        self.last_verb = ""
        self._grips.clear()
        self._grip_kind.clear()
        self._grip_z.clear()
        self._undo.clear()
        self._pz = None
        self.gravity = True
        self.selected = None

    def step(self, dt: float) -> None:
        """Semi-implicit Euler. g on free bodies; kinematic while held."""
        h = min(0.05, max(0.0, float(dt)))
        if h <= 0:
            return
        total = 0.0
        wall = time.perf_counter()
        for body in self.bodies:
            if body.attached:
                gap = wall - body._pointer_wall if body._pointer_wall >= 0 else 0.0
                if HITCH_GAP < gap <= HITCH_HOLD:
                    lo = self._touch_radius(body)
                    hi = 1.0 - lo
                    body.x = min(hi, max(lo, body.x + body._hitch_vx * h))
                    body.y = min(hi, max(lo, body.y + body._hitch_vy * h))
                if body.frozen:
                    body.vx = 0.0
                    body.vy = 0.0
                total += self.energy(body)
                continue
            if body.frozen:
                body.vx = 0.0
                body.vy = 0.0
                total += self.energy(body)
                continue
            self._hit = body
            if self.gravity:
                body.vy += GRAVITY * h
            body.x += body.vx * h
            body.y += body.vy * h
            self._bounce()
            total += self.energy(body)
        self._collide_pairs()
        self._hit = None
        self.last_energy = total

    def _release(self, t: float) -> None:
        vx, vy = self._trail_velocity(t)
        speed = (vx * vx + vy * vy) ** 0.5
        if (
            self._peak_speed > speed
            and self._peak_t > 0
            and t - self._peak_t <= PEAK_HOLD
        ):
            vx, vy, speed = self._peak_vx, self._peak_vy, self._peak_speed
        if speed < STILL_SPEED:
            vx, vy, speed = 0.0, 0.0, 0.0
        # z is size. A flick is on the plane, like the discs.
        self.disc.vx = vx
        self.disc.vy = vy
        self.disc.last_release_speed = speed
        self.last_release_speed = speed
        self.last_energy = self.energy()
        self._last_holder = self.disc.holder
        self._released_at = t
        self._trail.clear()
        self._clear_peak()
        self._clear_hitch()

    def _note_peak(self, t: float) -> None:
        vx, vy = self._trail_velocity(t)
        speed = (vx * vx + vy * vy) ** 0.5
        if speed >= self._peak_speed:
            self._peak_vx = vx
            self._peak_vy = vy
            self._peak_speed = speed
            self._peak_t = t

    def _clear_peak(self) -> None:
        self._peak_vx = 0.0
        self._peak_vy = 0.0
        self._peak_speed = 0.0
        self._peak_t = 0.0

    def _begin_scale(self) -> None:
        a = self._grips.get(self.disc.holder)
        b = self._grips.get(self.disc.scaler)
        if a is None or b is None:
            self.disc.scaler = ""
            return
        span = math.hypot(a[0] - b[0], a[1] - b[1])
        self._scale_last = max(SCALE_SPAN_MIN, span)
        self.disc._spin_last = math.atan2(b[1] - a[1], b[0] - a[0])
        self.disc._orbit_last = None
        za = self._grip_z.get(self.disc.holder)
        zb = self._grip_z.get(self.disc.scaler)
        if za is not None and zb is not None:
            self.disc._tilt_last = math.atan2(zb - za, max(span, SCALE_SPAN_MIN))
        else:
            self.disc._tilt_last = None
        self.disc.vx = 0.0
        self.disc.vy = 0.0

    def _end_scale(self) -> None:
        holder = self._grips.get(self.disc.holder)
        if holder is not None and self._grip_kind.get(self.disc.holder) == "fist":
            # Stay where the stretch left the disc. Snapping onto the remaining
            # fist is what made the next join a fight.
            self._hold_dx = self.disc.x - holder[0]
            self._hold_dy = self.disc.y - holder[1]
        self.disc.scaler = ""
        self._scale_last = 0.0
        self._scale_seen.clear()
        self._scaler_lost_at = -1.0
        self._clear_spin(self.disc)

    def _note_scale_hand(self, who: str, t: float) -> None:
        self._scale_seen.add(who)
        if (
            self.disc.holder in self._scale_seen
            and self.disc.scaler in self._scale_seen
        ):
            self._update_scale(t)
            self._scale_seen.clear()

    def _update_scale(self, t: float) -> None:
        a = self._grips.get(self.disc.holder)
        b = self._grips.get(self.disc.scaler)
        if a is None or b is None:
            return
        span = math.hypot(a[0] - b[0], a[1] - b[1])
        line = math.atan2(b[1] - a[1], b[0] - a[0])
        if self.disc._spin_last is not None:
            self.disc.angle += _wrap(line - self.disc._spin_last)
        self.disc._spin_last = line
        za = self._grip_z.get(self.disc.holder)
        zb = self._grip_z.get(self.disc.scaler)
        if za is not None and zb is not None:
            tilt_now = math.atan2(zb - za, max(span, SCALE_SPAN_MIN))
            if self.disc._tilt_last is not None:
                self.disc.tilt += _wrap(tilt_now - self.disc._tilt_last)
            self.disc._tilt_last = tilt_now
            self.disc.tilt = min(math.pi / 2.0, max(-math.pi / 2.0, self.disc.tilt))
        if span >= SCALE_SPAN_MIN and self._scale_last >= SCALE_SPAN_MIN:
            ratio = span / self._scale_last
            ratio = min(SCALE_RATIO_MAX, max(SCALE_RATIO_MIN, ratio))
            if not self.disc.size_locked:
                self.disc.radius = min(
                    RADIUS_MAX, max(RADIUS_MIN, self.disc.radius * ratio)
                )
            self._scale_last = span
        elif span >= SCALE_SPAN_MIN:
            self._scale_last = span
        if not self.disc.size_locked:
            mid_x = (a[0] + b[0]) * 0.5
            mid_y = (a[1] + b[1]) * 0.5
            lo = self.disc.radius
            hi = 1.0 - self.disc.radius
            self.disc.x = min(hi, max(lo, mid_x))
            self.disc.y = min(hi, max(lo, mid_y))
        self.disc.vx = 0.0
        self.disc.vy = 0.0
        self.disc.attached = True
        self._trail.append((t, self.disc.x, self.disc.y))
        self._note_peak(t)

    def _trail_velocity(self, t: float) -> tuple[float, float]:
        # Inclusive window + epsilon so a 100 ms flick is not dropped by float.
        pts = [(ts, x, y) for ts, x, y in self._trail if t - ts <= TRAIL_WINDOW + 1e-6]
        if len(pts) < 2:
            pts = list(self._trail)
        if len(pts) < 2:
            return (0.0, 0.0)
        t0, x0, y0 = pts[0]
        t1, x1, y1 = pts[-1]
        dur = t1 - t0
        if dur < 1e-4:
            return (0.0, 0.0)
        return ((x1 - x0) / dur, (y1 - y0) / dur)

    def _bounce(self) -> None:
        # Rest on the silhouette. A near ball is drawn larger than
        # radius; parking on the solid radius buried it in the floor.
        lo = self._touch_radius(self.disc)
        hi = 1.0 - lo
        if self.disc.x < lo:
            self.disc.x = lo
            self.disc.vx = abs(self.disc.vx) * RESTITUTION
        elif self.disc.x > hi:
            self.disc.x = hi
            self.disc.vx = -abs(self.disc.vx) * RESTITUTION
        if self.disc.y < lo:
            self.disc.y = lo
            self.disc.vy = abs(self.disc.vy) * RESTITUTION
        elif self.disc.y > hi:
            self.disc.y = hi
            outgoing = abs(self.disc.vy) * RESTITUTION
            # Floor rest: a place that has landed must sit, not jitter.
            if self.disc.vy > 0 and outgoing < REST_SPEED:
                self.disc.vy = 0.0
            else:
                self.disc.vy = -outgoing

    def _collide_pairs(self) -> None:
        """Circle–circle on circumradius. Held bodies stay put; free ones yield."""
        n = len(self.bodies)
        for i in range(n):
            a = self.bodies[i]
            ra = self._touch_radius(a)
            for j in range(i + 1, n):
                b = self.bodies[j]
                rb = self._touch_radius(b)
                dx = b.x - a.x
                dy = b.y - a.y
                dist = math.hypot(dx, dy)
                min_d = ra + rb
                if dist >= min_d:
                    continue
                if dist < 1e-9:
                    dx, dy, dist = 0.01, 0.0, 0.01
                nx = dx / dist
                ny = dy / dist
                overlap = min_d - dist
                a_held = a.attached or a.frozen
                b_held = b.attached or b.frozen
                if a_held and b_held:
                    continue
                if a_held:
                    b.x += nx * overlap
                    b.y += ny * overlap
                elif b_held:
                    a.x -= nx * overlap
                    a.y -= ny * overlap
                else:
                    a.x -= nx * overlap * 0.5
                    a.y -= ny * overlap * 0.5
                    b.x += nx * overlap * 0.5
                    b.y += ny * overlap * 0.5
                rvx = b.vx - a.vx
                rvy = b.vy - a.vy
                vn = rvx * nx + rvy * ny
                if vn >= 0:
                    continue
                impulse = -(1.0 + RESTITUTION) * vn
                if a_held:
                    b.vx += impulse * nx
                    b.vy += impulse * ny
                elif b_held:
                    a.vx -= impulse * nx
                    a.vy -= impulse * ny
                else:
                    ma = max(a.mass, 1e-6)
                    mb = max(b.mass, 1e-6)
                    j_imp = impulse / (1.0 / ma + 1.0 / mb)
                    a.vx -= (j_imp / ma) * nx
                    a.vy -= (j_imp / ma) * ny
                    b.vx += (j_imp / mb) * nx
                    b.vy += (j_imp / mb) * ny
                self._hit = b if not b_held else a
                self._bounce()
                self._hit = a if not a_held else b
                self._bounce()
