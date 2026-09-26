"""REBOUND IAS15 wrapper. No homemade high-order integrator."""

from __future__ import annotations

from dataclasses import dataclass, field

from arelis.physics.constants import G_SI


def rebound_available() -> bool:
    try:
        import rebound  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass
class Particle:
    name: str
    mass: float
    radius: float
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    massive: bool = True
    tracer: bool = False
    kind: str = "planet"
    parent: str | None = None


@dataclass
class NBody:
    """Live Newtonian N-body. Integrator name is recorded for the HUD."""

    particles: list[Particle]
    integrator: str = "IAS15"
    _sim: object = field(default=None, repr=False)
    t: float = 0.0

    @classmethod
    def from_particles(
        cls, particles: list[Particle], *, integrator: str = "IAS15"
    ) -> NBody:
        if not rebound_available():
            raise RuntimeError(
                "REBOUND is not installed. From a checkout: pip install -e \".[astro]\"."
            )
        import rebound

        sim = rebound.Simulation()
        sim.G = G_SI
        name = (integrator or "IAS15").upper()
        if name == "WHFAST":
            sim.integrator = "whfast"
        elif name == "MERCURIUS":
            sim.integrator = "mercurius"
        else:
            sim.integrator = "ias15"
            name = "IAS15"
        for p in particles:
            sim.add(
                m=float(p.mass) if p.massive else 0.0,
                r=float(p.radius),
                x=p.x,
                y=p.y,
                z=p.z,
                vx=p.vx,
                vy=p.vy,
                vz=p.vz,
                name=p.name,
            )
        sim.move_to_com()
        engine = cls(particles=list(particles), integrator=name, _sim=sim, t=0.0)
        engine.pull()
        return engine

    def pull(self) -> None:
        sim = self._sim
        if sim is None:
            return
        for i, p in enumerate(self.particles):
            body = sim.particles[i]
            p.x, p.y, p.z = float(body.x), float(body.y), float(body.z)
            p.vx, p.vy, p.vz = float(body.vx), float(body.vy), float(body.vz)
        self.t = float(sim.t)

    def integrate_to(self, t: float) -> None:
        sim = self._sim
        if sim is None:
            return
        sim.integrate(float(t))
        self.pull()

    def step(self, dt: float) -> None:
        self.integrate_to(self.t + float(dt))

    def apply_impulse(self, name: str, dv: tuple[float, float, float]) -> bool:
        return self.apply_delta_v(name, dv, massive_only=True)

    def apply_delta_v(
        self,
        name: str,
        dv: tuple[float, float, float],
        *,
        massive_only: bool = False,
    ) -> bool:
        sim = self._sim
        if sim is None:
            return False
        for i, p in enumerate(self.particles):
            if p.name != name:
                continue
            if massive_only and not p.massive:
                return False
            body = sim.particles[i]
            body.vx += float(dv[0])
            body.vy += float(dv[1])
            body.vz += float(dv[2])
            self.pull()
            return True
        return False

    def write_state(
        self,
        name: str,
        x: float,
        y: float,
        z: float,
        vx: float,
        vy: float,
        vz: float,
    ) -> bool:
        sim = self._sim
        if sim is None:
            return False
        for i, p in enumerate(self.particles):
            if p.name != name:
                continue
            body = sim.particles[i]
            body.x, body.y, body.z = float(x), float(y), float(z)
            body.vx, body.vy, body.vz = float(vx), float(vy), float(vz)
            self.pull()
            return True
        return False

    def write_mass_radius(self, name: str, mass: float, radius: float) -> bool:
        sim = self._sim
        if sim is None:
            return False
        for i, p in enumerate(self.particles):
            if p.name != name:
                continue
            body = sim.particles[i]
            body.m = float(mass) if p.massive else 0.0
            body.r = float(radius)
            p.mass = float(mass)
            p.radius = float(radius)
            self.pull()
            return True
        return False

    def add_particle(self, particle: Particle) -> None:
        sim = self._sim
        if sim is None:
            raise RuntimeError("no simulation")
        sim.add(
            m=float(particle.mass) if particle.massive else 0.0,
            r=float(particle.radius),
            x=particle.x,
            y=particle.y,
            z=particle.z,
            vx=particle.vx,
            vy=particle.vy,
            vz=particle.vz,
            name=particle.name,
        )
        self.particles.append(particle)
        self.pull()

    def energy(self) -> float:
        sim = self._sim
        if sim is None:
            return 0.0
        return float(sim.energy())

    def angular_momentum(self) -> tuple[float, float, float]:
        lx = ly = lz = 0.0
        for p in self.particles:
            if not p.massive:
                continue
            lx += p.mass * (p.y * p.vz - p.z * p.vy)
            ly += p.mass * (p.z * p.vx - p.x * p.vz)
            lz += p.mass * (p.x * p.vy - p.y * p.vx)
        return (lx, ly, lz)

    def find(self, name: str) -> Particle | None:
        for p in self.particles:
            if p.name == name:
                return p
        return None
