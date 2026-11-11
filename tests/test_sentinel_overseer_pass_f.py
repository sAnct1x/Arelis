"""Pass F free-flow: velocity avoidance and egress mute on the snapshot."""

from __future__ import annotations

import json

import numpy as np

from arelis.ui import overseer_freeflow as ff
from arelis.ui import overseer_runtime as o


def test_velocity_avoidance_holds_gap_without_position_snapping() -> None:
    sim = ff.Sim(ff.app_fixture(100), seed=7)
    rec = []
    rec_dock = []
    worst_pairs = 0.0
    touch_1236: list[float] = []
    present_minus_raw: list[float] = []
    # Ctor already warms ~3 s. Run through t=36 so the official window is scored.
    while sim.t < 36.0 - 1e-9:
        before = sim.p.copy()
        sim.step()
        rec.append(sim.present()[0].copy())
        rec_dock.append(sim.docked.copy())
        st = sim.overlap_stats()
        st_raw = sim.overlap_stats(False)
        worst_pairs = max(worst_pairs, float(st["touching_pairs"]))
        if 12.0 <= sim.t <= 36.0:
            touch_1236.append(float(st["touching"]))
            present_minus_raw.append(float(st["touching"]) - float(st_raw["touching"]))
        moved = float(np.linalg.norm(sim.p - before, axis=1).max())
        # Integration plus the 0.05 m safety net, not a multi-metre snap.
        vmax = max(ff.CASTES[c]["vmax"] for c in sim.caste)
        assert moved <= 1.5 * vmax * ff.DT + ff.PROJ_MAX_MOVE + 1e-6
    assert sim.proj_move_max <= ff.PROJ_MAX_MOVE + 1e-9
    assert worst_pairs < 0.05
    # Per-unit touching at 100, capsule gap < 0, t 12-36 s (present).
    assert touch_1236, "expected samples in the t 12-36 window"
    med = float(np.median(touch_1236))
    worst = float(max(touch_1236))
    assert med < 0.08 and worst <= 0.15, (med, worst)
    # Without catch-up, the 0.25 s damper can show 0.10 more units touching
    # than the sim on the same frame (Linux official worst 0.15 sits on a
    # 0.07 raw frame). That leftover display overlap is the Windows (0.07,
    # 0.17) failure: the 0.15 cap had no margin. Catch-up keeps the excess
    # at 0.05 on Linux.
    assert present_minus_raw, "expected samples in the t 12-36 window"
    assert max(present_minus_raw) <= 0.07, max(present_minus_raw)
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
