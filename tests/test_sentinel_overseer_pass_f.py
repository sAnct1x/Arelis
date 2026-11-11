"""Pass F free-flow: velocity avoidance, contact volumes, and egress mute on the snapshot."""

from __future__ import annotations

import json

import numpy as np

from arelis.ui import overseer_freeflow as ff
from arelis.ui import overseer_runtime as o


def test_velocity_avoidance_prevents_overlap_without_position_snapping() -> None:
    kinds = ("body_body", "body_tentacle", "tentacle_tentacle")
    sim = ff.Sim(ff.app_fixture(100), seed=7)
    rec = []
    rec_dock = []
    worst_raw = {k: 0.0 for k in kinds}
    worst_present = {k: 0.0 for k in kinds}
    # Ctor already warms ~3 s. Run through t=36 so the official window is scored.
    while sim.t < 36.0 - 1e-9:
        before = sim.p.copy()
        sim.step()
        rec.append(sim.present()[0].copy())
        rec_dock.append(sim.docked.copy())
        raw = sim.penetration_by_kind(False)
        pres = sim.penetration_by_kind(True)
        for k in kinds:
            worst_raw[k] = max(worst_raw[k], raw[k])
            worst_present[k] = max(worst_present[k], pres[k])
        moved = float(np.linalg.norm(sim.p - before, axis=1).max())
        # Integration plus the 0.05 m safety net, not a multi-metre snap.
        vmax = max(ff.CASTES[c]["vmax"] for c in sim.caste)
        assert moved <= 1.5 * vmax * ff.DT + ff.PROJ_MAX_MOVE + 1e-6
    assert sim.proj_move_max <= ff.PROJ_MAX_MOVE + 1e-9
    for k in kinds:
        assert worst_raw[k] <= 1e-3, (k, "raw", worst_raw[k])
        assert worst_present[k] <= 1e-3, (k, "present", worst_present[k])
    jit = ff.jitter_shares(
        {"present_p": rec, "p": rec, "docked": rec_dock},
        sim.caste,
    )
    assert jit["teleport_share"] < 0.01
    assert jit["zigzag_share"] < 0.02
    # Safety net cannot clear a deep overlap in one step (no 14-pass snap).
    other = ff.Sim(ff.app_fixture(8), seed=3)
    other.p[1] = other.p[0] + np.array([0.2, 0.0, 0.0])
    p0 = other.p.copy()
    sc = np.array([ff.CASTES[c]["scale"] for c in other.caste]) * other.scale_k
    other.safety_project(sc)
    assert float(np.linalg.norm(other.p - p0, axis=1).max()) <= ff.PROJ_MAX_MOVE + 1e-9
    # Lagged present pose: sim volumes are clear, the damper still shows a
    # deep body overlap. present() must resolve it so nothing passes through.
    lag = ff.Sim(ff.app_fixture(8), seed=3)
    live = [i for i in range(lag.N) if not lag.docked[i]]
    assert len(live) >= 2
    i, j = int(live[0]), int(live[1])
    lag.p[j] = lag.p[i] + np.array([8.0, 0.0, 0.0])
    lag.tent_off[i] = 0.0
    lag.tent_off[j] = 0.0
    yaw = np.arctan2(lag.face[:, 2], lag.face[:, 0])
    lag.smoother.snap(lag.p, yaw)
    lag.present_tent = lag.tent_off.copy()
    lag.smoother.x[j] = lag.smoother.x[i] + np.array([0.2, 0.0, 0.0])
    lag.present()
    for k in kinds:
        assert lag.penetration_by_kind(True)[k] <= 1e-3, (k, lag.penetration_by_kind(True))


def test_egress_muted_reaches_the_overseer_snapshot() -> None:
    quiet = o.build_frame([], o.DEFAULT_CAMERA_DISTANCE, snap={"egress_muted": False})
    muted = o.build_frame([], o.DEFAULT_CAMERA_DISTANCE, snap={"egress_muted": True})
    assert quiet["egressMuted"] is False
    assert muted["egressMuted"] is True

    class _Watch:
        def snapshot(self):
            return type("S", (), {"egress_muted": True})()

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"units": [], "nodes": []}).encode()

    import arelis.ui.overseer_freeflow as flow

    def fake_watch():
        return _Watch()

    # resolve_egress_muted prefers the snapshot key, then the live Watch.
    assert flow.resolve_egress_muted({"egress_muted": False}) is False
    import arelis.guard.watch as watch

    orig = watch.get_watch
    watch.get_watch = fake_watch  # type: ignore[assignment]
    try:
        assert flow.resolve_egress_muted({}) is True
        data = o.fetch_snapshot("127.0.0.1", 9, "tok", opener=lambda *a, **k: _Resp())
    finally:
        watch.get_watch = orig  # type: ignore[assignment]
    assert data["egress_muted"] is True
