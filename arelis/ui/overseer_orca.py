"""ORCA velocity avoidance and critically damped presentation smoothing (SPEC 3.2)."""
from __future__ import annotations

import math
from typing import Any

import numpy as np

ORCA_TAU = 2.0
ORCA_CELL = 10.0
ORCA_NBR_DIST = 10.0
ORCA_MAX_NBR = 10
# ORCA radius is the capsule radius. The hard constraint is non-penetration,
# not a kept gap; units may come right up to each other.
PROJ_MAX_PASSES = 2
PROJ_MAX_MOVE = 0.05
SMOOTH_T = 0.25
SMOOTH_OMEGA = 2.0 / SMOOTH_T
GAP_MIN_DEFAULT = 0.0


def cam_basis(p: np.ndarray, cam_pos: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    f = p - cam_pos
    f = f / (np.linalg.norm(f) + 1e-9)
    up = np.array([0.0, 1.0, 0.0])
    if abs(float(np.dot(up, f))) > 0.95:
        up = np.array([1.0, 0.0, 0.0])
    e1 = np.cross(up, f)
    e1 = e1 / (np.linalg.norm(e1) + 1e-9)
    e2 = np.cross(f, e1)
    e2 = e2 / (np.linalg.norm(e2) + 1e-9)
    return e1, e2, f


def to2(v: np.ndarray, e1: np.ndarray, e2: np.ndarray) -> np.ndarray:
    return np.array([float(np.dot(v, e1)), float(np.dot(v, e2))], dtype=np.float64)


def vo_u(
    p_rel: np.ndarray, v_rel: np.ndarray, radius: float, tau: float
) -> tuple[np.ndarray, np.ndarray]:
    dist_sq = float(np.dot(p_rel, p_rel))
    r_sq = radius * radius
    if dist_sq > r_sq:
        w = v_rel - p_rel / tau
        w_len_sq = float(np.dot(w, w))
        dp = float(np.dot(w, p_rel))
        if dp < 0.0 and dp * dp > r_sq * w_len_sq:
            w_len = math.sqrt(max(w_len_sq, 1e-16))
            n = w / w_len
            u = (radius / tau - w_len) * n
            return n, u
        leg = math.sqrt(max(dist_sq - r_sq, 0.0))
        if (p_rel[0] * w[1] - p_rel[1] * w[0]) > 0.0:
            direction = np.array([
                p_rel[0] * leg - p_rel[1] * radius,
                p_rel[0] * radius + p_rel[1] * leg,
            ]) / dist_sq
        else:
            direction = -np.array([
                p_rel[0] * leg + p_rel[1] * radius,
                -p_rel[0] * radius + p_rel[1] * leg,
            ]) / dist_sq
        dlen = math.sqrt(float(np.dot(direction, direction))) + 1e-12
        direction = direction / dlen
        u = float(np.dot(v_rel, direction)) * direction - v_rel
        n = np.array([-direction[1], direction[0]])
        if float(np.dot(n, u)) < 0.0:
            n = -n
        nlen = math.sqrt(float(np.dot(n, n))) + 1e-12
        return n / nlen, u
    inv_time = 1.0 / max(tau * 0.15, 1e-3)
    w = v_rel - p_rel * inv_time
    w_len = math.sqrt(float(np.dot(w, w))) + 1e-12
    n = w / w_len
    u = (radius * inv_time - w_len) * n
    return n, u


def _lp1_scalar(
    lines: list[tuple[float, float, float, float]],
    line_i: int,
    vmax: float,
    prefx: float,
    prefy: float,
) -> tuple[float, float] | None:
    dx, dy, px, py = lines[line_i]
    t = (prefx - px) * dx + (prefy - py) * dy
    b = 2.0 * (px * dx + py * dy)
    c = (px * px + py * py) - vmax * vmax
    det = b * b - 4.0 * c
    if det < 0.0:
        return None
    sdet = math.sqrt(det)
    t_left = (-b - sdet) * 0.5
    t_right = (-b + sdet) * 0.5
    for j in range(line_i):
        d2x, d2y, p2x, p2y = lines[j]
        n2x, n2y = -d2y, d2x
        den = dx * n2x + dy * n2y
        num = (p2x - px) * n2x + (p2y - py) * n2y
        if abs(den) <= 1e-8:
            if num < -1e-8:
                return None
            continue
        t_hit = num / den
        if den > 0.0:
            if t_hit < t_right:
                t_right = t_hit
        else:
            if t_hit > t_left:
                t_left = t_hit
        if t_left > t_right + 1e-8:
            return None
    if t < t_left:
        t = t_left
    elif t > t_right:
        t = t_right
    return px + t * dx, py + t * dy


def _lp2_scalar(
    lines: list[tuple[float, float, float, float]],
    prefx: float,
    prefy: float,
    vmax: float,
) -> tuple[float, float, bool]:
    rx, ry = prefx, prefy
    sp = math.hypot(rx, ry)
    if sp > vmax > 0.0:
        s = vmax / sp
        rx *= s
        ry *= s
    for i, (dx, dy, px, py) in enumerate(lines):
        if (rx - px) * (-dy) + (ry - py) * dx >= -1e-8:
            continue
        cand = _lp1_scalar(lines, i, vmax, prefx, prefy)
        if cand is None:
            return rx, ry, False
        rx, ry = cand
    return rx, ry, True


def _lp3_scalar(
    lines: list[tuple[float, float, float, float]],
    prefx: float,
    prefy: float,
    vmax: float,
) -> tuple[float, float]:
    """Greedy projection when the 2D linear program is infeasible."""
    rx, ry = prefx, prefy
    for _ in range(4):
        for dx, dy, px, py in lines:
            nx, ny = -dy, dx
            viol = -((rx - px) * nx + (ry - py) * ny)
            if viol > 0.0:
                rx += nx * viol
                ry += ny * viol
        sp = math.hypot(rx, ry)
        if sp > vmax > 0.0:
            s = vmax / sp
            rx *= s
            ry *= s
    return rx, ry


def _lp1(lines, line_i, vmax, pref):
    slines = [
        (float(d[0]), float(d[1]), float(p[0]), float(p[1])) for d, p in lines
    ]
    res = _lp1_scalar(slines, line_i, float(vmax), float(pref[0]), float(pref[1]))
    return None if res is None else np.array([res[0], res[1]], dtype=np.float64)


def _lp2(lines, pref, vmax):
    slines = [
        (float(d[0]), float(d[1]), float(p[0]), float(p[1])) for d, p in lines
    ]
    rx, ry, ok = _lp2_scalar(slines, float(pref[0]), float(pref[1]), float(vmax))
    return np.array([rx, ry], dtype=np.float64), ok


def _lp3(lines, pref, vmax):
    """Greedy projection when the 2D linear program is infeasible."""
    slines = [
        (float(d[0]), float(d[1]), float(p[0]), float(p[1])) for d, p in lines
    ]
    rx, ry = _lp3_scalar(slines, float(pref[0]), float(pref[1]), float(vmax))
    return np.array([rx, ry], dtype=np.float64)


def orca_step(
    P, V, pref, radii, mass, live, amax, vmax, dt, cam_pos,
    gap_min=GAP_MIN_DEFAULT, tau=ORCA_TAU, samples=None,
):
    n_agents = len(P)
    out = pref.copy()
    cell = ORCA_CELL
    keys = {}
    for i in range(n_agents):
        if not live[i]:
            continue
        gx = math.floor(P[i, 0] / cell)
        gy = math.floor(P[i, 1] / cell)
        gz = math.floor(P[i, 2] / cell)
        keys.setdefault((gx, gy, gz), []).append(i)

    def neighbours(i):
        gx = math.floor(P[i, 0] / cell)
        gy = math.floor(P[i, 1] / cell)
        gz = math.floor(P[i, 2] / cell)
        found = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    found.extend(keys.get((gx + dx, gy + dy, gz + dz), ()))
        f = P[i] - cam_pos
        f = f / (np.linalg.norm(f) + 1e-9)
        scored = []
        for j in found:
            if j == i or not live[j]:
                continue
            delta = P[j] - P[i]
            if float(np.dot(delta, delta)) > ORCA_NBR_DIST * ORCA_NBR_DIST:
                continue
            d = delta - np.dot(delta, f) * f
            scored.append((float(np.dot(d, d)), j))
        scored.sort()
        return [j for _, j in scored[:ORCA_MAX_NBR]]

    for i in range(n_agents):
        if not live[i]:
            out[i] = 0.0
            continue
        e1, e2, fwd = cam_basis(P[i], cam_pos)
        pref2 = to2(pref[i], e1, e2)
        v2 = to2(V[i], e1, e2)
        lines = []
        for j in neighbours(i):
            v_rel = to2(V[i] - V[j], e1, e2)
            if samples is not None:
                sample_x, sample_r = samples
                best_g = 1e18
                p_rel = to2(P[j] - P[i], e1, e2)
                r = float(radii[i] + radii[j] + gap_min)
                for a in range(sample_x.shape[1]):
                    for b in range(sample_x.shape[1]):
                        pr = to2(sample_x[j, b] - sample_x[i, a], e1, e2)
                        rr = float(sample_r[i, a] + sample_r[j, b] + gap_min)
                        g = math.sqrt(float(np.dot(pr, pr)) + 1e-16) - rr
                        if g < best_g:
                            best_g = g
                            p_rel, r = pr, rr
            else:
                p_rel = to2(P[j] - P[i], e1, e2)
                r = float(radii[i] + radii[j] + gap_min)
            n, u = vo_u(p_rel, v_rel, r, tau)
            if mass[i] < mass[j] - 1e-9:
                resp = 1.0
            elif mass[i] > mass[j] + 1e-9:
                resp = 0.0
            else:
                resp = 0.5
            if resp <= 0.0 and float(np.dot(u, u)) < 1e-12:
                continue
            point = v2 + resp * u
            # Tangent whose left-normal is n (allowed half-plane: (v-point)·n >= 0).
            direction = np.array([n[1], -n[0]])
            dlen = math.sqrt(float(np.dot(direction, direction))) + 1e-12
            direction = direction / dlen
            lines.append((direction, point))
        spd_lim = max(float(vmax[i]), 0.05)
        result, ok = _lp2(lines, pref2, spd_lim)
        if not ok:
            result = _lp3(lines, pref2, spd_lim)
        v3 = result[0] * e1 + result[1] * e2
        v3 = v3 + fwd * float(np.dot(pref[i], fwd))
        dv = v3 - V[i]
        cap = float(amax[i]) * dt
        dn = float(np.linalg.norm(dv))
        if dn > cap > 0:
            v3 = V[i] + dv * (cap / dn)
        out[i] = v3
    return out


class Smoother:
    def __init__(self, n=0):
        self.x = np.zeros((n, 3))
        self.v = np.zeros((n, 3))
        self.yaw = np.zeros(n)
        self.yaw_v = np.zeros(n)
        self.ready = False

    def resize(self, n):
        if self.x.shape[0] != n:
            self.x = np.zeros((n, 3))
            self.v = np.zeros((n, 3))
            self.yaw = np.zeros(n)
            self.yaw_v = np.zeros(n)
            self.ready = False

    def snap(self, p, yaw, mask=None):
        if mask is None:
            self.x = p.copy()
            self.v[:] = 0.0
            self.yaw = yaw.copy()
            self.yaw_v[:] = 0.0
            self.ready = True
            return
        self.x[mask] = p[mask]
        self.v[mask] = 0.0
        self.yaw[mask] = yaw[mask]
        self.yaw_v[mask] = 0.0

    def step(self, p, yaw, dt):
        if not self.ready or self.x.shape != p.shape:
            self.resize(len(p))
            self.snap(p, yaw)
            return self.x.copy(), self.yaw.copy()
        om = SMOOTH_OMEGA
        self.x = self.x + self.v * dt
        self.v = self.v + (om * om * (p - self.x) - 2.0 * om * self.v) * dt
        dy = (yaw - self.yaw + math.pi) % (2 * math.pi) - math.pi
        target = self.yaw + dy
        self.yaw = self.yaw + self.yaw_v * dt
        self.yaw_v = self.yaw_v + (om * om * (target - self.yaw) - 2.0 * om * self.yaw_v) * dt
        self.yaw = (self.yaw + math.pi) % (2 * math.pi) - math.pi
        return self.x.copy(), self.yaw.copy()


class OrcaPairSolver:
    """Reusable ORCA half-planes for one set of positions and capsule pairs.

    Camera bases and neighbor constraints depend only on P, mass, and the
    pair gaps; V and preferred velocity change across the two (or three)
    solves in Sim.step. Building them once keeps the 100-unit path bounded
    by N * ORCA_MAX_NBR per solve instead of walking every cap_pairs hit
    three times.
    """

    def __init__(
        self,
        P,
        mass,
        live,
        vmax,
        cam_pos,
        pair_i,
        pair_j,
        gaps,
        normals,
        gap_min=GAP_MIN_DEFAULT,
        tau=ORCA_TAU,
    ):
        n_agents = len(P)
        live_arr = np.asarray(live, dtype=bool)
        live_list = live_arr.tolist()
        self.vmax = [max(float(v), 0.05) for v in vmax]
        self.live = live_arr
        self._live_list = live_list
        self.n_agents = n_agents

        p_list = np.asarray(P, dtype=np.float64).tolist()
        mass_list = [float(m) for m in mass]
        cx, cy, cz = float(cam_pos[0]), float(cam_pos[1]), float(cam_pos[2])

        # Same scalar cam_basis and pair walk as orca_from_pairs, computed once.
        basis: list[tuple[float, float, float, float, float, float, float, float, float] | None] = [
            None
        ] * n_agents
        for i in range(n_agents):
            if not live_list[i]:
                continue
            px, py, pz = p_list[i]
            fx, fy, fz = px - cx, py - cy, pz - cz
            fl = math.sqrt(fx * fx + fy * fy + fz * fz) + 1e-9
            fx /= fl
            fy /= fl
            fz /= fl
            if abs(fy) > 0.95:
                # up = (1, 0, 0); cross(up, f) = (0, -fz, fy)
                e1x, e1y, e1z = 0.0, -fz, fy
            else:
                # up = (0, 1, 0); cross(up, f) = (fz, 0, -fx)
                e1x, e1y, e1z = fz, 0.0, -fx
            e1l = math.sqrt(e1x * e1x + e1y * e1y + e1z * e1z) + 1e-9
            e1x /= e1l
            e1y /= e1l
            e1z /= e1l
            # e2 = cross(f, e1)
            e2x = fy * e1z - fz * e1y
            e2y = fz * e1x - fx * e1z
            e2z = fx * e1y - fy * e1x
            e2l = math.sqrt(e2x * e2x + e2y * e2y + e2z * e2z) + 1e-9
            e2x /= e2l
            e2y /= e2l
            e2z /= e2l
            basis[i] = (e1x, e1y, e1z, e2x, e2y, e2z, fx, fy, fz)
        self._basis = basis

        cons: list[list[tuple[float, int, float, float, float, float]]] = [
            [] for _ in range(n_agents)
        ]
        nbr_dist_sq = ORCA_NBR_DIST * ORCA_NBR_DIST
        gap_min_f = float(gap_min)
        inv_tau = 1.0 / max(float(tau), 1e-3)
        pi_list = pair_i.tolist() if hasattr(pair_i, "tolist") else list(pair_i)
        pj_list = pair_j.tolist() if hasattr(pair_j, "tolist") else list(pair_j)
        g_list = gaps.tolist() if hasattr(gaps, "tolist") else list(gaps)
        n_list = normals.tolist() if hasattr(normals, "tolist") else list(normals)
        for k in range(len(pi_list)):
            i = int(pi_list[k])
            j = int(pj_list[k])
            if not live_list[i] or not live_list[j]:
                continue
            pix, piy, piz = p_list[i]
            pjx, pjy, pjz = p_list[j]
            ddx, ddy, ddz = pix - pjx, piy - pjy, piz - pjz
            if ddx * ddx + ddy * ddy + ddz * ddz > nbr_dist_sq:
                continue
            nk = n_list[k]
            nx, ny, nz = float(nk[0]), float(nk[1]), float(nk[2])
            ln = math.sqrt(nx * nx + ny * ny + nz * nz)
            if ln < 1e-8:
                continue
            inv_ln = 1.0 / ln
            nx *= inv_ln
            ny *= inv_ln
            nz *= inv_ln
            gk = float(g_list[k])
            rhs_rel = (gap_min_f - gk) * inv_tau
            if gk < 0.0:
                ri, rj = 0.5, 0.5
            elif mass_list[i] < mass_list[j] - 1e-9:
                ri, rj = 1.0, 0.0
            elif mass_list[i] > mass_list[j] + 1e-9:
                ri, rj = 0.0, 1.0
            else:
                ri, rj = 0.5, 0.5
            if ri > 0.0:
                cons[i].append((rhs_rel, j, nx, ny, nz, ri))
            if rj > 0.0:
                cons[j].append((rhs_rel, i, -nx, -ny, -nz, rj))

        linespec: list[list[tuple[Any, ...]] | None] = [None] * n_agents
        for i in range(n_agents):
            b_i = basis[i]
            if b_i is None:
                continue
            e1x, e1y, e1z, e2x, e2y, e2z, fx, fy, fz = b_i
            neigh = cons[i]
            if not neigh:
                linespec[i] = []
                continue
            neigh.sort(reverse=True)
            specs = []
            for rhs, j, nx, ny, nz, resp in neigh[:ORCA_MAX_NBR]:
                n2x = nx * e1x + ny * e1y + nz * e1z
                n2y = nx * e2x + ny * e2y + nz * e2z
                plen = math.hypot(n2x, n2y)
                if plen < 0.15:
                    continue
                inv_plen = 1.0 / plen
                n2x *= inv_plen
                n2y *= inv_plen
                fwd_n3 = fx * nx + fy * ny + fz * nz
                specs.append(
                    (rhs, j, nx, ny, nz, resp, n2x, n2y, inv_plen, n2y, -n2x, fwd_n3)
                )
            linespec[i] = specs
        self.linespec = linespec

    def solve(self, V, pref):
        v_list = np.asarray(V, dtype=np.float64).tolist()
        pref_list = np.asarray(pref, dtype=np.float64).tolist()
        out_rows = [[0.0, 0.0, 0.0] for _ in range(self.n_agents)]
        basis = self._basis
        linespec = self.linespec
        vmax_list = self.vmax
        for i in range(self.n_agents):
            b_i = basis[i]
            if b_i is None:
                continue
            e1x, e1y, e1z, e2x, e2y, e2z, fx, fy, fz = b_i
            prx, pry, prz = pref_list[i]
            pref2x = prx * e1x + pry * e1y + prz * e1z
            pref2y = prx * e2x + pry * e2y + prz * e2z
            fwd_comp = prx * fx + pry * fy + prz * fz
            specs = linespec[i]
            spd_lim = vmax_list[i]
            if specs:
                vix, viy, viz = v_list[i]
                lines: list[tuple[float, float, float, float]] = []
                for (
                    rhs, j, nx, ny, nz, resp, n2x, n2y, inv_plen, dx, dy, fwd_n3
                ) in specs:
                    vjx, vjy, vjz = v_list[j]
                    b = (1.0 - resp) * (vix * nx + viy * ny + viz * nz) + resp * (
                        (vjx * nx + vjy * ny + vjz * nz) + rhs
                    )
                    bound = (b - fwd_comp * fwd_n3) * inv_plen
                    lines.append((dx, dy, n2x * bound, n2y * bound))
                rx, ry, ok = _lp2_scalar(lines, pref2x, pref2y, spd_lim)
                if not ok:
                    rx, ry = _lp3_scalar(lines, pref2x, pref2y, spd_lim)
            else:
                rx, ry = pref2x, pref2y
                sp = math.hypot(rx, ry)
                if sp > spd_lim > 0.0:
                    s = spd_lim / sp
                    rx *= s
                    ry *= s
            out_rows[i] = [
                rx * e1x + ry * e2x + fx * fwd_comp,
                rx * e1y + ry * e2y + fy * fwd_comp,
                rx * e1z + ry * e2z + fz * fwd_comp,
            ]
        return np.asarray(out_rows, dtype=np.float64)


def orca_from_pairs(
    P, V, pref, mass, live, vmax, dt, cam_pos, pair_i, pair_j, gaps, normals,
    gap_min=GAP_MIN_DEFAULT, tau=ORCA_TAU,
):
    """Velocity half-planes from capsule-pair gaps in the same metric as overlap tests.

    (v_i - v_j) · n >= (gap_min - g) / tau, split by mass. Default gap_min is 0
    (no extra floor). Avoidance may exceed amax so units can brake in time;
    heading is still turn-clamped by the caller.
    """
    return OrcaPairSolver(
        P, mass, live, vmax, cam_pos, pair_i, pair_j, gaps, normals, gap_min, tau
    ).solve(V, pref)
