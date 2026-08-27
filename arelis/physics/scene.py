"""Live solar-system scene.

Pause, warp rate, HUD books, and the counterfactual flag live here.
IAS15 integrates the particles. The camera is not a particle: there is
no rideable craft. Overlay booleans (gravity / magnetic / wind / grid) used to
sit on that vehicle; they stay on OverlayFlags.

Massless probes and Lagrange markers are sketches. They do not clip on
stop-spheres. The fly camera refuses to enter a stop-sphere on Travel to.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from arelis.physics.belt import generate_tracers
from arelis.physics.clocks import RATE_DAY, RATE_HOUR, clamp_rate
from arelis.physics.collision import stop_radius_m
from arelis.physics.constants import (
    AU_M,
    BODIES,
    BODY_BY_NAME,
    G_SI,
    GM_SUN,
    M_SUN,
    mass_kg,
)
from arelis.physics.elements import hill_radius, osculating, sphere_of_influence
from arelis.physics.engine import NBody, Particle
from arelis.physics.horizons import VectorState
from arelis.physics.lagrange import sun_planet_l_points

TRAIL_MAX = 240


@dataclass
class BodyView:
    name: str
    kind: str
    tracer: bool
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    radius: float
    mass: float
    parent: str | None


@dataclass
class OverlayFlags:
    """Sketch overlays. Not a spacecraft. Spoken solar toggle flags match these."""

    show_gravity: bool = False
    show_magnetic: bool = False
    show_wind: bool = False
    show_grid: bool = False


@dataclass
class SolarSystem:
    nbody: NBody
    paused: bool = True
    rate: float = RATE_HOUR  # 1 hour per wall-second until they pick a warp.
    counterfactual: bool = False
    lock: str = "Sun"  # spawn host / spoken HUD. Click inspect is SolarPanel._inspect.
    show_osculating: bool = True
    show_trails: bool = False
    show_graphs: bool = False
    show_lagrange: bool = False
    epoch_tdb: str = ""
    epoch_jd: float = 0.0
    ic_date: str = ""
    energy0: float = 0.0
    l0: tuple[float, float, float] = (0.0, 0.0, 0.0)
    energy_hist: deque[tuple[float, float]] = field(default_factory=deque)
    trails: dict[str, deque[tuple[float, float, float]]] = field(default_factory=dict)
    integrator_note: str = "IAS15"
    overlay: OverlayFlags = field(default_factory=OverlayFlags)
    last_warp: float = RATE_HOUR  # remembered by \\ so realtime can restore it
    future_gyr: float = 0.0
    # Spoken solar lock/travel: the Qt panel consumes these on the next frame.
    pending_inspect: str | None = None
    pending_travel: str | None = None
    _present: list[
        tuple[str, float, float, float, float, float, float, float, float]
    ] | None = field(default=None, repr=False)

    @classmethod
    def from_states(
        cls,
        states: dict[str, VectorState],
        *,
        tracers: int = 0,
        tracer_seed: int = 20260824,
        integrator: str = "IAS15",
        epoch_tdb: str = "",
        epoch_jd: float = 0.0,
        ic_date: str = "",
    ) -> SolarSystem:
        particles: list[Particle] = []
        for spec in BODIES:
            st = states.get(spec.name)
            if st is None:
                continue
            particles.append(
                Particle(
                    name=spec.name,
                    mass=mass_kg(spec),
                    radius=spec.radius,
                    x=st.x,
                    y=st.y,
                    z=st.z,
                    vx=st.vx,
                    vy=st.vy,
                    vz=st.vz,
                    massive=True,
                    tracer=False,
                    kind=spec.kind,
                    parent=spec.parent,
                )
            )
        if not particles:
            raise ValueError("solar system needs at least one body state.")
        if tracers:
            for tr in generate_tracers(tracers, seed=tracer_seed):
                particles.append(
                    Particle(
                        name=tr.label,
                        mass=0.0,
                        radius=1_000.0,
                        x=tr.x,
                        y=tr.y,
                        z=tr.z,
                        vx=tr.vx,
                        vy=tr.vy,
                        vz=tr.vz,
                        massive=False,
                        tracer=True,
                        kind="tracer",
                    )
                )
        nbody = NBody.from_particles(particles, integrator=integrator)
        jd = epoch_jd
        if not jd:
            for st in states.values():
                if st.epoch_jd:
                    jd = float(st.epoch_jd)
                    break
        scene = cls(
            nbody=nbody,
            epoch_tdb=epoch_tdb,
            epoch_jd=jd,
            ic_date=ic_date,
            integrator_note=nbody.integrator,
        )
        scene.energy0 = nbody.energy()
        scene.l0 = nbody.angular_momentum()
        return scene

    @property
    def t(self) -> float:
        return self.nbody.t

    def tick(self, wall_dt: float) -> None:
        """Advance IAS15. The camera is not a particle; there is no craft substep."""
        if self.paused or wall_dt <= 0.0:
            return
        sim_dt = wall_dt * self.rate
        self._advance(sim_dt)
        if self.show_graphs or self.show_trails:
            self._sample()

    def step_once(self, dt: float | None = None) -> None:
        span = float(dt) if dt is not None else max(self.rate, 1.0)
        self._advance(span)
        self._sample()

    def _advance(self, sim_dt: float) -> None:
        if sim_dt <= 0.0:
            return
        self.nbody.step(sim_dt)

    def _sample(self) -> None:
        e = self.nbody.energy()
        self.energy_hist.append((self.t, e))
        while len(self.energy_hist) > 400:
            self.energy_hist.popleft()
        if not self.show_trails:
            return
        for p in self.nbody.particles:
            if p.tracer:
                continue
            trail = self.trails.setdefault(p.name, deque(maxlen=TRAIL_MAX))
            trail.append((p.x, p.y, p.z))

    def energy_residual(self) -> float:
        e = self.nbody.energy()
        if abs(self.energy0) < 1e-30:
            return 0.0
        return abs(e - self.energy0) / abs(self.energy0)

    def views(self) -> list[BodyView]:
        out: list[BodyView] = []
        for p in self.nbody.particles:
            out.append(
                BodyView(
                    name=p.name,
                    kind=p.kind,
                    tracer=p.tracer,
                    x=p.x,
                    y=p.y,
                    z=p.z,
                    vx=p.vx,
                    vy=p.vy,
                    vz=p.vz,
                    radius=p.radius,
                    mass=p.mass,
                    parent=p.parent,
                )
            )
        return out

    def locked(self) -> BodyView | None:
        hit = self.nbody.find(self.lock)
        if hit is None:
            return None
        return BodyView(
            name=hit.name,
            kind=hit.kind,
            tracer=hit.tracer,
            x=hit.x,
            y=hit.y,
            z=hit.z,
            vx=hit.vx,
            vy=hit.vy,
            vz=hit.vz,
            radius=hit.radius,
            mass=hit.mass,
            parent=hit.parent,
        )

    def about(self, body: BodyView) -> tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        float,
        str,
        tuple[float, float, float],
    ]:
        """Relative state, μ, parent name, parent world position."""
        spec = BODY_BY_NAME.get(body.name)
        parent_name = spec.parent if spec else None
        if parent_name:
            parent = self.nbody.find(parent_name)
            parent_spec = BODY_BY_NAME.get(parent_name)
            if parent is not None and parent_spec is not None:
                return (
                    (body.x - parent.x, body.y - parent.y, body.z - parent.z),
                    (body.vx - parent.vx, body.vy - parent.vy, body.vz - parent.vz),
                    parent_spec.gm,
                    parent_name,
                    (parent.x, parent.y, parent.z),
                )
        sun = self.nbody.find("Sun")
        if sun is None:
            return (
                (body.x, body.y, body.z),
                (body.vx, body.vy, body.vz),
                GM_SUN,
                "Sun",
                (0.0, 0.0, 0.0),
            )
        return (
            (body.x - sun.x, body.y - sun.y, body.z - sun.z),
            (body.vx - sun.vx, body.vy - sun.vy, body.vz - sun.vz),
            GM_SUN,
            "Sun",
            (sun.x, sun.y, sun.z),
        )

    def heliocentric(
        self, body: BodyView
    ) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        r, v, _mu, _name, _origin = self.about(body)
        if _name != "Sun":
            sun = self.nbody.find("Sun")
            if sun is not None:
                return (
                    (body.x - sun.x, body.y - sun.y, body.z - sun.z),
                    (body.vx - sun.vx, body.vy - sun.vy, body.vz - sun.vz),
                )
        return (r, v)

    def _sun_hud(self) -> dict[str, float | str]:
        from arelis.physics.evolution import sample

        track = sample(self.future_gyr) if abs(self.future_gyr) > 1e-6 else None
        return {
            "future_gyr": self.future_gyr,
            "sun_phase": track.phase if track else "main sequence",
            "sun_r": track.r_sun if track else 1.0,
            "sun_cite": track.cite if track else "",
        }

    def hud_for_lock(self) -> dict[str, float | str | bool | None]:
        body = self.locked()
        if body is None:
            return {}
        return self.hud_for_body(body)

    def hud_for_name(self, name: str) -> dict[str, float | str | bool | None]:
        prev = self.lock
        self.lock = name
        try:
            return self.hud_for_lock()
        finally:
            self.lock = prev

    def ic_caption(self) -> str:
        """One HUD phrase. Do not call a circular catalog a Horizons IC."""
        if self.counterfactual:
            return "COUNTERFACTUAL"
        if self.epoch_tdb:
            return self.epoch_tdb
        return "unspecified IC, not Horizons"

    def hud_for_body(self, body: BodyView) -> dict[str, float | str | bool | None]:
        """Kepler + vis-viva about the catalog parent (Sun if the body is a planet).

        Hill and SOI are this body's own radii about that parent, not capture
        walls. Circ/esc are two-body numbers at the current radius.
        """
        r, v, mu, about, _origin = self.about(body)
        el = osculating(r, v, mu)
        a = float(el.a) if el else 0.0
        parent_mass = mu / G_SI if mu > 0.0 else M_SUN
        hill = hill_radius(a, body.mass, parent_mass) if body.mass > 0.0 else 0.0
        soi = sphere_of_influence(a, body.mass, parent_mass) if body.mass > 0.0 else 0.0
        spec = BODY_BY_NAME.get(body.name)
        rx, ry, rz = r
        vx, vy, vz = v
        rmag = (rx * rx + ry * ry + rz * rz) ** 0.5
        v2 = vx * vx + vy * vy + vz * vz
        circ = esc = eps = None
        bound: bool | None = None
        if rmag > 1.0 and mu > 0.0:
            circ = (mu / rmag) ** 0.5
            esc = (2.0 * mu / rmag) ** 0.5
            eps = 0.5 * v2 - mu / rmag
            bound = eps < 0.0
        return {
            "name": body.name,
            "tracer": body.tracer,
            "kind": body.kind,
            "about": about,
            "a_au": a / AU_M if el else None,
            "e": el.e if el else None,
            "i_deg": (el.i * 180.0 / 3.141592653589793) if el else None,
            "period_day": (el.period_s / 86400.0) if el else None,
            "hill_m": hill,
            "soi_m": soi,
            "v_circ_m_s": circ,
            "v_esc_m_s": esc,
            "specific_energy": eps,
            "bound": bound,
            "radius_m": body.radius,
            "gm": spec.gm if spec else body.mass * G_SI,
            "horizons_id": spec.horizons_id if spec else "",
            "parent": body.parent,
            "energy_residual": self.energy_residual(),
            "counterfactual": self.counterfactual,
            "integrator": self.integrator_note,
            "paused": self.paused,
            "rate": self.rate,
            "t_s": self.t,
            "epoch_tdb": self.epoch_tdb,
            "epoch_jd": self.epoch_jd,
            "ic_date": self.ic_date,
            **self._sun_hud(),
        }

    def lagrange_sun_earth(self) -> dict[str, tuple[float, float, float]]:
        earth = self.nbody.find("Earth")
        sun = self.nbody.find("Sun")
        if earth is None or sun is None:
            return {}
        r = (earth.x - sun.x, earth.y - sun.y, earth.z - sun.z)
        v = (earth.vx - sun.vx, earth.vy - sun.vy, earth.vz - sun.vz)
        pts = sun_planet_l_points(r, M_SUN, earth.mass, v)
        return {
            name: (sun.x + xyz[0], sun.y + xyz[1], sun.z + xyz[2])
            for name, xyz in pts.items()
        }

    def lagrange_sun_jupiter(self) -> dict[str, tuple[float, float, float]]:
        jup = self.nbody.find("Jupiter")
        sun = self.nbody.find("Sun")
        if jup is None or sun is None:
            return {}
        r = (jup.x - sun.x, jup.y - sun.y, jup.z - sun.z)
        v = (jup.vx - sun.vx, jup.vy - sun.vy, jup.vz - sun.vz)
        pts = sun_planet_l_points(r, M_SUN, jup.mass, v)
        return {
            name: (sun.x + xyz[0], sun.y + xyz[1], sun.z + xyz[2])
            for name, xyz in pts.items()
        }

    def impulse(self, name: str, dv: tuple[float, float, float]) -> bool:
        ok = self.nbody.apply_impulse(name, dv)
        if ok:
            self.counterfactual = True
            self.energy0 = self.nbody.energy()
            self.l0 = self.nbody.angular_momentum()
        return ok

    def prograde_impulse(self, name: str, mag_m_s: float) -> bool:
        """Δv along the inertial velocity. Massive bodies only."""
        body = self.nbody.find(name)
        if body is None or not body.massive:
            return False
        speed = math.hypot(body.vx, body.vy, body.vz)
        if speed < 1e-12:
            return False
        scale = float(mag_m_s) / speed
        return self.impulse(
            name, (body.vx * scale, body.vy * scale, body.vz * scale)
        )

    def add_probe(
        self,
        name: str,
        x: float,
        y: float,
        z: float,
        vx: float,
        vy: float,
        vz: float,
    ) -> None:
        self.nbody.add_particle(
            Particle(
                name=name,
                mass=0.0,
                radius=5.0,
                x=x,
                y=y,
                z=z,
                vx=vx,
                vy=vy,
                vz=vz,
                massive=False,
                tracer=False,
                kind="probe",
            )
        )
        self.counterfactual = True

    def _unique(self, stem: str) -> str:
        base = (stem or "body").strip() or "body"
        label = base
        n = 2
        while self.nbody.find(label) is not None:
            label = f"{base}-{n}"
            n += 1
        return label

    def _host_for_spawn(self) -> Particle:
        # A Sun lock is the overview, not a request to skim the photosphere.
        if self.lock == "Sun":
            host = self.nbody.find("Earth") or self.nbody.find("Sun")
        else:
            host = self.nbody.find(self.lock)
            if host is None or not host.massive:
                host = self.nbody.find("Earth") or self.nbody.find("Sun")
        if host is None:
            raise RuntimeError("no host to spawn around")
        return host

    def _circular_state(
        self, host: Particle
    ) -> tuple[float, float, float, float, float, float, float, float, float]:
        """Inertial circular injection around host, plus the tangent unit."""
        sun = self.nbody.find("Sun")
        r_stop, _cite = stop_radius_m(host.name)
        if host.name == "Sun":
            dist = host.radius * 4.0
        elif host.name == "Earth":
            dist = r_stop + 300_000.0
        else:
            dist = r_stop + max(50_000.0, host.radius * 0.08)
        if sun is not None and host.name != "Sun":
            dx, dy, dz = host.x - sun.x, host.y - sun.y, host.z - sun.z
            hvx = host.vx - sun.vx
            hvy = host.vy - sun.vy
            hvz = host.vz - sun.vz
        else:
            dx, dy, dz = 1.0, 0.0, 0.0
            hvx, hvy, hvz = 0.0, 0.0, 1.0
        rl = (dx * dx + dy * dy + dz * dz) ** 0.5 or 1.0
        ux, uy, uz = dx / rl, dy / rl, dz / rl
        nx = dy * hvz - dz * hvy
        ny = dz * hvx - dx * hvz
        nz = dx * hvy - dy * hvx
        nl = (nx * nx + ny * ny + nz * nz) ** 0.5
        if nl < 1e-12:
            nx, ny, nz, nl = 0.0, 0.0, 1.0, 1.0
        nx, ny, nz = nx / nl, ny / nl, nz / nl
        tx = ny * uz - nz * uy
        ty = nz * ux - nx * uz
        tz = nx * uy - ny * ux
        tl = (tx * tx + ty * ty + tz * tz) ** 0.5
        if tl < 1e-12:
            tx, ty, tz, tl = -uy, ux, 0.0, 1.0
        tx, ty, tz = tx / tl, ty / tl, tz / tl
        spec = BODY_BY_NAME.get(host.name)
        mu = spec.gm if spec else GM_SUN
        v_c = (mu / dist) ** 0.5
        return (
            host.x + ux * dist,
            host.y + uy * dist,
            host.z + uz * dist,
            host.vx + tx * v_c,
            host.vy + ty * v_c,
            host.vz + tz * v_c,
            tx,
            ty,
            tz,
        )

    def _co_rotate(
        self, sun: Particle, earth: Particle, px: float, py: float, pz: float
    ) -> tuple[float, float, float]:
        """Inertial velocity so a point turns with the Sun-Earth line."""
        rx, ry, rz = earth.x - sun.x, earth.y - sun.y, earth.z - sun.z
        vx, vy, vz = earth.vx - sun.vx, earth.vy - sun.vy, earth.vz - sun.vz
        r2 = rx * rx + ry * ry + rz * rz
        if r2 < 1.0:
            return (sun.vx, sun.vy, sun.vz)
        ox = (ry * vz - rz * vy) / r2
        oy = (rz * vx - rx * vz) / r2
        oz = (rx * vy - ry * vx) / r2
        lx, ly, lz = px - sun.x, py - sun.y, pz - sun.z
        return (
            sun.vx + oy * lz - oz * ly,
            sun.vy + oz * lx - ox * lz,
            sun.vz + ox * ly - oy * lx,
        )

    def spawn_probe(self) -> str:
        """Massless circular probe around the lock. Not in the Horizons IC."""
        host = self._host_for_spawn()
        x, y, z, vx, vy, vz, _tx, _ty, _tz = self._circular_state(host)
        label = self._unique("probe")
        self.add_probe(label, x, y, z, vx, vy, vz)
        self.lock = label
        return label

    def spawn_tracer(self) -> str:
        """One debiased belt tracer, heliocentric about the live Sun."""
        sun = self.nbody.find("Sun")
        if sun is None:
            raise RuntimeError("need the Sun")
        seed = 20260824 + len(self.nbody.particles) + int(self.t * 1e3)
        tr = generate_tracers(1, seed=seed)[0]
        label = self._unique("belt particle")
        self.nbody.add_particle(
            Particle(
                name=label,
                mass=0.0,
                radius=1_000.0,
                x=sun.x + tr.x,
                y=sun.y + tr.y,
                z=sun.z + tr.z,
                vx=sun.vx + tr.vx,
                vy=sun.vy + tr.vy,
                vz=sun.vz + tr.vz,
                massive=False,
                tracer=True,
                kind="tracer",
            )
        )
        self.counterfactual = True
        self.lock = label
        return label

    def spawn_lagrange(self, which: str = "L4") -> str:
        """Massless particle at Sun-Earth CR3BP L-point. Not the N-body equilibrium."""
        pts = self.lagrange_sun_earth()
        key = which.strip().upper() or "L4"
        if key not in pts:
            raise RuntimeError("need Sun and Earth for a Lagrange spawn")
        sun = self.nbody.find("Sun")
        earth = self.nbody.find("Earth")
        if sun is None or earth is None:
            raise RuntimeError("need Sun and Earth")
        px, py, pz = pts[key]
        vx, vy, vz = self._co_rotate(sun, earth, px, py, pz)
        label = self._unique(f"SE-{key}")
        self.nbody.add_particle(
            Particle(
                name=label,
                mass=0.0,
                radius=5.0,
                x=px,
                y=py,
                z=pz,
                vx=vx,
                vy=vy,
                vz=vz,
                massive=False,
                tracer=False,
                kind="lagrange",
            )
        )
        self.counterfactual = True
        self.show_lagrange = True
        self.lock = label
        return label

    def add_planet(self, a_m: float, name: str = "extra") -> str:
        sun = self.nbody.find("Sun")
        if sun is None:
            raise RuntimeError("need the Sun")
        stem = (name or "extra").strip() or "extra"
        label = stem
        n = 2
        while self.nbody.find(label) is not None:
            label = f"{stem}-{n}"
            n += 1
        a = max(float(a_m), 1.0e9)
        v = (GM_SUN / a) ** 0.5
        earth = BODY_BY_NAME["Earth"]
        self.nbody.add_particle(
            Particle(
                name=label,
                mass=mass_kg(earth),
                radius=earth.radius,
                x=sun.x + a,
                y=sun.y,
                z=sun.z,
                vx=sun.vx,
                vy=sun.vy + v,
                vz=sun.vz,
                massive=True,
                tracer=False,
                kind="planet",
            )
        )
        self.counterfactual = True
        self.energy0 = self.nbody.energy()
        self.l0 = self.nbody.angular_momentum()
        return label

    def set_rate(self, rate: float) -> float:
        if self.rate > 1.0 + 1e-9:
            self.last_warp = self.rate
        self.rate = clamp_rate(rate)
        return self.rate

    def toggle_warp(self) -> float:
        if abs(self.rate - 1.0) < 1e-9:
            self.rate = clamp_rate(self.last_warp or RATE_DAY)
        else:
            self.last_warp = self.rate
            self.rate = 1.0
        return self.rate

    def _capture_present(self) -> None:
        rows = []
        for p in self.nbody.particles:
            rows.append(
                (p.name, p.x, p.y, p.z, p.vx, p.vy, p.vz, p.mass, p.radius)
            )
        self._present = rows

    def _restore_present(self) -> None:
        if not self._present:
            return
        for name, x, y, z, vx, vy, vz, mass, radius in self._present:
            self.nbody.write_state(name, x, y, z, vx, vy, vz)
            self.nbody.write_mass_radius(name, mass, radius)

    def set_future_gyr(self, gyr: float) -> float:
        """Scrub a cited solar track. Does not integrate 5 Gyr of IAS15."""
        from arelis.physics.evolution import clamp_gyr, sample

        t = clamp_gyr(gyr)
        if self._present is None:
            self._capture_present()
        self._restore_present()
        self.future_gyr = t
        if abs(t) < 1e-6:
            self.energy0 = self.nbody.energy()
            self.l0 = self.nbody.angular_momentum()
            return 0.0
        track = sample(t)
        sun = self.nbody.find("Sun")
        if sun is None:
            return t
        m0 = sun.mass
        r0 = sun.radius
        self.nbody.write_mass_radius("Sun", m0 * track.m_sun, r0 * track.r_sun)
        sun = self.nbody.find("Sun")
        if sun is None:
            return t
        scale_r = 1.0 / max(track.m_sun, 1e-6)
        scale_v = track.m_sun
        present = {row[0]: row for row in (self._present or [])}
        moons: list[str] = []
        for p in list(self.nbody.particles):
            if p.name == "Sun":
                continue
            spec = BODY_BY_NAME.get(p.name)
            if spec is not None and spec.parent:
                moons.append(p.name)
                continue
            dx, dy, dz = p.x - sun.x, p.y - sun.y, p.z - sun.z
            dvx, dvy, dvz = p.vx - sun.vx, p.vy - sun.vy, p.vz - sun.vz
            self.nbody.write_state(
                p.name,
                sun.x + dx * scale_r,
                sun.y + dy * scale_r,
                sun.z + dz * scale_r,
                sun.vx + dvx * scale_v,
                sun.vy + dvy * scale_v,
                sun.vz + dvz * scale_v,
            )
        for name in moons:
            spec = BODY_BY_NAME[name]
            parent = self.nbody.find(spec.parent or "")
            snap_p = present.get(name)
            snap_parent = present.get(spec.parent or "")
            if parent is None or snap_p is None or snap_parent is None:
                continue
            self.nbody.write_state(
                name,
                parent.x + (snap_p[1] - snap_parent[1]),
                parent.y + (snap_p[2] - snap_parent[2]),
                parent.z + (snap_p[3] - snap_parent[3]),
                parent.vx + (snap_p[4] - snap_parent[4]),
                parent.vy + (snap_p[5] - snap_parent[5]),
                parent.vz + (snap_p[6] - snap_parent[6]),
            )
        self.counterfactual = True
        self.energy0 = self.nbody.energy()
        self.l0 = self.nbody.angular_momentum()
        return t

    def enter_inspect(self) -> None:
        """Spoken solar action=craft / inspect. No-op: the camera is inspect-only."""
        return

    def gravity_at(
        self, x: float, y: float, z: float
    ) -> tuple[float, float, float, float]:
        """Newtonian g from massive bodies at a point. m/s^2."""
        gx = gy = gz = 0.0
        for p in self.nbody.particles:
            if not p.massive or p.mass <= 0.0:
                continue
            dx, dy, dz = p.x - x, p.y - y, p.z - z
            r2 = dx * dx + dy * dy + dz * dz
            r = r2 ** 0.5
            if r < 1.0:
                continue
            a = G_SI * p.mass / r2
            gx += a * dx / r
            gy += a * dy / r
            gz += a * dz / r
        g = (gx * gx + gy * gy + gz * gz) ** 0.5
        return gx, gy, gz, g
