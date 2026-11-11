"""ORCA velocity avoidance and critically damped presentation smoothing (SPEC 3.2)."""
from __future__ import annotations

import math

import numpy as np

ORCA_TAU = 2.0
ORCA_CELL = 10.0
ORCA_NBR_DIST = 10.0
ORCA_MAX_NBR = 10
# ORCA radius is capsule radius + 0.75 m (GAP_MIN 1.5 m floor, SPEC 2.4).
PROJ_MAX_PASSES = 2
PROJ_MAX_MOVE = 0.05
SMOOTH_T = 0.25
SMOOTH_OMEGA = 2.0 / SMOOTH_T
GAP_MIN_DEFAULT = 1.5


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


def _lp1(lines, line_i, vmax, pref):
    direction, point = lines[line_i]
    t = float(np.dot(pref - point, direction))
    b = 2.0 * float(np.dot(point, direction))
    c = float(np.dot(point, point)) - vmax * vmax
    det = b * b - 4.0 * c
    if det < 0.0:
        return None
    sdet = math.sqrt(det)
    t_left = (-b - sdet) / 2.0
    t_right = (-b + sdet) / 2.0
    for j in range(line_i):
        d2, p2 = lines[j]
        n2 = np.array([-d2[1], d2[0]])
        den = float(np.dot(direction, n2))
        num = float(np.dot(p2 - point, n2))
        if abs(den) <= 1e-8:
            if num < -1e-8:
                return None
            continue
        t_hit = num / den
        if den > 0.0:
            t_right = min(t_right, t_hit)
        else:
            t_left = max(t_left, t_hit)
        if t_left > t_right + 1e-8:
            return None
    t = min(max(t, t_left), t_right)
    return point + t * direction


def _lp2(lines, pref, vmax):
    result = pref.copy()
    sp = math.sqrt(float(np.dot(result, result)))
    if sp > vmax > 0:
        result = result * (vmax / sp)
    for i, (direction, point) in enumerate(lines):
        n = np.array([-direction[1], direction[0]])
        if float(np.dot(result - point, n)) >= -1e-8:
            continue
        cand = _lp1(lines, i, vmax, pref)
        if cand is None:
            return result, False
        result = cand
    return result, True


def _lp3(lines, pref, vmax):
    """Greedy projection when the 2D linear program is infeasible."""
    result = pref.copy()
    for _ in range(4):
        for direction, point in lines:
            n = np.array([-direction[1], direction[0]])
            viol = -float(np.dot(result - point, n))
            if viol > 0.0:
                result = result + n * viol
        sp = math.sqrt(float(np.dot(result, result)))
        if sp > vmax > 0:
            result = result * (vmax / sp)
    return result


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


def orca_from_pairs(
    P, V, pref, mass, live, vmax, dt, cam_pos, pair_i, pair_j, gaps, normals,
    gap_min=GAP_MIN_DEFAULT, tau=ORCA_TAU,
):
    """Velocity half-planes from capsule-pair gaps in the same metric as overlap tests.

    (v_i - v_j) · n >= (gap_min - g) / tau, split by mass. Avoidance may exceed amax
    so units can brake in time; heading is still turn-clamped by the caller.
    """
    n_agents = len(P)
    out = pref.copy()
    cons = [[] for _ in range(n_agents)]
    for k in range(len(pair_i)):
        i = int(pair_i[k])
        j = int(pair_j[k])
        if not live[i] or not live[j]:
            continue
        if float(np.dot(P[i] - P[j], P[i] - P[j])) > ORCA_NBR_DIST * ORCA_NBR_DIST:
            continue
        n3 = np.asarray(normals[k], dtype=np.float64)
        ln = float(np.linalg.norm(n3))
        if ln < 1e-8:
            continue
        n3 = n3 / ln
        rhs_rel = (float(gap_min) - float(gaps[k])) / max(float(tau), 1e-3)
        if float(gaps[k]) < 0.0:
            # Already overlapping: both must separate. Mass-only responsibility
            # lets a heavy Sanitizer (mass 2) plow inward through Harvesters.
            ri, rj = 0.5, 0.5
        elif mass[i] < mass[j] - 1e-9:
            ri, rj = 1.0, 0.0
        elif mass[i] > mass[j] + 1e-9:
            ri, rj = 0.0, 1.0
        else:
            ri, rj = 0.5, 0.5
        cons[i].append((rhs_rel, j, n3, ri))
        cons[j].append((rhs_rel, i, -n3, rj))

    for i in range(n_agents):
        if not live[i]:
            out[i] = 0.0
            continue
        e1, e2, fwd = cam_basis(P[i], cam_pos)
        pref2 = to2(pref[i], e1, e2)
        lines = []
        fwd_comp = float(np.dot(pref[i], fwd))
        # Tightest first (largest rhs_rel); cap like SPEC ORCA_MAX_NBR.
        neigh = [c for c in cons[i] if c[3] > 0.0]
        neigh.sort(reverse=True)
        for rhs_rel, j, n3, resp in neigh[:ORCA_MAX_NBR]:
            n2 = to2(n3, e1, e2)
            plen = math.sqrt(float(np.dot(n2, n2)))
            if plen < 0.15:
                continue
            n2 = n2 / plen
            # v_i · n3 = v2 · (n3 in plane) + fwd_comp * (fwd · n3)
            # v2 · n2 >= (b - fwd_comp * (fwd · n3)) / plen
            b = (1.0 - resp) * float(np.dot(V[i], n3)) + resp * (float(np.dot(V[j], n3)) + rhs_rel)
            bound = (b - fwd_comp * float(np.dot(fwd, n3))) / plen
            point = n2 * bound
            direction = np.array([n2[1], -n2[0]])
            lines.append((direction, point))
        spd_lim = max(float(vmax[i]), 0.05)
        result, ok = _lp2(lines, pref2, spd_lim)
        if not ok:
            result = _lp3(lines, pref2, spd_lim)
        v3 = result[0] * e1 + result[1] * e2
        v3 = v3 + fwd * fwd_comp
        out[i] = v3
    return out
