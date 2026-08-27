"""Free camera in metres. Not a burn, not a lock, not a spacecraft.

WASD/QE flies the eye. Wheel dollies along look; Shift+wheel is travel
speed. Travel to warps to a sunlit approach standoff (~8× IAU radius),
which sits outside the catalog stop-sphere. That warp is not an N-body burn.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from arelis.physics.constants import AU_M

SPEED_MIN = 10.0
SPEED_MAX = 5.0e11  # ~3 AU/s. Slider and wheel share this range.

# look() is camera-relative and does not clamp. Pitch ±90° is straight
# up/down; going further tumbles over the pole. look_basis picks a
# fallback axis if the up hint is parallel to forward.
WORLD_UP: tuple[float, float, float] = (0.0, 1.0, 0.0)

# Mean Neptune a. Overview never frames tighter than the giant-planet system.
SOLAR_SPAN_M = 30.07 * AU_M


def overview_distance(span_m: float, *, fov_y: float = 0.70) -> float:
    """Camera distance so a heliocentric span fits in the vertical FOV with margin."""
    half = max(float(span_m), AU_M)
    return half / math.tan(max(float(fov_y), 0.2) * 0.35)


def speed_label(mps: float) -> str:
    v = max(float(mps), 0.0)
    if v >= 0.01 * AU_M:
        return f"{v / AU_M:.3g} AU/s"
    if v >= 1000.0:
        return f"{v / 1000.0:.3g} km/s"
    return f"{v:.3g} m/s"


@dataclass
class FlyCamera:
    """Eye in ECLIPJ2000 metres. Wheel is travel speed, not zoom-to-lock."""

    yaw: float = 1.45
    pitch: float = 0.38
    x: float = 2.2e11
    y: float = 7.4e10
    z: float = 1.0e11
    speed: float = 3.0e7
    distance: float = 3.0e11
    min_distance: float = 0.12 * AU_M
    max_distance: float = 2.6e13
    up: tuple[float, float, float] = WORLD_UP

    def forward(self) -> tuple[float, float, float]:
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        return (cp * cy, sp, cp * sy)

    def basis(
        self,
    ) -> tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]:
        fx, fy, fz = self.forward()
        return look_basis(
            (self.x, self.y, self.z),
            (self.x + fx, self.y + fy, self.z + fz),
            self.up,
        )

    def look(self, dyaw: float, dpitch: float) -> None:
        """Yaw about camera up, pitch about camera right. No pole clamp."""
        if dyaw == 0.0 and dpitch == 0.0:
            return
        right, up, fwd = self.basis()
        # Signs match the old yaw+= / pitch+= convention: drag left, arrow up.
        if dyaw != 0.0:
            fwd = _rodrigues(fwd, up, -dyaw)
            right = _rodrigues(right, up, -dyaw)
        if dpitch != 0.0:
            fwd = _rodrigues(fwd, right, -dpitch)
            up = _rodrigues(up, right, -dpitch)
        fwd = _unit3(fwd)
        # Keep up orthonormal to forward so a tumble over the pole does not snap.
        d = fwd[0] * up[0] + fwd[1] * up[1] + fwd[2] * up[2]
        up = _unit3((up[0] - fwd[0] * d, up[1] - fwd[1] * d, up[2] - fwd[2] * d))
        self.up = up
        self.pitch = math.asin(max(-1.0, min(1.0, fwd[1])))
        self.yaw = math.atan2(fwd[2], fwd[0])

    def nudge_speed(self, factor: float) -> None:
        self.speed = min(SPEED_MAX, max(SPEED_MIN, self.speed * float(factor)))

    def speed_u(self) -> float:
        span = math.log(SPEED_MAX / SPEED_MIN)
        return math.log(max(self.speed, SPEED_MIN) / SPEED_MIN) / span

    def set_speed_u(self, u: float) -> None:
        t = min(1.0, max(0.0, float(u)))
        self.speed = SPEED_MIN * (SPEED_MAX / SPEED_MIN) ** t

    def fly(self, fwd: float, right: float, up: float, dt: float) -> None:
        if dt <= 0.0:
            return
        bx, by, bz = self.basis()
        s = self.speed * dt
        self.x += (fwd * bz[0] + right * bx[0] + up * by[0]) * s
        self.y += (fwd * bz[1] + right * bx[1] + up * by[1]) * s
        self.z += (fwd * bz[2] + right * bx[2] + up * by[2]) * s

    def look_at(self, tx: float, ty: float, tz: float) -> None:
        self.up = WORLD_UP
        dx, dy, dz = tx - self.x, ty - self.y, tz - self.z
        n = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        self.pitch = math.asin(max(-1.0, min(1.0, dy / n)))
        self.yaw = math.atan2(dz, dx)

    def place_looking_at(self, tx: float, ty: float, tz: float, dist: float) -> None:
        self.distance = float(dist)
        fx, fy, fz = self.forward()
        self.x = tx - fx * self.distance
        self.y = ty - fy * self.distance
        self.z = tz - fz * self.distance

    def travel_to(
        self,
        tx: float,
        ty: float,
        tz: float,
        radius: float,
        sun: tuple[float, float, float] | None = None,
    ) -> None:
        """Camera warp to a sunlit approach standoff. Not an N-body burn.

        ``radius`` is the IAU mean (or 1-bar) radius from the catalog, not
        the atmosphere envelope. 8× that radius is still outside Karman.
        """
        r = max(float(radius), 1.0)
        standoff = max(r * 8.0, r * 2.5)
        if r >= 1.0e8:
            standoff = max(standoff, 0.12 * AU_M)
        self.min_distance = max(r * 2.5, 1.0e3)
        self.distance = standoff
        if sun is not None:
            sx, sy, sz = sun
            dx, dy, dz = sx - tx, sy - ty, sz - tz
            n = math.sqrt(dx * dx + dy * dy + dz * dz)
            if n > r:
                dx, dy, dz = dx / n, dy / n, dz / n
                nx, ny, nz = 0.0, 0.0, 1.0
                if abs(dz) > 0.92:
                    nx, ny, nz = 0.0, 1.0, 0.0
                px = ny * dz - nz * dy
                py = nz * dx - nx * dz
                pz = nx * dy - ny * dx
                pl = math.sqrt(px * px + py * py + pz * pz)
                if pl > 1e-9:
                    px, py, pz = px / pl, py / pl, pz / pl
                    nx = py * dz - pz * dy
                    ny = pz * dx - px * dz
                    nz = px * dy - py * dx
                    nl = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
                    nx, ny, nz = nx / nl, ny / nl, nz / nl
                self.x = tx + dx * standoff + nx * standoff * 0.28
                self.y = ty + dy * standoff + ny * standoff * 0.28
                self.z = tz + dz * standoff + nz * standoff * 0.28
                self.look_at(tx, ty, tz)
            else:
                self.place_looking_at(tx, ty, tz, standoff)
                self.look_at(tx, ty, tz)
        else:
            self.place_looking_at(tx, ty, tz, standoff)
            self.look_at(tx, ty, tz)
        cap = max(SPEED_MIN, standoff * 0.35)
        if self.speed > cap:
            self.speed = cap

    def approach(self, factor: float) -> None:
        old = self.distance
        self.distance = min(
            self.max_distance,
            max(self.min_distance, self.distance * float(factor)),
        )
        step = old - self.distance
        fx, fy, fz = self.forward()
        self.x += fx * step
        self.y += fy * step
        self.z += fz * step

    def fit_overview(self, radius: float) -> None:
        r = max(float(radius), 1.0e6)
        self.min_distance = max(0.12 * AU_M, r * 2.5)
        self.distance = max(3.0e11, self.min_distance * 2.0)
        self.yaw = 1.45
        self.pitch = 0.38
        self.up = WORLD_UP
        self.place_looking_at(0.0, 0.0, 0.0, self.distance)

    def frame_system(self, span_m: float, *, fov_y: float = 0.70) -> None:
        """Pull back until the heliocentric span fits. Does not change IAU radii."""
        dist = overview_distance(span_m, fov_y=fov_y)
        self.max_distance = max(self.max_distance, dist * 1.35)
        self.min_distance = 0.12 * AU_M
        self.distance = dist
        self.yaw = 1.45
        self.pitch = 0.38
        self.up = WORLD_UP
        self.speed = min(SPEED_MAX, max(8.0e7, dist * 0.12))

    def fit_approach(self, radius: float) -> None:
        r = max(float(radius), 1.0e3)
        self.min_distance = r * 2.5
        self.distance = max(self.min_distance, r * 8.0)
        self.up = WORLD_UP
        self.place_looking_at(0.0, 0.0, 0.0, self.distance)

    def project(
        self,
        point: tuple[float, float, float],
        target: tuple[float, float, float],
        width: int,
        height: int,
        *,
        fov_y: float = 0.70,
        eye: tuple[float, float, float] | None = None,
    ) -> tuple[float, float, float] | None:
        """Return pixel x, y and camera-space depth (positive in front)."""
        cam_eye = eye if eye is not None else (self.x, self.y, self.z)
        return project_with_basis(
            point,
            cam_eye,
            look_basis(cam_eye, target, self.up),
            width,
            height,
            fov_y=fov_y,
        )


def project_with_basis(
    point: tuple[float, float, float],
    eye: tuple[float, float, float],
    basis: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ],
    width: int,
    height: int,
    *,
    fov_y: float = 0.70,
) -> tuple[float, float, float] | None:
    """Pinhole project against an already-built basis.

    The overlay projects every body several times a frame; rebuilding the look
    basis inside each call was two square roots per point for no new answer.
    """
    fx, fy, fz = basis
    px = point[0] - eye[0]
    py = point[1] - eye[1]
    pz = point[2] - eye[2]
    cam_z = px * fz[0] + py * fz[1] + pz * fz[2]
    if cam_z <= 1.0:
        return None
    cam_x = px * fx[0] + py * fx[1] + pz * fx[2]
    cam_y = px * fy[0] + py * fy[1] + pz * fy[2]
    sy = 1.0 / math.tan(fov_y * 0.5)
    sx = sy / (width / max(height, 1))
    ndc_x = (cam_x * sx) / cam_z
    ndc_y = (cam_y * sy) / cam_z
    if abs(ndc_x) > 4.0 or abs(ndc_y) > 4.0:
        return None
    return (
        (ndc_x * 0.5 + 0.5) * width,
        (0.5 - ndc_y * 0.5) * height,
        cam_z,
    )


def look_basis(
    eye: tuple[float, float, float],
    target: tuple[float, float, float],
    up: tuple[float, float, float] = WORLD_UP,
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    """Orthonormal camera axes: right, up, forward. Hint may leave world-up."""
    f = (
        target[0] - eye[0],
        target[1] - eye[1],
        target[2] - eye[2],
    )
    fl = math.sqrt(f[0] * f[0] + f[1] * f[1] + f[2] * f[2]) or 1.0
    fz = (f[0] / fl, f[1] / fl, f[2] / fl)
    ul = math.sqrt(up[0] * up[0] + up[1] * up[1] + up[2] * up[2]) or 1.0
    hint = (up[0] / ul, up[1] / ul, up[2] / ul)
    fx = (
        hint[1] * fz[2] - hint[2] * fz[1],
        hint[2] * fz[0] - hint[0] * fz[2],
        hint[0] * fz[1] - hint[1] * fz[0],
    )
    xl = math.sqrt(fx[0] * fx[0] + fx[1] * fx[1] + fx[2] * fx[2])
    if xl < 1e-8:
        alt = (0.0, 0.0, 1.0) if abs(hint[1]) > 0.7 else WORLD_UP
        fx = (
            alt[1] * fz[2] - alt[2] * fz[1],
            alt[2] * fz[0] - alt[0] * fz[2],
            alt[0] * fz[1] - alt[1] * fz[0],
        )
        xl = math.sqrt(fx[0] * fx[0] + fx[1] * fx[1] + fx[2] * fx[2]) or 1.0
    fx = (fx[0] / xl, fx[1] / xl, fx[2] / xl)
    fy = (
        fz[1] * fx[2] - fz[2] * fx[1],
        fz[2] * fx[0] - fz[0] * fx[2],
        fz[0] * fx[1] - fz[1] * fx[0],
    )
    return fx, fy, fz


def _unit3(
    v: tuple[float, float, float],
) -> tuple[float, float, float]:
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def _rodrigues(
    v: tuple[float, float, float],
    k: tuple[float, float, float],
    ang: float,
) -> tuple[float, float, float]:
    cx, sx = math.cos(ang), math.sin(ang)
    vx, vy, vz = v
    kx, ky, kz = k
    dot = kx * vx + ky * vy + kz * vz
    cr = (ky * vz - kz * vy, kz * vx - kx * vz, kx * vy - ky * vx)
    om = 1.0 - cx
    return (
        vx * cx + cr[0] * sx + kx * dot * om,
        vy * cx + cr[1] * sx + ky * dot * om,
        vz * cx + cr[2] * sx + kz * dot * om,
    )
