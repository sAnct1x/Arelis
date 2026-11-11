"""Pass F free-flow sim: caste steering, ORCA velocity avoidance, 0.25 s smoothing.

Iris SPEC.md section 3, with section 3.2 in place of the reference sim's hard
position projection. Scene space is +Y up, metres. Bearing theta maps to
(R cos theta, y, -R sin theta).
"""
from __future__ import annotations

import math, os
import numpy as np

from arelis.ui.overseer_orca import (
    ORCA_TAU,
    PROJ_MAX_MOVE,
    PROJ_MAX_PASSES,
    Smoother,
    orca_from_pairs,
    orca_step,
)

DT = 1.0 / 30.0
ORB = np.array([0.0, 1.6, 0.0]); ORB_KEEP = 10.0           # core keep-out: no unit capsule inside 10 m of the orb centre (v1: 9)
BAR_C = np.array([0.0, 0.5, 0.0]); BAR_A = 32.0; BAR_H = 11.0  # barrier: oblate spheroid semi-axes 32 / 11 / 32 (v1: 28 / 10 / 28)
PERIM = 39.0; SRC_R = 41.0; FIELD_MAX = 50.0                  # FIELD_MAX is the far-side limit; field_max(theta) is the real bound (frame fit)
def field_max(theta):
    """Outer limit of the field by bearing, so every unit stays in the overview frame (camera pulled back 12 %):
    44 m on the sides, 50 m on the far side (top of the frame), 40 m on the near side (above the dispatch bar)."""
    s_ = math.sin(theta); return 44.0 + 6.0 * max(0.0, s_) ** 2 - 4.0 * max(0.0, -s_) ** 2
GATE_R_AP = 1.7                                              # gateway aperture radius (frame 1.28 x)
LANE_OFF = 0.85                                              # two lanes per gate, side by side: out lane +t, in lane -t
PASS_START = 2.5                                             # the pass state (right of way) starts 2.5 m before the gate plane
LANE_GAP = 0.4                                               # s between two passes in the same lane (v1: 0.8)
# v2.1 knobs (TYCHO-v2.1.md): end-on yaw bias, Sanitizer leash, Sanitizer mass, Sanitizer scan depth
YAW_BIAS = math.radians(float(os.environ.get('FF_YAWBIAS', '27')))     # v2.1: cone half-angle off screen-vertical
YAW_JIT = math.radians(float(os.environ.get('FF_YAWJIT', '5')))        # v2.1: per-unit spread of the cone angle (+-)
SAN_LEASH = float(os.environ.get('FF_SANLEASH', '1.5'))                 # radial spring (m/s^2 per m) beyond SAN_RHOME, after the separation share
SAN_RHOME = float(os.environ.get('FF_SANRHOME', '16.0')); SAN_RMAX = float(os.environ.get('FF_SANRMAX', '19'))   # leash start, hard clamp radius
SAN_MASS = float(os.environ.get('FF_SANMASS', '2'))                     # spacing mass of a patrolling Sanitizer (v2.1: 2)
SAN_SCAN = float(os.environ.get('FF_SANSCAN', '15.0'))                  # scan spot depth inside the gate (m); v2.1: 15
PICKET_OFF = float(os.environ.get('FF_PICKOFF', '5.0')); PICKET_OUT = float(os.environ.get('FF_PICKOUT', '4.0'))
# Tripwire picket station: 4 m outside the shell, 5 m beside the gate axis = 2 m clear of the gate frame edge (frame radius 1.28 x 1.7 = 2.2 m,
# + 2 m, + 0.8 m head radius). A literal 2 m off the axis put the picket inside the lane corridor (+-2.5 m) and on the work slots.
G = 9.81
SCALE_K = 1.0   # overview scale rule factor (set by Sim from the inside-barrier count)
KMIN = float(os.environ.get("FF_KMIN", "0.64"))  # overview scale floor (v1: 0.6; the camera is 12 % further back)
HEAD_L = 2.0                                     # head length at scale 1 (sentinel_geo.HEAD_L)
HEAD_MIN_PX = float(os.environ.get("FF_HEADPX", "24"))   # minimum head length on screen at the overview (px at 1306 px tall)
HEAD_MAX_MUL = 1.4                               # the head floor never makes a head more than 1.4 x its body scale
COLLAR_X = -0.93                                 # tentacle roots (sentinel_geo.COLLAR_X); tentacles shift back by COLLAR_X x (sh - s)
# silhouette capsule per unit (head + trailing tentacles + comet spread), in units of scale s:
# spine samples at +0.6 s (head, r 1.4 s), -1.6 s (r 1.5 s), -4.4 s (r 2.7 s) along the facing direction
# -> covers nose +2.0 s .. tail -7.1 s: full sentinel length L = 9.1 s, comet spread up to 5.4 s, mean width 3.7 s
CAP_X = np.array([0.6, -1.6, -4.4]); CAP_R = 1.4      # legacy names kept for capgap.py (head-centred view)
CAP_RS = np.array([1.4, 1.5, 2.7])                   # per-sample radius (x scale): head+claws, mid tentacles, comet-spread tips
CAP_T = np.array([0.6, 1.6, 4.4])                    # sample offsets (x scale): head ahead on the facing dir, tentacles behind
# CAP_T / CAP_RS were fitted to the rendered Pass E silhouettes (src/fit_spine.py): 3.0% of silhouette pixels fall outside
# tentacle speed per state (same table as scene_f / Pass E runtime tentacle_speed)
TENT_SPEED = dict(PATROLLING=0.55, DOCKED=0.55, VECTORING=2.2, ENGAGED_DEFENSE=2.5, ENGAGED_HARVEST=1.8, RETURNING=1.8, ENGAGED_SANITIZE=1.1)
GAP_MIN = float(os.environ.get("FF_GAP", "1.5")); GAP_SOFT = GAP_MIN + 1.6; K_CAP = 16.0      # clear capsule gap (m, camera-plane metric): hard floor, soft start, gain
GAP_CAP = 1.0                                     # gap used by the density cap footprint (the floor above has 0.5 m of tip margin)
CAM_D = 95.1893 * 1.12                        # overview camera distance, pulled back 12 % (v1 95.1893); target, pitch, fov unchanged
CAM_POS = np.array([0.0, 49.8247, 87.8283])   # = qtcam.Cam((0, -6, -3), CAM_D, 31.6864).pos (v1: 0, 43.8436, 78.0966)
CAM_FWD = np.array([0.0, -0.5252696836807533, -0.8509358139166088]); CAM_FPX = 653.0 / math.tan(math.radians(17.5))
CAM_UP = np.array([0.0, 0.8509358139166088, -0.5252696836807533])

def screen_axis(P):
    """Plan direction that projects to screen-vertical at the overview camera."""
    n = np.cross(np.atleast_2d(P) - CAM_POS, CAM_UP)
    ax = np.stack([-n[:, 2], n[:, 0]], 1)
    return ax / (np.linalg.norm(ax, axis=1, keepdims=True) + 1e-9)

def head_scale(P, s):
    """Head scale with the overview pixel floor: head length >= HEAD_MIN_PX, capped at HEAD_MAX_MUL x s."""
    depth = np.maximum((np.atleast_2d(P) - CAM_POS) @ CAM_FWD, 1.0)
    return np.minimum(np.maximum(s, HEAD_MIN_PX * depth / (HEAD_L * CAM_FPX)), HEAD_MAX_MUL * s)
def plane(DX, X):
    """Remove the component of each pair vector along that pair's view ray (camera -> pair midpoint)."""
    M = 0.5 * (X[:, None, :, None, :] + X[None, :, None, :, :]) - CAM_POS
    f = M / (np.linalg.norm(M, axis=-1, keepdims=True) + 1e-9)
    return DX - np.sum(DX * f, -1, keepdims=True) * f

def bearing_pt(theta, r, y):
    return np.array([r * math.cos(theta), y, -r * math.sin(theta)])

# ---- castes: role, zone and motion signature (SPEC.md section 3 table) ----
CASTES = {
    #            role        vmin vmax amax turn  sepR  nbr  kAli kCoh wander ylo  yhi  bankMax scale
    'sanitizer': dict(role='defender', vmin=1.2, vmax=3.2, amax=3.0, turn=1.6, sepR=3.2, nbr=9.0, kAli=0.35, kCoh=0.30,
                      wander=0.9, ylo=0.0, yhi=2.5, bank=20, scale=0.72, rlo=12.0, rhi=19.0),
    'warden':    dict(role='defender', vmin=2.5, vmax=5.5, amax=4.5, turn=1.2, sepR=4.2, nbr=12.0, kAli=1.0, kCoh=0.45,
                      wander=0.6, ylo=-0.5, yhi=2.5, bank=28, scale=0.90, rlo=21.0, rhi=28.8),
    'tripwire':  dict(role='hunter', vmin=0.0, vmax=2.6, amax=2.0, turn=0.9, sepR=6.0, nbr=0.0, kAli=0.0, kCoh=0.0,
                      wander=0.0, ylo=0.5, yhi=2.0, bank=10, scale=0.95, rlo=36.0, rhi=40.0),
    'stalker':   dict(role='hunter', vmin=4.0, vmax=9.0, amax=8.0, turn=0.9, sepR=9.0, nbr=0.0, kAli=0.0, kCoh=0.0,
                      wander=0.5, ylo=1.0, yhi=4.0, bank=40, scale=1.00, rlo=37.0, rhi=44.0, sprint=15.0, turnChase=2.2),
    'harvester': dict(role='gatherer', vmin=1.0, vmax=6.5, amax=5.0, turn=1.4, sepR=3.6, nbr=8.0, kAli=0.6, kCoh=0.0,
                      wander=0.35, ylo=-0.5, yhi=2.5, bank=24, scale=0.90, rlo=13.0, rhi=28.0, carry=4.6),
}
CASTE_IDS = list(CASTES)
SOURCES = [('arxiv', 'arXiv', math.radians(8.0), '#8fd3ff'), ('wikipedia', 'Wikipedia', math.radians(128.0), '#a78bfa'),
           ('horizons', 'Horizons', math.radians(62.0), '#7ee0c8'), ('web', 'Web', math.radians(160.0), '#e879f9')]
# watched ports (warden.py:31-36 _DEFAULT_WATCHED_PORTS) -> port gateways in the near half
PORTS = [(8765, 'LAN ingest', 'lan'), (8766, 'Core IPC', 'loopback'), (11434, 'Ollama', 'loopback'), (8790, 'Command bridge', 'loopback')]
PORT_BEARINGS = [math.radians(a) for a in (348.0, 292.0, 248.0, 205.0)]
MAX_GATES = 8

def h(x):   # GLSL hash, same as the tentacle seeds
    v = math.sin(x) * 43758.5453; return v - math.floor(v)

def flow(p, t, ph):
    """Wander flow field (sum of sines, divergence-light): same maths in the app step."""
    x, y, z = p[..., 0], p[..., 1], p[..., 2]
    return np.stack([np.sin(0.21 * z + 0.37 * t + ph) + 0.5 * np.sin(0.13 * y - 0.23 * t + 2.1 * ph),
                     0.35 * np.sin(0.17 * x + 0.29 * t + 1.3 * ph),
                     np.sin(0.19 * x - 0.31 * t + 0.7 * ph) + 0.5 * np.sin(0.11 * y + 0.41 * t + ph)], -1)

def footprint(k):
    """m^2 one unit needs: (L 9.1 s + gap) x (mean silhouette width 3.7 s + gap) at mean inside scale 0.86 x k"""
    s = 0.86 * k; return (9.1 * s + GAP_CAP) * (3.7 * s + GAP_CAP)
A_INSIDE = math.pi * ((BAR_A - 2.0) ** 2 - ORB_KEEP ** 2)        # usable annulus, 2 m off the wall
PACK_LOW = 0.65
PACK_HIGH = 0.55  # SPEC 7.2: above 100 units
DENSITY_SWITCH = 100

def pack_for(n_units):
    env = os.environ.get("FF_PACK")
    if env:
        return float(env)
    return PACK_HIGH if int(n_units) > DENSITY_SWITCH else PACK_LOW

def inside_cap(k, n_units=0):
    return int(pack_for(n_units) * A_INSIDE / footprint(k))

def field_edge_points(n=16):
    pts = []
    for i in range(n):
        th = 2.0 * math.pi * i / n
        r = field_max(th)
        pts.append({
            "x": r * math.cos(th),
            "y": 0.02,
            "z": -r * math.sin(th),
        })
    return pts

def cap_pairs(X, RAD, P, live, reach):
    """Candidate pairs i<j whose head centres are within the capsule reach (broad phase), then the 3x3 sample
    distances in the camera-plane metric (narrow phase). Returns I, J, min clear gap, unit push vector (i away from j)."""
    DP = P[:, None, :] - P[None, :, :]; MP = 0.5 * (P[:, None, :] + P[None, :, :]) - CAM_POS
    fP = MP / (np.linalg.norm(MP, axis=-1, keepdims=True) + 1e-9); D = np.linalg.norm(DP - np.sum(DP * fP, -1, keepdims=True) * fP, axis=2)
    ext = np.max(np.linalg.norm(X - P[:, None, :], axis=2) + RAD, axis=1)          # per-unit reach of its samples
    lim = ext[:, None] + ext[None, :] + reach
    I, J = np.nonzero(np.triu(D < lim, 1) & live[:, None] & live[None, :])
    if len(I) == 0: return I, J, np.zeros(0), np.zeros((0, 3))
    DX = X[I][:, :, None, :] - X[J][:, None, :, :]                                       # (M,3,3,3)
    M_ = 0.5 * (X[I][:, :, None, :] + X[J][:, None, :, :]) - CAM_POS; f = M_ / (np.linalg.norm(M_, axis=-1, keepdims=True) + 1e-9)
    DX = DX - np.sum(DX * f, -1, keepdims=True) * f
    RX = np.linalg.norm(DX, axis=-1).reshape(len(I), 9) + 1e-6
    rr = (RAD[I][:, :, None] + RAD[J][:, None, :]).reshape(len(I), 9)
    gap = RX - rr; a = gap.argmin(1); g = gap[np.arange(len(I)), a]
    v = DX.reshape(len(I), 9, 3)[np.arange(len(I)), a] / RX[np.arange(len(I)), a][:, None]
    keep = g < reach
    return I[keep], J[keep], g[keep], v[keep]

class Gate:
    def __init__(self, gid, kind, theta, label, color, sub=''):
        self.id, self.kind, self.theta, self.label, self.color, self.sub = gid, kind, theta, label, color, sub
        self.c = bearing_pt(theta, BAR_A, BAR_C[1]); self.n = np.array([math.cos(theta), 0, -math.sin(theta)])
        self.t = np.cross(np.array([0, 1.0, 0]), self.n)
        self.want = 'closed'; self.open = 0.0; self.state = 'closed'; self.traffic_in = 0.0; self.traffic_out = 0.0
        self.lane_free = {+1: 0.0, -1: 0.0}; self.queue = {+1: [], -1: []}; self.threat = False; self.blocked = False
    def pt(self, along, lane):   # along > 0 outside, < 0 inside
        return self.c + self.n * along + self.t * (LANE_OFF * lane)
    def step(self, dt, now):
        target = 0.0 if (self.blocked or self.want == 'closed') else 1.0
        rate = dt / 0.6 if target > self.open else dt / 0.8     # open 0.6 s, close 0.8 s
        self.open = min(target, self.open + rate) if target > self.open else max(target, self.open - rate)
        self.traffic_in *= math.exp(-dt / 0.8); self.traffic_out *= math.exp(-dt / 0.8)
        self.state = ('threat' if self.threat else 'blocked' if self.blocked else
                      'in' if self.traffic_in > 0.2 else 'out' if self.traffic_out > 0.2 else 'open' if self.open > 0.5 else 'closed')

class Sim:
    def __init__(self, fixture, seed=7):
        rng = np.random.default_rng(seed); self.t = 0.0
        self.caste = []; P = []
        for c, n in fixture:
            for i in range(n):
                self.caste.append(c); C = CASTES[c]
                r = rng.uniform(C['rlo'], C['rhi']); th = rng.uniform(0, 2 * math.pi)
                P.append(bearing_pt(th, r, rng.uniform(C['ylo'], C['yhi'])))
        self.N = len(self.caste); self.p = np.array(P); self.ci = np.array([CASTE_IDS.index(c) for c in self.caste])
        self.v = np.zeros((self.N, 3)); self.bank = np.zeros(self.N); self.omega = np.zeros(self.N)
        tang = np.cross(np.array([0, 1.0, 0]), self.p - ORB); tang /= np.linalg.norm(tang, axis=1, keepdims=True) + 1e-9
        for i in range(self.N): self.v[i] = tang[i] * CASTES[self.caste[i]]['vmin'] * (1 if i % 2 else -1) + 0.3
        fn = np.linalg.norm(self.v, axis=1, keepdims=True) + 1e-9
        self.face = self.v / fn
        self.face[:, 1] = np.clip(self.face[:, 1], -0.14, 0.14)
        self.face /= np.linalg.norm(self.face, axis=1, keepdims=True) + 1e-9
        self.state = ['PATROLLING'] * self.N; self.sub = [''] * self.N; self.timer = np.zeros(self.N)
        self.gate = [None] * self.N; self.goal = [None] * self.N; self.carry = np.zeros(self.N, bool)
        self.pack = np.full(self.N, -1); self.slot = np.zeros(self.N, int); self.job = [None] * self.N
        self.wp = [0] * self.N; self.eye_threat = np.zeros(self.N, bool); self.anim = [dict() for _ in range(self.N)]; self.qhead = set()
        self.phase = np.array([h(i * 1.7 + 0.3) * 6.2832 for i in range(self.N)])
        self.gates = {}
        for (port, name, bind), th in zip(PORTS, PORT_BEARINGS):
            g = Gate('port-%d' % port, 'port', th, ':%d %s' % (port, name), '#a78bfa', bind); g.want = 'open'; self.gates[g.id] = g
        for sid, label, th, col in SOURCES:
            self.gates['src-' + sid] = Gate('src-' + sid, 'source', th, label, col)
        self.threats = []; self.handoffs = []; self.events = []; self.qstart = {}
        # packs: wardens in packs of 6 (gate-to-gate loops), sanitizers one loose cloud, stalkers solo, tripwires on gates
        idx = {c: [i for i in range(self.N) if self.caste[i] == c] for c in CASTES}
        for k, i in enumerate(idx['warden']): self.pack[i] = k // 6; self.slot[i] = k % 6
        for k, i in enumerate(idx['sanitizer']): self.pack[i] = 100; self.slot[i] = k
        for k, i in enumerate(idx['stalker']): self.slot[i] = k
        for k, i in enumerate(idx['tripwire']): self.slot[i] = k
        for k, i in enumerate(idx['harvester']): self.slot[i] = k
        self.idx = idx
        # overview scale rule and inside-barrier cap (SPEC 2.4): k = clamp(sqrt(30 / n_inside), 0.7, 1)
        global SCALE_K
        n_in = sum(1 for c in self.caste if CASTES[c]['role'] in ('defender', 'gatherer'))
        SCALE_K = float(np.clip(math.sqrt(30.0 / max(n_in, 1)), KMIN, 1.0))
        self.scale_k = SCALE_K
        self.cap_inside = inside_cap(SCALE_K, self.N)
        self.docked = np.zeros(self.N, bool)
        self.smoother = Smoother(self.N)
        self.prev_state = ['PATROLLING'] * self.N
        self.proj_steps = 0
        self.proj_active_steps = 0
        self.proj_move_sum = 0.0
        self.proj_move_max = 0.0
        self.egress_muted = False
        self.emp = False
        inside = [i for i in range(self.N) if CASTES[self.caste[i]]['role'] in ('defender', 'gatherer')]
        # keep the cap awake; dock the rest, harvesters first (they wake for jobs), then sanitizers, then wardens
        order = sorted(inside, key=lambda i: (['harvester', 'sanitizer', 'warden'].index(self.caste[i]), -self.slot[i]))
        for i in order[:max(0, len(inside) - self.cap_inside)]:
            self.docked[i] = True; self.state[i] = 'DOCKED'; self.p[i] = ORB + np.array([0, -4.0, 0])
        self.n_wpacks = max(1, (len(idx['warden']) + 5) // 6)
        for i in idx['tripwire']: self.p[i] = self.picket_station(i)[1]      # pickets start on station
        self._legalize_start()

    # ---------- events (what the hive reports) ----------
    def wake(self):
        awake_in = sum(1 for i in range(self.N) if not self.docked[i] and CASTES[self.caste[i]]['role'] in ('defender', 'gatherer') and self.side(i))
        if awake_in < self.cap_inside:
            d = [i for i in range(self.N) if self.docked[i]]
            if d:
                i = d[0]; self.docked[i] = False; self.state[i] = 'PATROLLING'
                self.p[i] = ORB + np.array([0, -2.5, 0]) + bearing_pt(h(i * 0.7) * 6.28, ORB_KEEP + 1.0, 0); self.v[i] = np.array([0.5, 0.0, 0.5])
    def dispatch(self, i, source):
        g = self.gates['src-' + source]
        self.job[i] = source; self.gate[i] = g.id; self.state[i] = 'VECTORING'; self.sub[i] = 'to_gate'; self.timer[i] = 0; self.qstart[i] = self.t
        self.events.append((round(self.t, 2), i, 'VECTORING', source))
    def spawn_threat(self, gate_id, bearing_off=0.0, r0=55.0):
        g = self.gates[gate_id]; th = g.theta + bearing_off
        self.threats.append(dict(gate=gate_id, p=bearing_pt(th, r0, 2.5), v=np.zeros(3), alive=True, t0=self.t, hp=1.0))
        g.threat = True

    # ---------- per-unit goals (state machine) ----------
    def gate_req(self, i, g, lane):
        """Queue at the gate's lane; returns the point to steer at and whether the pass is granted.
        v2: the queue is ordered by distance to the lane's pass spot (2.5 m before the gate plane, on the lane line),
        so the nearest waiting unit goes next; the queue head flies THROUGH the spot when the lane is free (no stop),
        and the pass is granted within 2.5 m of the spot."""
        q = g.queue[lane]
        if i not in q: q.append(i)
        side = -1 if lane > 0 else 1        # out lane queues inside, in lane outside
        spot = g.pt(side * PASS_START, lane)
        if i == q[0] or len(q) > 1:
            q.sort(key=lambda j: float(np.linalg.norm(self.p[j] - spot)))
        k = q.index(i)
        if k == 0: self.qhead.add(i)
        else: self.qhead.discard(i)
        free = g.open > 0.85 and self.t >= g.lane_free[lane] and not g.blocked
        rel = self.p[i] - g.c; al = side * (rel @ g.n); lat = rel @ g.t - lane * LANE_OFF   # al > 0 = still on the queue side
        on_lane = abs(lat) < 1.6 and -1.0 < al < PASS_START + 3.5
        if k == 0:
            # line up on the lane first (a point 4.5 m before the gate, on the lane line), then fly through without braking
            hold = (g.pt(-side * 6.0, lane) if on_lane else g.pt(side * (PASS_START + 2.0), lane)) if free else spot
        elif k == 1:        # next in line waits ON the lane line, one sentinel length (+gap) behind the pass spot
            hold = g.pt(side * (PASS_START + 9.1 * CASTES['harvester']['scale'] * SCALE_K + GAP_MIN), lane)
        else:               # later places fan out along the barrier wall either side of the lane, 5 m back from the gate
            hold = g.pt(side * 5.0, lane) + g.t * (lane * 2.0)
            sp = 1.15 * 9.1 * CASTES['harvester']['scale'] * SCALE_K            # 1.15 full sentinel lengths apart
            phi = (1 if k % 2 else -1) * (k // 2 + 1) * sp / max(np.linalg.norm(hold[[0, 2]]), 1.0)
            cph, sph = math.cos(phi), math.sin(phi); x, z = hold[0], hold[2]
            hold = np.array([cph * x - sph * z, hold[1], sph * x + cph * z])
        granted = k == 0 and free and on_lane and al < PASS_START + 0.5   # the pass starts 2.5 m (+0.5) before the gate plane
        return hold, granted

    def picket_station(self, i):
        """Tripwire i's still-picket station: gate (ports first, then sources) by slot, 2 m off the gate axis on the
        out-lane side (second row: the other side), PICKET_OUT m outside the shell, 1.2 m up."""
        gl = [g for g in self.gates.values() if g.kind == 'port'] + [self.gates['src-' + s_[0]] for s_ in SOURCES]
        g = gl[self.slot[i] % len(gl)]; row = self.slot[i] // len(gl); sideP = 1 if row % 2 == 0 else -1
        st_pt = g.c + g.n * (PICKET_OUT + 3.0 * (row // 2)) + g.t * (PICKET_OFF * sideP); st_pt[1] = 1.2
        return g, st_pt

    def unit_goal(self, i):
        c = self.caste[i]; C = CASTES[c]; st = self.state[i]; sub = self.sub[i]; p = self.p[i]; t = self.t
        A = self.anim[i]; A.clear()
        if self.docked[i]: return p, 0.0
        if c == 'harvester':
            if st == 'PATROLLING':   # staging cloud inside the barrier, biased to the source-gate half
                th = self.slot[i] * 2.39996 + 0.04 * t * (1 if self.slot[i] % 2 else -1)   # golden-angle spread all round, slow drift
                r = 13.5 + 10.0 * h(self.slot[i] * 3.1); A['wIdle'] = 0.35
                return bearing_pt(th, r, 0.5 + 1.5 * math.sin(0.09 * t + self.phase[i])), C['vmax'] * 0.35
            g = self.gates[self.gate[i]]; src = bearing_pt(g.theta, SRC_R, 3.0)
            if sub == 'to_gate':
                g.want = 'open'; hold, ok = self.gate_req(i, g, +1)
                if ok:
                    g.queue[+1].remove(i); self.qhead.discard(i); g.lane_free[+1] = t + LANE_GAP; self.sub[i] = 'pass_out'; g.traffic_out = 1.0
                    self.events.append((round(t, 2), i, 'PASS_OUT', g.id, round(t - self.qstart.pop(i, t), 2)))
                return hold, C['vmax'] * 0.8
            if sub == 'pass_out':
                g.traffic_out = 1.0
                if (p - g.c) @ g.n > 4.0: self.sub[i] = 'travel'
                return g.pt(10.0, +1), C["vmax"] * 0.6        # aim past the exit point so arrive() does not brake inside the gate
            if sub == 'travel':
                stand = self.work_pt(i, g, src)
                if np.linalg.norm(p - stand) < 2.0: self.sub[i] = 'work'; self.state[i] = 'ENGAGED_HARVEST'; self.timer[i] = 0
                bow = -g.t * 1.5 * math.sin(math.pi * np.clip(((p - g.c) @ g.n) / (SRC_R - BAR_A), 0, 1))   # bow away from the picket side (+t)
                return stand + bow, C['vmax']
            if sub == 'work':        # reach 0-1.2 s, grab 1.2-2.2 s, coil 2.2-3.4 s (Pass E timeline), then carry
                w = self.timer[i]; A.update(face=src, wIdle=0.6, wReach=min(1, w / 0.6) * (1 - np.clip((w - 1.2) / 0.4, 0, 1)),
                                            wHold=np.clip((w - 1.2) / 0.4, 0, 1), wCoil=np.clip((w - 2.2) / 1.2, 0, 1),
                                            clawOpenArm=0.75 if w < 1.2 else 0.05, clawOpen=0.6)
                if w > 3.4: self.sub[i] = 'carry'; self.state[i] = 'RETURNING'; self.carry[i] = True; self.qstart[i] = t
                return self.work_pt(i, g, src), 0.6
            if sub == 'carry':
                A.update(wCoil=1.0, clawOpenArm=0.05); hold, ok = self.gate_req(i, g, -1)
                if ok:
                    g.queue[-1].remove(i); self.qhead.discard(i); g.lane_free[-1] = t + LANE_GAP; self.sub[i] = 'pass_in'; g.traffic_in = 1.0
                    self.events.append((round(t, 2), i, 'PASS_IN', g.id, round(t - self.qstart.pop(i, t), 2)))
                return hold, C['carry']
            if sub == 'pass_in':
                A.update(wCoil=1.0, clawOpenArm=0.05); g.traffic_in = 1.0
                if (p - g.c) @ g.n < -4.0: self.sub[i] = 'to_core'
                return g.pt(-10.0, -1), C["carry"] * 0.6
            if sub == 'to_core':
                A.update(wCoil=1.0, clawOpenArm=0.05)
                dock = ORB + (bearing_pt(g.theta + 0.5 * (self.slot[i] % 3 - 1), 1, 0) * (ORB_KEEP + 1.0))
                if np.linalg.norm(p - dock) < 2.5: self.sub[i] = 'handoff'; self.timer[i] = 0
                return dock, C['carry']
            if sub == 'handoff':     # release: coil unwinds 1.2 s, bead flies to the core 0.8 s
                w = self.timer[i]; A.update(face=ORB, wCoil=float(np.clip(1 - w / 1.2, 0, 1)), wIdle=0.5)
                if w > 0.6 and self.carry[i]: self.carry[i] = False; self.handoffs.append((t, i, p.copy()))
                if w > 1.8:
                    self.state[i] = 'PATROLLING'; self.sub[i] = ''; self.job[i] = None; self.gate[i] = None
                    self.events.append((round(t, 2), i, 'PATROLLING', 'handoff'))
                return ORB + bearing_pt(g.theta + 0.5 * (self.slot[i] % 3 - 1), 1, 0) * (ORB_KEEP + 1.0), 0.4
        if c == 'sanitizer':
            if st == 'ENGAGED_SANITIZE':   # meet a returning gatherer just inside its gate, scan, back
                g = self.gates[self.gate[i]]; A.update(face=g.c, wIdle=0.4)
                if self.timer[i] > 6.0: self.state[i] = 'PATROLLING'; self.gate[i] = None
                return g.pt(-SAN_SCAN, -1) - g.t * 5.0, C['vmax']     # v2: always on the in-lane side, 11 m in, clear of the out-lane approach
            th = 0.06 * t * (1 if self.slot[i] % 2 else -1) + self.slot[i] * 2.39996
            r = 15.5 + 2.8 * math.sin(3 * th + 0.11 * t + self.phase[i])
            return bearing_pt(th, r, 1.0 + 1.2 * math.sin(0.13 * t + self.phase[i])), C['vmax'] * 0.6
        if c == 'warden':
            pk = self.pack[i]; dirn = 1 if pk % 2 == 0 else -1
            if st == 'ENGAGED_DEFENSE':   # wall on the inner side of the attacked gate
                g = self.gates[self.gate[i]]; A.update(face=g.c, clawOpen=0.85)
                s = self.slot[i] - 2.5
                return g.pt(-6.5 - 3.0 * (self.slot[i] % 2), 0) + g.t * s * 3.4, C['vmax']
            ports = sorted([g for g in self.gates.values() if g.kind == 'port'], key=lambda g: g.theta)
            # gate-to-gate loop: waypoints alternate gate-inner (r 16) and a pulled-in midpoint (r 11.5)
            wps = []
            for g in ports: wps += [g.theta, None]
            k = len(wps); wi = self.wp[i] % k
            def wpt(j):
                j %= k; th = wps[j] if wps[j] is not None else (wps[j - 1] + ((wps[(j + 1) % k] - wps[j - 1]) % (2 * math.pi)) / 2)
                rr = 24.5 if wps[j] is not None else 21.0 + 1.5 * math.sin(0.07 * t + pk)
                return bearing_pt(th, rr, 0.5 + 1.5 * math.sin(0.1 * t + pk * 1.3))
            anchor_i = [x for x in range(self.N) if self.pack[x] == pk and self.caste[x] == 'warden']
            lead = anchor_i[0]
            if i == lead:
                tgt = wpt(wi if dirn > 0 else -wi)
                if np.linalg.norm(p - tgt) < 3.5: self.wp[i] += 1
                return tgt, C['vmax'] * 0.75
            # followers: loose slot behind the leader (offset jitters slowly: 'shifting' flock)
            L = self.p[lead]; fv = self.v[lead] / (np.linalg.norm(self.v[lead]) + 1e-6); side = np.cross(np.array([0, 1.0, 0]), fv)
            s = self.slot[i]; j = 0.6 * math.sin(0.23 * t + self.phase[i])
            return L - fv * (7.6 * (s // 2 + 1) + j) + side * ((s % 2) * 2 - 1) * (3.0 + j) + np.array([0, 0.8 * math.sin(0.31 * t + s), 0]), C['vmax']
        if c == 'tripwire':
            g, st_pt = self.picket_station(i)
            if st == 'VECTORING' and self.threats:
                T = self.threats[0]; A.update(face=T['p'], clawOpen=0.7)
                return T['p'] + (self.p[i] - T['p']) / (np.linalg.norm(self.p[i] - T['p']) + 1e-6) * 10.0, C['vmax'] * 2.2
            # still picket: a fixed station 2 m off the gate axis (out-lane side, beyond the pass exit), body holds,
            # only the head scans: a +-0.30 rad (17 deg) pendulum round the outward normal, 6 s period
            sc_ = 0.30 * math.sin(2 * math.pi * t / 6.0 + self.phase[i]); fd = g.n * math.cos(sc_) + g.t * math.sin(sc_)
            if YAW_BIAS > 0:      # v2.1: pendulum centre is the cone + 0.30 rad off the screen-vertical axis
                vr = screen_axis(p)[0]; nn = g.n[[0, 2]] / (np.linalg.norm(g.n[[0, 2]]) + 1e-9)
                ph = math.atan2(abs(vr[0] * nn[1] - vr[1] * nn[0]), abs(vr @ nn)); need = YAW_BIAS + 0.30
                if ph < need:
                    cands = [g.n * math.cos(o) + g.t * math.sin(o) for o in (need - ph, ph - need)]
                    ang = lambda c: math.atan2(abs(vr[0] * c[2] - vr[1] * c[0]), abs(vr[0] * c[0] + vr[1] * c[2]))
                    c0 = max(cands, key=ang); t0_ = np.cross(np.array([0, 1.0, 0]), c0)
                    fd = c0 * math.cos(sc_) - t0_ * math.sin(sc_)
            A.update(wIdle=0.15, face=(p + fd * 10.0).tolist(), picket=1)
            return st_pt, (1.2 if np.linalg.norm(p - st_pt) < 4.0 else C['vmax'])
        if c == 'stalker':
            if st == 'ENGAGED_DEFENSE' and self.threats and self.threats[0]['alive']:
                T = self.threats[0]; n = len(self.idx['stalker']); k = self.slot[i]
                d = np.linalg.norm(T['p'] - p); lead = T['p'] + T['v'] * min(1.5, d / max(np.linalg.norm(self.v[i]), 1))
                ang = 2 * math.pi * k / n + 1.9 * t                          # pincer ring round the threat, 1.9 rad/s
                ring = np.array([math.cos(ang), 0.35 * math.sin(2 * ang), math.sin(ang)]) * (7.0 if d < 12 else 0)
                A.update(face=T['p'], clawOpen=0.85, wStrike=float(np.clip(1 - d / 9.0, 0, 1)) * (0.5 + 0.5 * math.sin(6 * t + k)))
                return lead + ring, C['sprint']
            # sector sweep: lawnmower zig-zag between r 26 and r 46 across the stalker's own 360/n wedge
            n = len(self.idx['stalker']); k = self.slot[i]; w0 = 2 * math.pi * k / n; ww = 2 * math.pi / n
            leg = self.wp[i]; th = w0 + ww * (0.15 + 0.7 * ((leg // 2) % 5) / 4.0); r = 39.0 if leg % 2 == 0 else field_max(th) - 1.5
            tgt = bearing_pt(th, r, 2.5 + 2.0 * math.sin(0.2 * t + k))
            if np.linalg.norm(p[[0, 2]] - tgt[[0, 2]]) < 4.0: self.wp[i] += 1
            return tgt, C['vmax']
        return p, 0.0

    # ---------- the step ----------
    def step(self):
        t = self.t; N = self.N
        for g in self.gates.values():
            if g.kind == 'source':
                busy = any(self.gate[i] == g.id for i in range(N) if self.caste[i] == 'harvester')
                g.want = 'open' if busy else 'closed'
        goals = np.zeros((N, 3)); vdes = np.zeros(N)
        for i in range(N):
            gp, vd = self.unit_goal(i); goals[i] = gp; vdes[i] = vd
        if YAW_BIAS > 0:
            ax2 = screen_axis(self.p)
            for i in range(N):
                A = self.anim[i]
                if 'face' not in A or A.get('picket') or A.get('wReach', 0) > 0 or self.caste[i] == 'stalker':
                    continue
                f = np.asarray(A['face'], float) - self.p[i]; fh = f[[0, 2]]; L = np.linalg.norm(fh) + 1e-9; u = fh / L
                c_ = float(u @ ax2[i]); s_ = ax2[i, 0] * u[1] - ax2[i, 1] * u[0]
                ph = math.atan2(abs(s_), abs(c_))
                if ph >= YAW_BIAS:
                    continue
                axs = ax2[i] * (1 if c_ >= 0 else -1); sd = 1.0 if s_ * (1 if c_ >= 0 else -1) >= 0 else -1.0
                nx = axs[0] * math.cos(YAW_BIAS) - axs[1] * math.sin(YAW_BIAS) * sd
                nz = axs[0] * math.sin(YAW_BIAS) * sd + axs[1] * math.cos(YAW_BIAS)
                A['face'] = [float(self.p[i, 0] + nx * L), float(A['face'][1]), float(self.p[i, 2] + nz * L)]
        self.timer += DT
        par = [CASTES[c] for c in self.caste]
        vmax = np.array([C['vmax'] for C in par]); amax = np.array([C['amax'] for C in par])
        turn = np.array([C['turn'] for C in par]); vmin = np.array([C['vmin'] for C in par])
        for i in range(N):
            if self.caste[i] == 'stalker' and self.state[i] == 'ENGAGED_DEFENSE':
                vmax[i] = CASTES['stalker']['sprint']; turn[i] = CASTES['stalker']['turnChase']; amax[i] = 12.0
            if self.caste[i] == 'tripwire' and self.state[i] == 'VECTORING': vmax[i] = 6.0; turn[i] = 1.8
            if self.sub[i] in ('pass_out', 'pass_in'): turn[i] = 2.5
            if self.carry[i]: vmax[i] = CASTES['harvester']['carry']
        # arrive: desired velocity toward goal, slowing inside 6 m
        d = goals - self.p; dist = np.linalg.norm(d, axis=1) + 1e-6
        spd = np.minimum(vdes, vdes * dist / 6.0); spd = np.maximum(spd, np.where(dist > 1.0, vmin, 0.0))
        desired = d / dist[:, None] * spd[:, None]
        # route round the core: if the straight line to the goal cuts the keep-out cylinder, steer for the tangent
        a = self.p[:, [0, 2]] - ORB[[0, 2]]; b = goals[:, [0, 2]] - ORB[[0, 2]]; ab = b - a
        tt = np.clip(-np.sum(a * ab, 1) / (np.sum(ab * ab, 1) + 1e-9), 0, 1)
        closest = np.linalg.norm(a + ab * tt[:, None], axis=1); ra = np.linalg.norm(a, axis=1) + 1e-9
        cut = (closest < ORB_KEEP + 2.5) & (tt > 0) & (tt < 1) & np.array([x not in ('to_core', 'handoff') for x in self.sub])
        if cut.any():
            sgn0 = np.sign(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0] + 1e-9)
            # v2: hysteresis. Keep the side a unit chose while its route still cuts the core (v1 flipped the side near the
            # antipode and parked units behind the core for 10 to 20 s, the main cause of the slow gatherer queue)
            if not hasattr(self, 'route_sgn'): self.route_sgn = np.zeros(N)
            self.route_sgn[~cut] = 0.0; new = cut & (self.route_sgn == 0); self.route_sgn[new] = sgn0[new]
            sgn = np.where(self.route_sgn != 0, self.route_sgn, sgn0)
            tang = np.stack([-a[:, 1], a[:, 0]], 1) * (sgn / ra)[:, None]
            outw = a / ra[:, None] * np.clip(ORB_KEEP + 3.0 - ra, 0, None)[:, None] * 0.5
            dd = tang + outw; dd /= np.linalg.norm(dd, axis=1, keepdims=True) + 1e-9
            desired[cut][:, :] = 0
            desired[cut, 0] = dd[cut, 0] * spd[cut]; desired[cut, 2] = dd[cut, 1] * spd[cut]
        if YAW_BIAS > 0:      # v2.1: bend free headings off the screen-vertical axis so tails never hang straight down
            if not hasattr(self, 'yaw_side'): self.yaw_side = np.zeros(N)
            vr = screen_axis(self.p)
            dz = desired[:, [0, 2]]; sp_ = np.linalg.norm(dz, axis=1) + 1e-9; u = dz / sp_[:, None]
            c_ = np.sum(u * vr, 1); s_ = vr[:, 0] * u[:, 1] - vr[:, 1] * u[:, 0]
            phi = np.arctan2(np.abs(s_), np.abs(c_))
            elig = np.array([(self.sub[i] in ('', 'travel', 'to_gate', 'carry', 'to_core') and not self.anim[i].get('picket') and 'face' not in self.anim[i]
                              and not (self.caste[i] == 'stalker' and self.state[i] == 'ENGAGED_DEFENSE') and i not in self.qhead) for i in range(N)])
            hit = elig & (phi < YAW_BIAS) & (sp_ > 0.3)
            self.yaw_side[~hit] = 0.0; nw = hit & (self.yaw_side == 0); self.yaw_side[nw] = np.where(s_[nw] * np.sign(c_[nw] + 1e-9) >= 0, 1.0, -1.0)
            if hit.any():
                ax_ = vr * np.sign(c_ + 1e-9)[:, None]; sd = self.yaw_side; ca_, sa_ = math.cos(YAW_BIAS), math.sin(YAW_BIAS)
                nx = ax_[:, 0] * ca_ - ax_[:, 1] * sa_ * sd; nz = ax_[:, 0] * sa_ * sd + ax_[:, 1] * ca_
                desired[hit, 0] = nx[hit] * sp_[hit]; desired[hit, 2] = nz[hit] * sp_[hit]
        F = (desired - self.v) * 1.6
        # Soft capsule separation is a preferred-velocity bias (Iris step 4).
        # ORCA then enforces the hard velocity constraint; positions are not snapped.
        sc = np.array([C['scale'] for C in par]) * SCALE_K
        Xsep, Rsep = self.spine(sc)
        I, J, gmin, vec = cap_pairs(Xsep, Rsep, self.p, ~self.docked, GAP_SOFT)
        w = np.clip((GAP_SOFT - gmin) / (GAP_SOFT - GAP_MIN), 0, None) ** 2
        ms = self.mass()
        fi = np.where(ms[I] > ms[J], 0.0, np.where(ms[I] < ms[J], 2.0, 1.0)); fj = 2.0 - fi
        Fsep = np.zeros((N, 3))
        if len(I):
            np.add.at(Fsep, I, K_CAP * vec * (w * fi)[:, None]); np.add.at(Fsep, J, -K_CAP * vec * (w * fj)[:, None])
        D = self.p[:, None, :] - self.p[None, :, :]; R = np.linalg.norm(D, axis=2) + np.eye(N) * 1e9
        nbr = np.array([C['nbr'] for C in par]); same = (self.pack[:, None] == self.pack[None, :]) & (self.pack[:, None] >= 0)
        pat = np.array([x == 'PATROLLING' for x in self.state]); same &= pat[:, None] & pat[None, :]
        W = same & (R < nbr[:, None]); cnt = W.sum(1)
        has = cnt > 0
        if has.any():
            ali = (W @ self.v) / np.maximum(cnt, 1)[:, None] - self.v
            coh = (W @ self.p) / np.maximum(cnt, 1)[:, None] - self.p
            kA = np.array([C['kAli'] for C in par]); kC = np.array([C['kCoh'] for C in par])
            F += has[:, None] * (ali * kA[:, None] + coh * kC[:, None] * 0.25)
        # wander (flow field)
        wan = np.array([C['wander'] for C in par]); F += flow(self.p, t, self.phase) * wan[:, None]
        # orb keep-out (quadratic within 2 m of 6.5 m) and barrier sides (only units not passing a gate)
        do = self.p - ORB; ro = np.linalg.norm(do, axis=1) + 1e-6
        F += (do / ro[:, None]) * (np.clip(ORB_KEEP + 2.0 - ro, 0, None) ** 2 * 3.0)[:, None]
        q = self.p - BAR_C; fb = np.sqrt((q[:, 0] ** 2 + q[:, 2] ** 2) / BAR_A ** 2 + q[:, 1] ** 2 / BAR_H ** 2)
        nb = q / np.array([BAR_A ** 2, BAR_H ** 2, BAR_A ** 2]); nb /= np.linalg.norm(nb, axis=1, keepdims=True) + 1e-9
        passing = np.array([self.sub[i] in ('pass_out', 'pass_in') or (self.sub[i] in ('to_gate', 'carry') and (i in self.qhead or 0.9 < fb[i] < 1.1)) for i in range(N)])   # v2: the queue head is exempt (its spot is 2.5 m from the shell)
        inside = np.array([self.side(i) for i in range(N)])
        pin = np.where(inside, -np.clip(fb - 0.86, 0, None), np.clip(1.14 - fb, 0, None)) * 60.0
        F += (~passing)[:, None] * nb * pin[:, None]
        # altitude band
        ylo = np.array([C['ylo'] for C in par]); yhi = np.array([C['yhi'] for C in par])
        F[:, 1] += (np.clip(ylo - self.p[:, 1], 0, None) - np.clip(self.p[:, 1] - yhi, 0, None)) * 1.5
        # accel clamp, then ORCA on the preferred velocity
        fm = np.linalg.norm(F, axis=1) + 1e-9; F *= (np.minimum(fm, amax) / fm)[:, None]
        sm = np.linalg.norm(Fsep, axis=1) + 1e-9; Fsep *= (np.minimum(sm, 2.5 * amax) / sm)[:, None]
        keep = np.where(ms > 1.0, 0.4, 0.8)
        pk_ = np.array([bool(self.anim[i].get('picket')) for i in range(N)])
        if pk_.any():
            F[pk_] = (desired[pk_] - self.v[pk_]) * 2.5
        F = F * (1.0 - np.minimum(np.clip(sm / (2.5 * amax), 0, 1), keep))[:, None] + Fsep
        if SAN_LEASH > 0:
            for i in self.idx['sanitizer']:
                if self.state[i] != 'PATROLLING' or self.docked[i]: continue
                rr = math.hypot(self.p[i, 0], self.p[i, 2])
                if rr > SAN_RHOME: F[i, [0, 2]] -= self.p[i, [0, 2]] / rr * min(SAN_LEASH * (rr - SAN_RHOME), 2.0 * CASTES['sanitizer']['amax'])
        v_pref = self.v + F * DT
        Xsp, Rsp = self.spine(sc)
        radii = np.max(Rsp, axis=1)
        v0 = self.v.copy()
        live = ~self.docked
        reach = GAP_MIN + float(np.max(vmax)) * ORCA_TAU
        Ip, Jp, gp, vp = cap_pairs(Xsp, Rsp, self.p, live, reach)
        if len(Ip):
            v1 = orca_from_pairs(self.p, self.v, v_pref, self.mass(), live, vmax, DT, CAM_POS, Ip, Jp, gp, vp, GAP_MIN, ORCA_TAU)
            v1 = orca_from_pairs(self.p, v1, v1, self.mass(), live, vmax, DT, CAM_POS, Ip, Jp, gp, vp, GAP_MIN, ORCA_TAU)
        else:
            v1 = orca_step(self.p, self.v, v_pref, radii, self.mass(), live, amax, vmax, DT, CAM_POS, GAP_MIN)
        # Turn limit applies to preferred velocity only (already in F / caste steering).
        # Clamping the ORCA heading and keeping the ORCA speed on the old heading
        # drives units through each other. Presentation smoothing is 0.25 s.
        s1 = np.linalg.norm(v1, axis=1) + 1e-9
        s1c = np.clip(s1, 0.0, vmax); v1 *= (s1c / s1)[:, None]
        if YAW_BIAS > 0:
            # Heading cone on the integrated velocity. Separation is added back
            # so the cone never cancels avoidance (Iris v2.1).
            ax2 = screen_axis(self.p); hz = v1[:, [0, 2]]; hs = np.linalg.norm(hz, axis=1) + 1e-9; u = hz / hs[:, None]
            c_ = np.sum(u * ax2, 1); s_ = ax2[:, 0] * u[:, 1] - ax2[:, 1] * u[:, 0]
            phi = np.arctan2(np.abs(s_), np.abs(c_))
            yb = YAW_BIAS + YAW_JIT * (2.0 * np.array([h(7.31 * i + 0.5) for i in range(N)]) - 1.0)
            hit = elig & (phi < yb) & (hs > 0.3)
            if not hasattr(self, 'cone_side'): self.cone_side = np.zeros(N)
            self.cone_side[~hit] = 0.0; nw = hit & (self.cone_side == 0)
            self.cone_side[nw] = np.where(s_[nw] * np.sign(c_[nw] + 1e-9) >= 0, 1.0, -1.0)
            if hit.any():
                axs = ax2 * np.sign(c_ + 1e-9)[:, None]; sd = self.cone_side
                ca_, sa_ = np.cos(yb), np.sin(yb)
                nx = axs[:, 0] * ca_ - axs[:, 1] * sa_ * sd; nz = axs[:, 0] * sa_ * sd + axs[:, 1] * ca_
                v1[hit, 0] = nx[hit] * hs[hit]; v1[hit, 2] = nz[hit] * hs[hit]
            # Re-solve ORCA after the cone so heading correction cannot undo avoidance.
            # (Adding Fsep back, as the snap-based design sim does, would reopen gaps.)
            if len(Ip):
                v1 = orca_from_pairs(self.p, v1, v1, self.mass(), live, vmax, DT, CAM_POS, Ip, Jp, gp, vp, GAP_MIN, ORCA_TAU)
        # banking from the turn rate (coordinated turn), smoothed 0.25 s
        hz0 = v0[:, [0, 2]]; hz1 = v1[:, [0, 2]]
        yaw0 = np.arctan2(hz0[:, 1], hz0[:, 0]); yaw1 = np.arctan2(hz1[:, 1], hz1[:, 0])
        om = ((yaw1 - yaw0 + np.pi) % (2 * np.pi) - np.pi) / DT
        self.omega += (om - self.omega) * (DT / 0.25)
        bmax = np.radians([C['bank'] for C in par])
        self.bank = np.clip(np.arctan(np.linalg.norm(v1, axis=1) * self.omega / G), -bmax, bmax)
        v1[self.docked] = 0.0
        self.v = v1
        s1 = np.linalg.norm(v1, axis=1)
        moving = s1 > 0.3
        dest = self.face.copy()
        dest[moving] = v1[moving] / s1[moving, None]
        dest[:, 1] = np.clip(dest[:, 1], -0.14 * np.linalg.norm(dest[:, [0, 2]], axis=1), 0.14 * np.linalg.norm(dest[:, [0, 2]], axis=1))
        dest /= np.linalg.norm(dest, axis=1, keepdims=True) + 1e-9
        cs = np.clip(np.sum(self.face * dest, 1), -1, 1)
        ang = np.arccos(cs)
        lim = turn * DT
        over = ang > lim
        if over.any():
            axis = np.cross(self.face[over], dest[over])
            al = np.linalg.norm(axis, axis=1, keepdims=True) + 1e-9
            axis = axis / al
            # If nearly colinear and opposite, pick a world-up rotation axis
            flip = al[:, 0] < 1e-6
            if np.any(flip):
                axis[flip] = np.array([0.0, 1.0, 0.0])
            ca = np.cos(lim[over])[:, None]; sa = np.sin(lim[over])[:, None]
            f0 = self.face[over]
            dest[over] = f0 * ca + np.cross(axis, f0) * sa + axis * np.sum(axis * f0, 1, keepdims=True) * (1 - ca)
            dest[over] /= np.linalg.norm(dest[over], axis=1, keepdims=True) + 1e-9
        dest[self.docked] = self.face[self.docked]
        self.face = dest
        self.p = self.p + v1 * DT
        self.project_zones()
        self.safety_project(sc)
        for g in self.gates.values(): g.step(DT, t)
        if int(t / DT) % 15 == 0: self.wake()
        self.step_threats()
        yaw = np.arctan2(self.v[:, 2], self.v[:, 0])
        snap = np.array([(self.state[i] == 'DOCKED') != (self.prev_state[i] == 'DOCKED') for i in range(N)], dtype=bool)
        if not self.smoother.ready:
            self.smoother.snap(self.p, yaw)
        elif snap.any():
            self.smoother.snap(self.p, yaw, snap)
        self.prev_state = list(self.state)
        self.t += DT

    def work_pt(self, i, g, src):
        """v2: 6 work slots on the source's INNER 200 deg arc (facing the barrier), 40 deg apart, radius 2.45 s + 3.2 m,
        so no slot sits beyond the field edge (v1 put 3 of 6 slots on the far side, 2 of them outside field_max at arXiv)."""
        j = self.slot[i] % 6; a = math.radians(-100.0 + 40.0 * j); s = CASTES['harvester']['scale'] * SCALE_K
        d = -g.n * math.cos(a) + g.t * math.sin(a)          # tails point away from the source
        return src + d * (2.45 * s + 3.2) + np.array([0, 0.6 * s, 0])

    def spine(self, sc):
        """(N,3,3) capsule samples matching the rendered silhouette: head ahead on the facing direction,
        tentacle samples on the tail direction, which trails straight behind (fit to the renders)."""
        f = self.face.copy() if hasattr(self, 'face') else self.v.copy()
        for i in range(self.N):
            A = self.anim[i]
            if 'face' in A: f[i] = np.asarray(A['face']) - self.p[i]; f[i, 1] *= 0.3
        f[:, 1] = np.clip(f[:, 1], -0.14 * np.linalg.norm(f[:, [0, 2]], axis=1), 0.14 * np.linalg.norm(f[:, [0, 2]], axis=1))   # level: pitch <= 8 deg
        f /= np.linalg.norm(f, axis=1, keepdims=True) + 1e-6
        tail = -f                                       # tails trail level behind the head, even when slow
        sh = head_scale(self.p, sc); dl = -COLLAR_X * (sh - sc)        # bigger head: tentacles sit further back
        X = np.empty((self.N, 3, 3))
        X[:, 0] = self.p + f * (CAP_T[0] * sh[:, None]); X[:, 1] = self.p + tail * (CAP_T[1] * sc + dl)[:, None]; X[:, 2] = self.p + tail * (CAP_T[2] * sc + dl)[:, None]
        RAD = np.stack([CAP_RS[0] * sh, CAP_RS[1] * sc, CAP_RS[2] * sc], 1)
        return X, RAD

    def mass(self):
        """Spacing mass: 6 while passing a gate (everyone yields), 5 carrying a result home, 4 holding a job spot (work, handoff, queue head), 3 travelling on a job
        (gate approach, outbound travel, carry, return to core, hunters engaged), 1 for free patrol."""
        pk = [bool(a.get('picket')) for a in self.anim]
        sm_ = [SAN_MASS if (c == 'sanitizer' and self.state[i] == 'PATROLLING') else 1.0 for i, c in enumerate(self.caste)]
        return np.array([4.0 if pk[i] else 6.0 if x in ('pass_out', 'pass_in') else 5.0 if (x in ('carry', 'to_core') and self.carry[i]) else 4.0 if (x in ('work', 'handoff') or i in self.qhead) else 3.0 if (x in ('to_gate', 'travel', 'carry', 'to_core') or st in ('ENGAGED_DEFENSE', 'VECTORING', 'ENGAGED_SANITIZE'))
                         else sm_[i] for i, (x, st) in enumerate(zip(self.sub, self.state))])

    def _legalize_start(self):
        """One-time seed so units do not start overlapping. Not used as the step mechanism."""
        par = [CASTES[c] for c in self.caste]
        sc = np.array([C['scale'] for C in par]) * self.scale_k
        live = ~self.docked
        # Batch inner projection steps, then snap zones once per round. Zoning
        # after every single pass pinned wardens to the 0.90 shell and left
        # ~11 % still touching after 80 tries; 8-iter batches reach 0 %.
        for _ in range(24):
            done = False
            for _it in range(8):
                X, RAD = self.spine(sc)
                I, J, g, vec = cap_pairs(X, RAD, self.p, live, GAP_MIN)
                if len(I) == 0 or float(g.min()) >= 0.0:
                    done = True
                    break
                d = (GAP_MIN - g)[:, None] * vec
                # Equal responsibility at init only: mass-weighted projection left
                # mass-2 Sanitizers stuck and shoved Harvesters into residual overlaps.
                wi = np.full(len(I), 0.5)
                np.add.at(self.p, I, d * wi[:, None])
                np.add.at(self.p, J, -d * (1.0 - wi)[:, None])
            self.project_zones(hard=False, clamp_san=False, legalize=True)
            if done and self.overlap_stats(use_present=False)["touching"] == 0.0:
                break
        # Cold start: from rest, preferred velocities briefly pack the field.
        # Settle with the real velocity-avoidance step (not a position snap)
        # so the first displayed frame is already in the held-gap regime.
        for _ in range(90):
            self.step()
        yaw = np.arctan2(self.face[:, 2], self.face[:, 0])
        self.smoother.snap(self.p, yaw)
        self.proj_steps = 0
        self.proj_active_steps = 0
        self.proj_move_sum = 0.0
        self.proj_move_max = 0.0

    def project_spacing(self, sc, iters=None):
        """Safety-net projection only (SPEC 3.2): at most 2 passes, 0.05 m per step."""
        return self.safety_project(sc)

    def safety_project(self, sc):
        live = ~self.docked
        m = self.mass()
        p0 = self.p.copy()
        for _ in range(PROJ_MAX_PASSES):
            X, RAD = self.spine(sc)
            I, J, g, vec = cap_pairs(X, RAD, self.p, live, GAP_MIN)
            if len(I) == 0:
                break
            d = (GAP_MIN - g)[:, None] * vec
            mi, mj = m[I], m[J]
            wi = np.where(mi > mj, 0.0, np.where(mi < mj, 1.0, 0.5))
            np.add.at(self.p, I, d * wi[:, None])
            np.add.at(self.p, J, -d * (1.0 - wi)[:, None])
            self.project_zones()
        dp = self.p - p0
        nd = np.linalg.norm(dp, axis=1)
        over = nd > PROJ_MAX_MOVE
        if over.any():
            dp[over] *= (PROJ_MAX_MOVE / (nd[over] + 1e-9))[:, None]
            self.p = p0 + dp
            nd = np.linalg.norm(self.p - p0, axis=1)
        moved = float(nd.max()) if self.N else 0.0
        self.proj_steps += 1
        if moved > 1e-6:
            self.proj_active_steps += 1
            self.proj_move_sum += moved
            self.proj_move_max = max(self.proj_move_max, moved)
        return moved

    def project_zones(self, hard=False, clamp_san=True, legalize=False):
        """Zone constraints. Legalize (hard=True) snaps inside units to 0.90 of
        the shell and outside units to 1.10. The running loop only retracts a
        unit that has actually crossed the membrane (0.98 / 1.02) and cancels
        the crossing velocity. A hard snap to 0.90 every step packed wardens
        onto a shared 28.8 m surface (their outer patrol edge) and undid
        velocity-level avoidance."""
        q = self.p - BAR_C; fb = np.sqrt((q[:, 0] ** 2 + q[:, 2] ** 2) / BAR_A ** 2 + q[:, 1] ** 2 / BAR_H ** 2) + 1e-9
        nb = q / np.array([BAR_A ** 2, BAR_H ** 2, BAR_A ** 2])
        nb /= np.linalg.norm(nb, axis=1, keepdims=True) + 1e-9
        # Legalize may use the design shells. The running loop only retracts a
        # unit that has gone through the membrane, and cancels the crossing
        # velocity. A hard snap to 0.90 packed wardens onto a shared 28.8 m
        # surface (their outer patrol edge) and undid velocity avoidance.
        if hard:
            in_lim, out_lim = 0.90, 1.10
        elif legalize:
            in_lim, out_lim = 0.99, 1.02
        else:
            in_lim, out_lim = 1.05, 0.95
        cap = None if (hard or legalize) else PROJ_MAX_MOVE

        def _nudge(i, dest):
            dest = np.asarray(dest, dtype=float)
            if cap is None:
                self.p[i] = dest
                return
            d = dest - self.p[i]
            L = float(np.linalg.norm(d))
            if L > cap:
                self.p[i] = self.p[i] + d * (cap / L)
            else:
                self.p[i] = dest

        for i in range(self.N):
            if self.docked[i] or self.sub[i] in ('pass_out', 'pass_in'): continue
            if self.sub[i] in ('to_gate', 'carry') and 0.85 < fb[i] < 1.15: continue
            vn = float(np.dot(self.v[i], nb[i]))
            if self.side(i):
                if fb[i] > in_lim:
                    tgt = 0.90 if hard else (0.99 if legalize else 1.0)
                    _nudge(i, BAR_C + q[i] * (tgt / fb[i]))
                    q[i] = self.p[i] - BAR_C
                    fb[i] = math.sqrt((q[i, 0] ** 2 + q[i, 2] ** 2) / BAR_A ** 2 + q[i, 1] ** 2 / BAR_H ** 2) + 1e-9
                # Only brake at the membrane (0.97), not at 0.90 (warden patrol edge).
                if (not hard) and fb[i] > 0.97 and vn > 0.0:
                    self.v[i] = self.v[i] - nb[i] * vn
            else:
                if fb[i] < out_lim:
                    tgt = 1.10 if hard else (1.02 if legalize else 1.0)
                    _nudge(i, BAR_C + q[i] * (tgt / fb[i]))
                    q[i] = self.p[i] - BAR_C
                if (not hard) and fb[i] < 1.03 and vn < 0.0:
                    self.v[i] = self.v[i] - nb[i] * vn
                rr = math.hypot(self.p[i, 0], self.p[i, 2]); fm_ = field_max(math.atan2(-self.p[i, 2], self.p[i, 0]))
                if rr > fm_:
                    dest = self.p[i].copy()
                    dest[[0, 2]] = dest[[0, 2]] * (fm_ / rr)
                    _nudge(i, dest)
        if clamp_san and SAN_RMAX < 90:     # v2.1: Sanitizer outer limit. Cancel outward
            # velocity at 19 m; only retract a unit that has gone past 19.5 m.
            # Snapping every patrol onto exactly 19 m packed them on a cylinder.
            for i in self.idx['sanitizer']:
                if self.state[i] != 'PATROLLING' or self.docked[i]: continue
                rr = math.hypot(self.p[i, 0], self.p[i, 2])
                if rr <= 1e-9: continue
                vr = (self.v[i, 0] * self.p[i, 0] + self.v[i, 2] * self.p[i, 2]) / rr
                if rr > SAN_RMAX and vr > 0.0:
                    self.v[i, 0] -= self.p[i, 0] / rr * vr
                    self.v[i, 2] -= self.p[i, 2] / rr * vr
                if rr > SAN_RMAX + 0.5:
                    dest = self.p[i].copy()
                    dest[[0, 2]] = dest[[0, 2]] * (SAN_RMAX / rr)
                    _nudge(i, dest)
        ylo = np.array([CASTES[c]['ylo'] for c in self.caste]) - 1.5; yhi = np.array([CASTES[c]['yhi'] for c in self.caste]) + 1.5
        free = np.array([x not in ('pass_out', 'pass_in') for x in self.sub])  # every unit except one passing a gate
        yc = np.clip(self.p[:, 1], ylo, yhi); hit = free & (yc != self.p[:, 1])
        if cap is None:
            self.p[free, 1] = yc[free]
        else:
            dy = yc - self.p[:, 1]
            step = np.clip(dy, -cap, cap)
            self.p[free, 1] = self.p[free, 1] + step[free]
        self.v[hit, 1] = 0.0
        do = self.p - ORB; do[:, 1] = 0.0; ro = np.linalg.norm(do, axis=1) + 1e-9   # core keep-out: a vertical cylinder
        keep_r = ORB_KEEP if hard else 8.0
        m = (ro < keep_r) & ~self.docked & np.array([x not in ('handoff', 'to_core') for x in self.sub])
        # Push toward keep_r (not past it to ORB_KEEP on the running loop, which
        # was a 2 m snap whenever someone crossed 8 m).
        if m.any():
            dest = self.p.copy()
            dest[m] = self.p[m] + do[m] * ((keep_r - ro[m]) / ro[m])[:, None]
            if cap is None:
                self.p[m] = dest[m]
            else:
                d = dest[m] - self.p[m]
                L = np.linalg.norm(d, axis=1, keepdims=True) + 1e-12
                self.p[m] = self.p[m] + d * np.minimum(1.0, cap / L)
        if not hard:
            inward = m | ((ro < ORB_KEEP) & ~self.docked)
            if inward.any():
                nxy = do / ro[:, None]
                vn = np.sum(self.v * (-nxy), 1)
                push = inward & (vn > 0)
                self.v[push] += nxy[push] * vn[push, None]

    def side(self, i):
        """True when unit i belongs inside the barrier now."""
        c = self.caste[i]; sub = self.sub[i]
        if c in ('sanitizer', 'warden'): return True
        if c in ('tripwire', 'stalker'): return False
        return sub in ('', 'to_gate', 'to_core', 'handoff') or self.state[i] == 'PATROLLING'

    def step_threats(self):
        for T in self.threats:
            if not T['alive']: continue
            g = self.gates[T['gate']]; tgt = g.pt(6.0, 0) + np.array([0, 2.0, 0])
            d = tgt - T['p']; dist = np.linalg.norm(d)
            jink = np.array([math.sin(1.7 * self.t), 0.3 * math.sin(2.3 * self.t), math.cos(1.3 * self.t)]) * 2.5
            T['v'] = (d / max(dist, 1e-6)) * min(3.2, dist) + jink
            hunters = [i for i in range(self.N) if self.state[i] == 'ENGAGED_DEFENSE' and self.caste[i] == 'stalker']
            if hunters:
                close = min(np.linalg.norm(self.p[i] - T['p']) for i in hunters)
                if close < 8.0: T['v'] *= 0.35; T['hp'] -= DT / 6.0         # held and struck
            T['p'] = T['p'] + T['v'] * DT
            if T['hp'] <= 0: T['alive'] = False; g.threat = False

    def eye(self, i):
        """Red only on a real threat: hunters engaged on a threat node, wardens walling a threat gate."""
        if self.state[i] == 'ENGAGED_DEFENSE' and self.threats and self.threats[0]['alive']: return 'threat'
        if self.caste[i] == 'harvester' and self.state[i] != 'PATROLLING': return 'fetch'
        return 'caste'

    def set_blocked(self, *, emp=False, egress_muted=False):
        self.emp = bool(emp)
        self.egress_muted = bool(egress_muted)
        for g in self.gates.values():
            g.blocked = bool(self.emp or self.egress_muted)

    def present(self, dt=DT):
        yaw = np.arctan2(self.face[:, 2], self.face[:, 0])
        return self.smoother.step(self.p, yaw, dt)

    def overlap_stats(self, use_present=True):
        par = [CASTES[c] for c in self.caste]
        sc = np.array([C['scale'] for C in par]) * SCALE_K
        saved = None
        if use_present and self.smoother.ready:
            saved = self.p.copy()
            self.p = self.smoother.x
        X, RAD = self.spine(sc)
        live = ~self.docked
        I, J, g, _ = cap_pairs(X, RAD, self.p, live, GAP_MIN + 8.0)
        if saved is not None:
            self.p = saved
        n_live = int(live.sum())
        pairs = n_live * (n_live - 1) // 2
        if pairs <= 0 or len(I) == 0:
            return {"touching": 0.0, "real": 0.0, "touching_pairs": 0.0, "real_pairs": 0.0,
                    "pairs": float(pairs), "n_live": float(n_live), "min_gap": 99.0}
        units_touch = len(set(I[g < 0.0].tolist() + J[g < 0.0].tolist()))
        units_real = len(set(I[g < -0.05].tolist() + J[g < -0.05].tolist()))
        return {
            "touching": units_touch / max(n_live, 1),
            "real": units_real / max(n_live, 1),
            "touching_pairs": float(np.count_nonzero(g < 0.0)) / max(pairs, 1),
            "real_pairs": float(np.count_nonzero(g < -0.05)) / max(pairs, 1),
            "pairs": float(pairs),
            "n_live": float(n_live),
            "min_gap": float(g.min()) if len(g) else 99.0,
        }


FIXTURE = [('sanitizer', 10), ('warden', 18), ('stalker', 8), ('tripwire', 8), ('harvester', 36)]   # 80 units (design hero)
def app_fixture(n):   # shot_passD.py proportions (100 = 16 / 28 / 2 / 44 / 10)
    base = [('sanitizer', 16), ('warden', 28), ('stalker', 2), ('harvester', 44), ('tripwire', 10)]
    out = [(c, max(1, round(k * n / 100))) for c, k in base]; return [(c, k) for c, k in out]

def scenario(T_END=46.0, record_from=0.0, fixture=None, threat=True):
    sim = Sim(fixture or FIXTURE)
    hv = sim.idx['harvester']
    # jobs: arXiv x8, Wikipedia x6, Web x4 dispatched in waves; Horizons idle (its gate stays shut)
    plan = [('arxiv', 6, 0.0, 2.6), ('wikipedia', 6, 1.0, 2.6), ('web', 4, 3.0, 3.0)]
    disp = []; k = 0
    for src, n, t0, dtp in plan:
        for j in range(n): disp.append((t0 + j * dtp, hv[k], src)); k += 1
    # second wave reuses whoever has handed off
    rec = dict(docked=[], t=[], p=[], v=[], bank=[], state=[], sub=[], carry=[], eye=[], gate=[], anim=[], gates=[], threats=[], handoffs=[])
    threat_t = 24.0; engaged = False; last_src = {}
    while sim.t < T_END:
        for td, i, src in list(disp):
            if sim.docked[i]:
                disp.remove((td, i, src)); aw = [j for j in hv if sim.state[j] == 'PATROLLING' and not sim.docked[j] and not any(d[1] == j for d in disp)]
                if aw: disp.append((td, aw[0], src))
                continue
            if sim.t >= td and sim.state[i] == 'PATROLLING': sim.dispatch(i, src); disp.remove((td, i, src))
        for i in hv:                          # a gatherer that handed off goes again 4 s later (same source)
            if i in last_src and sim.state[i] == 'PATROLLING' and not any(d[1] == i for d in disp):
                disp.append((sim.t + 4.0, i, last_src[i]))
        for i in hv:
            if sim.job[i]: last_src[i] = sim.job[i]
        if threat and sim.t >= threat_t and not sim.threats:
            sim.spawn_threat('port-8765', bearing_off=0.12, r0=47.0)
            sim.events.append((round(sim.t, 2), -1, 'THREAT', 'port-8765 UNDER ATTACK'))
        if sim.threats and not engaged and sim.t >= threat_t + 0.8:
            engaged = True
            for i in sim.idx['stalker']: sim.state[i] = 'ENGAGED_DEFENSE'
            g = sim.gates['port-8765']
            trips = sorted(sim.idx['tripwire'], key=lambda i: np.linalg.norm(sim.p[i] - g.c))[:2]
            for i in trips: sim.state[i] = 'VECTORING'
            pk0 = sim.pack[sorted(sim.idx['warden'], key=lambda i: np.linalg.norm(sim.p[i] - g.c))[0]]
            for i in sim.idx['warden']:
                if sim.pack[i] == pk0: sim.state[i] = 'ENGAGED_DEFENSE'; sim.gate[i] = 'port-8765'
        if sim.threats and not sim.threats[0]['alive'] and engaged:
            for i in range(sim.N):
                if sim.state[i] in ('ENGAGED_DEFENSE', 'VECTORING') and sim.caste[i] in ('stalker', 'tripwire', 'warden'):
                    sim.state[i] = 'PATROLLING'; sim.gate[i] = None if sim.caste[i] == 'warden' else sim.gate[i]
            engaged = None
        # sanitizers scan returning payloads (ENGAGED_SANITIZE 'Scanning payload from <source>')
        for i in hv:
            if sim.sub[i] == 'pass_in' and not sim.anim[i].get('_scanned'):
                g = sim.gates[sim.gate[i]]
                free = [s for s in sim.idx['sanitizer'] if sim.state[s] == 'PATROLLING']
                if free:
                    s = min(free, key=lambda s: np.linalg.norm(sim.p[s] - g.c)); sim.state[s] = 'ENGAGED_SANITIZE'; sim.gate[s] = g.id; sim.timer[s] = 0
                sim.anim[i]['_scanned'] = True
        sim.step()
        if sim.t >= record_from:
            rec['docked'].append(sim.docked.copy()); rec['t'].append(sim.t); rec['p'].append(sim.p.copy()); rec['v'].append(sim.v.copy()); rec['bank'].append(sim.bank.copy())
            rec['state'].append(list(sim.state)); rec['sub'].append(list(sim.sub)); rec['carry'].append(sim.carry.copy())
            rec['eye'].append([sim.eye(i) for i in range(sim.N)]); rec['gate'].append(list(sim.gate))
            rec['anim'].append([{k: (v.tolist() if hasattr(v, 'tolist') else v) for k, v in a.items() if not k.startswith('_')} for a in sim.anim])
            rec['gates'].append({g.id: dict(open=g.open, state=g.state, tin=g.traffic_in, tout=g.traffic_out) for g in sim.gates.values()})
            rec['threats'].append([dict(p=T['p'].copy(), alive=T['alive']) for T in sim.threats])
            rec['handoffs'].append(list(sim.handoffs))
    return sim, rec


def jitter_shares(rec, caste):
    P = np.array(rec["present_p"] if rec.get("present_p") else rec["p"])
    dk = np.array(rec["docked"])
    vmax = np.array([max(CASTES[c]["vmax"], CASTES[c].get("sprint", 0)) for c in caste])
    dP = np.diff(P, axis=0)
    sp = np.linalg.norm(dP, axis=2) / DT
    ok = ~dk[1:] & ~dk[:-1]
    tele = (sp > 1.5 * vmax[None, :]) & ok
    a, b = dP[1:], dP[:-1]
    cs = np.sum(a * b, 2) / (np.linalg.norm(a, axis=2) * np.linalg.norm(b, axis=2) + 1e-9)
    zz = (cs < 0.5) & (sp[1:] > 0.5) & ok[1:]
    denom_t = max(int(ok.sum()), 1)
    denom_z = max(int(ok[1:].sum()), 1)
    return {"teleport_share": float(tele.sum() / denom_t), "zigzag_share": float(zz.sum() / denom_z)}


def memory_mote_points(count, radius=2.444):
    n = max(0, min(int(count), 48))
    pts = []
    for k in range(n):
        y = 1.0 - 2.0 * (k + 0.5) / max(n, 1)
        r = math.sqrt(max(0.0, 1.0 - y * y))
        a = 2.399963 * k
        pts.append((r * math.cos(a) * radius, y * radius, r * math.sin(a) * radius))
    return pts


def tool_spark_pose(i, spin_deg, radius=1.352):
    ax = np.array([0.8 * math.sin(2.399963 * i), 1.0, 0.8 * math.cos(2.399963 * i)])
    ax = ax / (np.linalg.norm(ax) + 1e-9)
    tmp = np.array([1.0, 0.0, 0.0]) if abs(ax[1]) < 0.9 else np.array([0.0, 0.0, 1.0])
    b1 = np.cross(ax, tmp)
    b1 /= np.linalg.norm(b1) + 1e-9
    b2 = np.cross(ax, b1)
    ang = math.radians(spin_deg) + 2.1 * i
    pos = b1 * math.cos(ang) * radius + b2 * math.sin(ang) * radius
    return {"x": float(pos[0]), "y": float(pos[1]), "z": float(pos[2]), "axis": ax.tolist(), "angle": ang}


def build_links(sim, present=None):
    p = present if present is not None else sim.p
    used = {}
    for i in range(sim.N):
        if sim.docked[i]:
            continue
        if not sim.side(i) and (
            sim.sub[i] in ("pass_out", "travel", "work", "carry", "pass_in")
            or sim.state[i] in ("VECTORING", "ENGAGED_DEFENSE", "ENGAGED_HARVEST")
        ):
            gid = sim.gate[i]
            if not gid:
                open_ports = [g for g in sim.gates.values() if g.kind == "port" and g.open > 0.5 and not g.blocked]
                if not open_ports:
                    continue
                gid = min(open_ports, key=lambda g: float(np.linalg.norm(p[i] - g.c))).id
            used.setdefault(gid, []).append(i)
    links = []
    for gid, ids in used.items():
        g = sim.gates.get(gid)
        if g is None:
            continue
        arc = g.c + np.array([0.0, 2.5, 0.0])
        inward = bool(any(sim.sub[i] in ("carry", "pass_in", "to_core") or sim.carry[i] for i in ids))
        links.append({
            "kind": "trunk", "gate": gid,
            "sx": 0.0, "sy": float(ORB[1]), "sz": 0.0,
            "cx": float(arc[0]), "cy": float(arc[1]), "cz": float(arc[2]),
            "ex": float(g.c[0]), "ey": float(g.c[1]), "ez": float(g.c[2]),
            "radius": 0.022, "inward": inward, "color": "#c4b5fd",
        })
        for i in ids:
            links.append({
                "kind": "branch", "gate": gid, "unit": i,
                "sx": float(g.c[0]), "sy": float(g.c[1]), "sz": float(g.c[2]),
                "cx": float((g.c[0] + p[i, 0]) * 0.5),
                "cy": float((g.c[1] + p[i, 1]) * 0.5 + 0.4),
                "cz": float((g.c[2] + p[i, 2]) * 0.5),
                "ex": float(p[i, 0]), "ey": float(p[i, 1]), "ez": float(p[i, 2]),
                "radius": 0.02,
                "inward": bool(sim.sub[i] in ("carry", "pass_in", "to_core") or sim.carry[i]),
                "color": "#c4b5fd",
            })
    return links


def layout_static(n_units=0):
    n_in = max(1, n_units)
    k = float(np.clip(math.sqrt(30.0 / n_in), KMIN, 1.0))
    return {
        "bands": [],
        "perimeter": PERIM,
        "sourceRadius": SRC_R,
        "fieldEdge": field_edge_points(16),
        "scaleK": k,
        "insideCap": inside_cap(k, n_units),
        "pack": pack_for(n_units),
        "barrier": {"cx": float(BAR_C[0]), "cy": float(BAR_C[1]), "cz": float(BAR_C[2]), "a": BAR_A, "h": BAR_H},
    }



class FreeflowSession:
    """Live driver: maps hive units onto the Pass F sim and writes positions back.

    Callers that only want layout (tests that already placed a unit) can skip
    this and use layout_static(). Positions already on the unit are kept
    until sync() runs.
    """

    def __init__(self):
        self.sim = None
        self.ids = []
        self._last = None

    def _rebuild(self, units):
        counts = {}
        ids = []
        caste_list = []
        for u in units:
            c = str(u.get("caste") or "warden").lower()
            if c not in CASTES:
                c = "warden"
            counts[c] = counts.get(c, 0) + 1
            ids.append(str(u.get("unit_id") or f"u{len(ids)}"))
            caste_list.append(c)
        fixture = [(c, counts.get(c, 0)) for c in CASTES if counts.get(c, 0)]
        if not fixture:
            fixture = [("warden", 1)]
        self.sim = Sim(fixture, seed=7)
        # Reorder sim rows to match unit list order when counts allow.
        # Sim builds in fixture (CASTES) order; remap by taking each caste queue.
        queues = {c: [i for i, cc in enumerate(self.sim.caste) if cc == c] for c in CASTES}
        order = []
        for c in caste_list:
            q = queues.get(c) or queues["warden"]
            order.append(q.pop(0) if q else 0)
        if order and len(order) == self.sim.N:
            idx = np.array(order)
            # If the mapping is not identity, permute sim arrays.
            if not np.all(idx == np.arange(self.sim.N)):
                inv = np.empty(self.sim.N, dtype=int)
                inv[idx] = np.arange(self.sim.N)
                # simpler: just record index map
                self._map = idx
            else:
                self._map = np.arange(self.sim.N)
        else:
            self._map = np.arange(self.sim.N)
        self.ids = ids
        self._last = None
        self.sim.smoother.snap(self.sim.p, np.arctan2(self.sim.face[:, 2], self.sim.face[:, 0]))

    def sync(self, units, snap=None, now=None):
        units = list(units)
        ids = [str(u.get("unit_id") or f"u{i}") for i, u in enumerate(units)]
        if self.sim is None or ids != self.ids or self.sim.N != len(units):
            self._rebuild(units)
        snap = snap or {}
        emp = False
        if isinstance(snap, dict):
            emp = bool(snap.get("emp") or snap.get("emp_active"))
        muted = bool(snap.get("egress_muted")) if isinstance(snap, dict) and "egress_muted" in snap else False
        self.sim.set_blocked(emp=emp, egress_muted=muted)
        tnow = float(now if now is not None else (snap.get("timestamp") if isinstance(snap, dict) else 0) or 0)
        steps = 1
        if self._last is not None and tnow > self._last:
            steps = int(max(1, min(4, round((tnow - self._last) / DT))))
        elif self._last is not None:
            steps = 1
        self._last = tnow
        for _ in range(steps):
            self.sim.step()
        p, yaw = self.sim.present()
        for i, u in enumerate(units):
            j = int(self._map[i]) if i < len(self._map) else i
            u["position"] = [round(float(p[j, 0]), 4), round(float(p[j, 1]), 4), round(float(p[j, 2]), 4)]
            v = self.sim.v[j]
            u["velocity"] = [round(float(v[0]), 4), round(float(v[1]), 4), round(float(v[2]), 4)]
            u["heading"] = [round(float(math.cos(yaw[j])), 4), 0.0, round(float(math.sin(yaw[j])), 4)]
            u.pop("orbit", None)
        return units

    def frame_extras(self, snap=None):
        snap = snap or {}
        sim = self.sim
        layout = layout_static(sim.N if sim else 0)
        gates = []
        links = []
        if sim is not None:
            traffic_n = {}
            for i in range(sim.N):
                gid = sim.gate[i]
                if gid:
                    traffic_n[gid] = traffic_n.get(gid, 0) + 1
            for g in sim.gates.values():
                traffic = float(traffic_n.get(g.id, 0))
                st = "blocked" if g.blocked else ("open" if g.open > 0.5 else "closed")
                edge = g.color if st != "blocked" else "#cbd5e1"
                eg = 0.30 if st == "blocked" else (0.45 if st == "open" else 0.10)
                portal = 0.0 if st != "open" else 0.05 * (0.4 + 0.6 * min(1.0, traffic / 4.0))
                halo = 0.0 if st == "closed" else 0.015 + 0.04 * min(1.0, traffic / 4.0)
                if g.blocked:
                    halo = 0.0
                    portal = 0.0
                    eg = 0.30
                gates.append({
                    "id": g.id, "kind": g.kind, "theta": g.theta, "label": g.label,
                    "color": g.color, "edgeColor": edge, "blocked": bool(g.blocked),
                    "open": float(g.open), "state": st, "locked": bool(g.blocked),
                    "x": float(g.c[0]), "y": float(g.c[1]), "z": float(g.c[2]),
                    "nx": float(g.n[0]), "ny": float(g.n[1]), "nz": float(g.n[2]),
                    "r": GATE_R_AP, "halo": halo, "edgeGain": eg, "portal": portal,
                    "traffic": traffic, "waveK": 18.0,
                    "wavePh": (1.0 if any(sim.sub[i] in ("carry", "pass_in") and sim.gate[i] == g.id for i in range(sim.N)) else -1.0) * 6.0 * float(sim.t),
                })
            links = build_links(sim, present=sim.smoother.x if sim.smoother.ready else sim.p)
        mem = 0
        if isinstance(snap, dict):
            mem = int(snap.get("memories_in_context") or snap.get("memory_count") or 0)
        tools = []
        if isinstance(snap, dict):
            tools = list(snap.get("tools_running") or [])
        layout["gates"] = gates
        layout["links"] = links
        layout["memoryMotes"] = [{"x": x, "y": y, "z": z} for x, y, z in memory_mote_points(mem)]
        layout["toolSparks"] = [tool_spark_pose(i, 0.0) for i in range(min(8, len(tools)))]
        layout["egressMuted"] = bool(sim.egress_muted) if sim is not None else bool(snap.get("egress_muted"))
        return layout


def resolve_egress_muted(snap=None):
    if isinstance(snap, dict) and "egress_muted" in snap:
        return bool(snap.get("egress_muted"))
    try:
        from arelis.guard.watch import get_watch
        watch = get_watch()
        if hasattr(watch, "snapshot"):
            return bool(watch.snapshot().egress_muted)
        if hasattr(watch, "egress_open"):
            return not bool(watch.egress_open())
    except Exception:
        # Watch is not always started (tests, box shots, a detached snapshot).
        # Treat a missing watch as unmuted; a live hive always has the key or the Watch.
        return False
    return False


if __name__ == '__main__':
    import pickle, time, sys
    name = sys.argv[1] if len(sys.argv) > 1 else 'hero80'; T_END = float(sys.argv[2]) if len(sys.argv) > 2 else 46.0
    fx = None if name == 'hero80' else app_fixture(int(name[1:]))
    t0 = time.time(); sim, rec = scenario(T_END=T_END, fixture=fx, threat=(name == 'hero80'))
    print('sim %.1f s wall for %.1f s sim, %d steps, %.2f ms/step' % (time.time() - t0, sim.t, len(rec['t']), 1000 * (time.time() - t0) / len(rec['t'])))
    os.makedirs(os.path.join(os.path.dirname(__file__), '..', 'out'), exist_ok=True)
    pickle.dump(dict(rec=rec, caste=sim.caste, scale_k=SCALE_K, cap=sim.cap_inside, gates={g.id: dict(kind=g.kind, theta=g.theta, label=g.label, color=g.color, sub=g.sub) for g in sim.gates.values()},
                     events=sim.events), open(os.path.join(os.path.dirname(__file__), '..', 'out', 'sim_%s.pkl' % (name + (sys.argv[3] if len(sys.argv) > 3 else ''))), 'wb'))
