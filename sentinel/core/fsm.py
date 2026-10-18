"""Sentinel Finite State Machine, Upgrade Tiers, 3D World Nodes, and Boids Kinematics."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SentinelState(StrEnum):
    DOCKED = "DOCKED"
    PATROLLING = "PATROLLING"
    VECTORING = "VECTORING"
    ENGAGED_HARVEST = "ENGAGED_HARVEST"
    ENGAGED_SANITIZE = "ENGAGED_SANITIZE"
    ENGAGED_DEFENSE = "ENGAGED_DEFENSE"
    ENGAGED_EXECUTION = "ENGAGED_EXECUTION"
    RETURNING = "RETURNING"
    QUARANTINING = "QUARANTINING"
    EMP_DISABLED = "EMP_DISABLED"


@dataclass(frozen=True)
class TierSpec:
    tier: str
    tentacles: int
    max_speed: float
    accel: float
    scale: float


TIER_SPECS: dict[str, TierSpec] = {
    "mk1": TierSpec(
        tier="mk1",
        tentacles=8,
        max_speed=24.0,
        accel=42.0,
        scale=1.0,
    ),
    "mk2": TierSpec(
        tier="mk2",
        tentacles=10,
        max_speed=34.0,
        accel=60.0,
        scale=1.18,
    ),
    "mk3": TierSpec(
        tier="mk3",
        tentacles=12,
        max_speed=46.0,
        accel=82.0,
        scale=1.36,
    ),
}

CASTE_ORBIT_PROFILES: dict[str, dict[str, float]] = {
    "harvester": {"radius": 18.0, "y_band": 4.0, "speed_mult": 1.05},
    "sanitizer": {"radius": 12.5, "y_band": 3.0, "speed_mult": 0.95},
    "warden": {"radius": 28.0, "y_band": 2.5, "speed_mult": 1.15},
    "tripwire": {"radius": 24.0, "y_band": -3.5, "speed_mult": 0.90},
}


def register_caste_profile(
    caste_id: str,
    *,
    radius: float = 20.0,
    y_band: float = 0.0,
    speed_mult: float = 1.0,
    doctrine: str = "HUNTER-SEEKER",
) -> dict[str, float]:
    """Register or update 3D orbital dynamics and Matrix doctrine for a Sentinel caste."""
    cid = caste_id.strip().lower()
    profile = {
        "radius": float(radius),
        "y_band": float(y_band),
        "speed_mult": float(speed_mult),
    }
    CASTE_ORBIT_PROFILES[cid] = profile
    CASTE_DEFAULT_DOCTRINE[cid] = doctrine
    return profile


def unregister_caste_profile(caste_id: str) -> bool:
    """Remove orbital dynamics profile for an unregistered caste."""
    cid = caste_id.strip().lower()
    CASTE_DEFAULT_DOCTRINE.pop(cid, None)
    return CASTE_ORBIT_PROFILES.pop(cid, None) is not None



def resolve_tier(tier: str | None) -> TierSpec:
    key = (tier or "mk1").strip().lower()
    return TIER_SPECS.get(key, TIER_SPECS["mk1"])


@dataclass
class WorldNode:
    """A 3D entity in the Overseer space: Bastion Gate, Harvest Target, or Threat Node."""

    node_id: str
    kind: str  # "bastion" | "harvest_target" | "threat" | "quarantine" | "memory_crystal"
    label: str
    position: list[float]  # [x, y, z]
    status: str = "active"  # "active" | "extracting" | "sanitizing" | "completed" | "blocked" | "quarantined"
    progress: float = 0.0  # 0.0 .. 1.0
    severity: str = "none"  # "none" | "low" | "medium" | "high" | "critical"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "label": self.label,
            "position": [round(c, 3) for c in self.position],
            "status": self.status,
            "progress": round(self.progress, 3),
            "severity": self.severity,
            "metadata": self.metadata,
        }


# Doctrine strings select steer speed and pack labels. They do not terminate processes.
CASTE_DEFAULT_DOCTRINE: dict[str, str] = {
    "harvester": "HUNTER-GATHERER",
    "tripwire": "HUNTER-SEEKER",
    "warden": "HUNTER-KILLER",
    "sanitizer": "HUNTER-KILLER",
}


@dataclass
class SentinelUnit:
    """An individual autonomous Sentinel with narrow caste lock, Matrix doctrine, and 3D pack kinematics."""

    unit_id: str
    caste: str
    tier: str = "mk1"
    version: str = "1.0.0"
    state: SentinelState = SentinelState.PATROLLING
    doctrine: str = "HUNTER-SEEKER"
    pack_id: str | None = None
    pack_role: str = "SOLO"  # "SOLO" | "ALPHA" | "WINGMAN"
    pack_slot: int = 0
    pack_size: int = 1
    position: list[float] = field(default_factory=lambda: [0.0, 0.0, 15.0])
    velocity: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    heading: list[float] = field(default_factory=lambda: [0.0, 0.0, 1.0])
    orbit_angle: float = 0.0
    orbit_phase: float = 0.0
    target_node_id: str | None = None
    target_position: list[float] | None = None
    current_task: str = "Patrolling assigned sector"
    laser_active: bool = False
    laser_target: list[float] | None = None
    laser_kind: str = "none"  # "none" | "harvest" | "sanitize" | "defense"
    carrying_orb: bool = False
    orb_color: str = "#ff7a22"
    missions_completed: int = 0
    bytes_processed: int = 0
    threats_neutralized: int = 0  # Legacy field, no longer used for new metrics.
    security_events: int = 0
    spawned_at: float = field(default_factory=time.time)
    last_transition_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.doctrine or self.doctrine == "HUNTER-SEEKER":
            self.doctrine = CASTE_DEFAULT_DOCTRINE.get(self.caste, "HUNTER-SEEKER")

    @property
    def spec(self) -> TierSpec:
        return resolve_tier(self.tier)

    def resolve_active_doctrine(self) -> str:
        """Return the doctrine label for this caste and state. Callers use it for speed and pack tags."""
        if self.caste == "harvester":
            return "HUNTER-GATHERER"
        if self.caste == "tripwire":
            if self.state in {SentinelState.ENGAGED_DEFENSE, SentinelState.QUARANTINING}:
                return "HUNTER-KILLER"
            return "HUNTER-SEEKER"
        if self.caste == "warden":
            if self.state in {SentinelState.ENGAGED_DEFENSE, SentinelState.QUARANTINING}:
                return "HUNTER-KILLER"
            if self.state == SentinelState.VECTORING and self.current_task.startswith("Live Socket Patrol"):
                return "HUNTER-SEEKER"
            return "HUNTER-KILLER" if self.laser_kind == "defense" else "HUNTER-SEEKER"
        if self.caste == "sanitizer":
            return "HUNTER-KILLER"
        return self.doctrine

    def transition(
        self,
        new_state: SentinelState,
        *,
        task: str | None = None,
        target_node_id: str | None = None,
        target_position: list[float] | None = None,
        laser_active: bool = False,
        laser_kind: str = "none",
        carrying_orb: bool | None = None,
        force_restore: bool = False,
    ) -> None:
        if (
            self.state == SentinelState.EMP_DISABLED
            and new_state != SentinelState.EMP_DISABLED
            and not force_restore
        ):
            return
        was_patrolling = self.state == SentinelState.PATROLLING
        self.state = new_state
        self.last_transition_at = time.time()
        if task is not None:
            self.current_task = task
        self.target_node_id = target_node_id
        if target_position is not None:
            self.target_position = list(target_position)
        elif new_state in {SentinelState.PATROLLING, SentinelState.DOCKED, SentinelState.EMP_DISABLED}:
            self.target_position = None
            self.pack_id = None
            self.pack_role = "SOLO"
            self.pack_slot = 0
            self.pack_size = 1
            if new_state == SentinelState.PATROLLING and not was_patrolling:
                horiz_r = math.hypot(self.position[0], self.position[2])
                if horiz_r > 2.0:
                    self.orbit_angle = math.atan2(self.position[2], self.position[0]) % (math.pi * 2.0)
        self.laser_active = laser_active
        self.laser_kind = laser_kind if laser_active else "none"
        self.laser_target = list(target_position) if (laser_active and target_position) else None
        if carrying_orb is not None:
            self.carrying_orb = carrying_orb
        self.doctrine = self.resolve_active_doctrine()

    def upgrade(self, new_tier: str, *, new_version: str | None = None) -> TierSpec:
        spec = resolve_tier(new_tier)
        self.tier = spec.tier
        if new_version:
            self.version = new_version
        return spec

    def step_kinematics(
        self,
        dt: float,
        neighbors: list[SentinelUnit],
        nodes: dict[str, WorldNode],
    ) -> None:
        """Advance 3D position, velocity, heading, Boids ribbon schooling, and Pack encirclement."""
        dt = min(max(dt, 0.001), 0.1)
        spec = self.spec
        profile = CASTE_ORBIT_PROFILES.get(
            self.caste,
            {"radius": 20.0, "y_band": 0.0, "speed_mult": 1.0},
        )

        if self.state == SentinelState.EMP_DISABLED:
            self.velocity[0] *= 0.90
            self.velocity[1] = max(-2.5, self.velocity[1] * 0.90 - 1.8 * dt)
            self.velocity[2] *= 0.90
            self.laser_active = False
            self._integrate(dt, max_spd=6.0)
            return

        if self.state == SentinelState.DOCKED:
            goal = [
                math.cos(self.orbit_angle) * 5.0,
                -2.0,
                math.sin(self.orbit_angle) * 5.0,
            ]
            self._steer_toward(goal, dt, max_spd=spec.max_speed * 0.5, slow_radius=3.0)
            self._integrate(dt, max_spd=spec.max_speed * 0.5)
            return

        # Keep target_position synced if locked onto a live WorldNode
        if self.target_node_id and self.target_node_id in nodes:
            node = nodes[self.target_node_id]
            self.target_position = list(node.position)
            if self.laser_active:
                self.laser_target = list(node.position)

        slot_angle = (self.pack_slot / max(1, self.pack_size)) * (math.pi * 2.0)
        slot_elev = ((self.pack_slot % 3) - 1.0) * 1.15

        if self.state == SentinelState.PATROLLING:
            ang_speed = (0.42 * profile["speed_mult"]) * (1.0 + 0.1 * (spec.tentacles - 8))
            self.orbit_angle = (self.orbit_angle + ang_speed * dt) % (math.pi * 2.0)
            # Sinuous Matrix corkscrew wave along orbital ring
            r = profile["radius"] + math.sin(self.orbit_angle * 3.0 + self.orbit_phase) * 2.6
            y = profile["y_band"] + math.cos(self.orbit_angle * 2.0 + self.orbit_phase) * 3.4
            goal = [
                math.cos(self.orbit_angle) * r,
                y,
                math.sin(self.orbit_angle) * r,
            ]
            self._steer_toward(goal, dt, max_spd=spec.max_speed * 0.58, slow_radius=2.0)

        elif self.state == SentinelState.VECTORING and self.target_position:
            # Approach target in a 3D spherical pack pincer formation
            tx, ty, tz = self.target_position
            standoff = 3.2
            ring_ang = self.orbit_phase + slot_angle
            goal = [
                tx + math.cos(ring_ang) * standoff,
                ty + slot_elev,
                tz + math.sin(ring_ang) * standoff,
            ]
            # Doctrine tag HUNTER-KILLER uses a higher steer speed
            spd_boost = 1.25 if self.doctrine == "HUNTER-KILLER" else 1.08
            self._steer_toward(goal, dt, max_spd=spec.max_speed * spd_boost, slow_radius=4.2)

        elif self.state in {
            SentinelState.ENGAGED_HARVEST,
            SentinelState.ENGAGED_SANITIZE,
            SentinelState.ENGAGED_DEFENSE,
            SentinelState.QUARANTINING,
        } and self.target_position:
            # 3D Spherical Pack Encirclement: each unit in the pack orbits the target at its own slot angle
            tx, ty, tz = self.target_position
            orbit_rate = 2.15 if self.doctrine == "HUNTER-KILLER" else 1.65
            self.orbit_angle = (self.orbit_angle + orbit_rate * dt) % (math.pi * 2.0)
            hover_r = 3.1 if self.state != SentinelState.QUARANTINING else 2.5
            ang = self.orbit_angle + slot_angle
            goal = [
                tx + math.cos(ang) * hover_r,
                ty + math.sin(ang * 2.0) * 1.15 + slot_elev * 0.65,
                tz + math.sin(ang) * hover_r,
            ]
            self._steer_toward(goal, dt, max_spd=spec.max_speed * 0.85, slow_radius=1.2)
            # Point carapace and tentacles directly inward at the target core
            self._face_point(self.target_position)

        elif self.state == SentinelState.RETURNING:
            # Stream back to Arelis Core [0, 0, 0] carrying the harvested data orb
            ang = self.orbit_phase + slot_angle
            goal = [
                math.cos(ang) * 3.2,
                math.sin(ang) * 1.2,
                math.sin(ang) * 3.2,
            ]
            self._steer_toward(goal, dt, max_spd=spec.max_speed * 0.95, slow_radius=4.0)

        # Full 3D Boids Forces: Separation + Same-Caste/Pack Alignment & Ribbon Cohesion
        sep_x, sep_y, sep_z = 0.0, 0.0, 0.0
        align_vx, align_vy, align_vz = 0.0, 0.0, 0.0
        coh_x, coh_y, coh_z = 0.0, 0.0, 0.0
        flock_count = 0

        min_sep = 2.85 * spec.scale
        flock_radius2 = 14.0 * 14.0

        for other in neighbors:
            if other.unit_id == self.unit_id or other.state == SentinelState.EMP_DISABLED:
                continue
            rx = self.position[0] - other.position[0]
            ry = self.position[1] - other.position[1]
            rz = self.position[2] - other.position[2]
            d2 = rx * rx + ry * ry + rz * rz
            if 0.0001 < d2 < (min_sep * min_sep):
                d = math.sqrt(d2)
                push = (min_sep - d) / d
                sep_x += rx * push * 19.0
                sep_y += ry * push * 19.0
                sep_z += rz * push * 19.0

            # Schooling alignment & cohesion with packmates or same-caste units
            same_group = (self.pack_id is not None and self.pack_id == other.pack_id) or (
                self.state == SentinelState.PATROLLING
                and other.state == SentinelState.PATROLLING
                and self.caste == other.caste
            )
            if same_group and d2 < flock_radius2:
                align_vx += other.velocity[0]
                align_vy += other.velocity[1]
                align_vz += other.velocity[2]
                coh_x += other.position[0]
                coh_y += other.position[1]
                coh_z += other.position[2]
                flock_count += 1

        self.velocity[0] += sep_x * dt
        self.velocity[1] += sep_y * dt
        self.velocity[2] += sep_z * dt

        if flock_count > 0 and self.state in {SentinelState.PATROLLING, SentinelState.VECTORING, SentinelState.RETURNING}:
            inv_n = 1.0 / flock_count
            # Alignment: match velocity vector of packmates for Matrix squid-ribbon streaming
            self.velocity[0] += ((align_vx * inv_n) - self.velocity[0]) * 1.35 * dt
            self.velocity[1] += ((align_vy * inv_n) - self.velocity[1]) * 1.35 * dt
            self.velocity[2] += ((align_vz * inv_n) - self.velocity[2]) * 1.35 * dt
            # Subtle cohesion toward pack center
            self.velocity[0] += ((coh_x * inv_n) - self.position[0]) * 0.55 * dt
            self.velocity[1] += ((coh_y * inv_n) - self.position[1]) * 0.55 * dt
            self.velocity[2] += ((coh_z * inv_n) - self.position[2]) * 0.55 * dt

        self.doctrine = self.resolve_active_doctrine()
        self._integrate(dt, max_spd=spec.max_speed * 1.25)

    def _steer_toward(
        self,
        goal: list[float],
        dt: float,
        *,
        max_spd: float,
        slow_radius: float,
    ) -> None:
        dx = goal[0] - self.position[0]
        dy = goal[1] - self.position[1]
        dz = goal[2] - self.position[2]
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        if dist < 0.001:
            return
        target_spd = max_spd if dist > slow_radius else max_spd * (dist / slow_radius)
        desired_vx = (dx / dist) * target_spd
        desired_vy = (dy / dist) * target_spd
        desired_vz = (dz / dist) * target_spd

        steer_rate = min(1.0, self.spec.accel * dt / max(1.0, max_spd))
        self.velocity[0] += (desired_vx - self.velocity[0]) * steer_rate
        self.velocity[1] += (desired_vy - self.velocity[1]) * steer_rate
        self.velocity[2] += (desired_vz - self.velocity[2]) * steer_rate

    def _face_point(self, pt: list[float]) -> None:
        dx = pt[0] - self.position[0]
        dy = pt[1] - self.position[1]
        dz = pt[2] - self.position[2]
        mag = math.sqrt(dx * dx + dy * dy + dz * dz)
        if mag > 0.001:
            self.heading = [dx / mag, dy / mag, dz / mag]

    def _integrate(self, dt: float, *, max_spd: float) -> None:
        vx, vy, vz = self.velocity
        spd = math.sqrt(vx * vx + vy * vy + vz * vz)
        if spd > max_spd and spd > 0.0:
            scale = max_spd / spd
            vx *= scale
            vy *= scale
            vz *= scale
            self.velocity = [vx, vy, vz]
            spd = max_spd

        self.position[0] += vx * dt
        self.position[1] += vy * dt
        self.position[2] += vz * dt

        if spd > 1.25 and self.state not in {
            SentinelState.ENGAGED_HARVEST,
            SentinelState.ENGAGED_SANITIZE,
            SentinelState.ENGAGED_DEFENSE,
            SentinelState.QUARANTINING,
        }:
            tx, ty, tz = vx / spd, vy / spd, vz / spd
            blend = min(1.0, dt * 10.0)
            hx = self.heading[0] + (tx - self.heading[0]) * blend
            hy = self.heading[1] + (ty - self.heading[1]) * blend
            hz = self.heading[2] + (tz - self.heading[2]) * blend
            hmag = math.sqrt(hx * hx + hy * hy + hz * hz)
            if hmag > 1e-4:
                self.heading = [hx / hmag, hy / hmag, hz / hmag]

    def to_dict(self) -> dict[str, Any]:
        spec = self.spec
        return {
            "unit_id": self.unit_id,
            "caste": self.caste,
            "tier": self.tier,
            "version": self.version,
            "doctrine": self.doctrine,
            "pack_id": self.pack_id,
            "pack_role": self.pack_role,
            "pack_slot": self.pack_slot,
            "pack_size": self.pack_size,
            "tentacles": spec.tentacles,
            "scale": spec.scale,
            "state": str(self.state),
            "position": [round(c, 3) for c in self.position],
            "velocity": [round(c, 3) for c in self.velocity],
            "heading": [round(c, 3) for c in self.heading],
            "target_node_id": self.target_node_id,
            "current_task": self.current_task,
            "laser_active": self.laser_active,
            "laser_target": [round(c, 3) for c in self.laser_target] if self.laser_target else None,
            "laser_kind": self.laser_kind,
            "carrying_orb": self.carrying_orb,
            "orb_color": self.orb_color,
            "missions_completed": self.missions_completed,
            "bytes_processed": self.bytes_processed,
            "threats_neutralized": self.threats_neutralized,
            "security_events": self.security_events,
        }
