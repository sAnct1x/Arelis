"""Overseer front tentacle pairs reach once per open harvest fetch (GPU-evaluated)."""

from __future__ import annotations

from pathlib import Path

from arelis.ui import overseer_runtime as o

ASSETS = Path(__file__).resolve().parents[1] / "arelis/assets/sentinel/overseer"


def _node(nid: str, unit_id: str, status: str = "extracting") -> dict:
    return {
        "node_id": nid,
        "kind": "harvest_target",
        "label": "ARXIV: fusion",
        "status": status,
        "position": [20.0, 2.0, 0.0],
        "metadata": {"action": "arxiv", "target": "fusion", "unit_id": unit_id},
    }


def test_front_pairs_reach_per_open_fetch_and_shader_eases_from_instance_data() -> None:
    units = [
        {"unit_id": "SNT-HRV-001", "caste": "harvester", "state": "ENGAGED_HARVEST",
         "position": [8, 0.5, 2], "target_node_id": "node-hrv-0001"},
        {"unit_id": "SNT-HRV-002", "caste": "harvester", "state": "VECTORING",
         "position": [6, 0.5, 1]},
        {"unit_id": "SNT-WRD-001", "caste": "warden", "state": "PATROLLING",
         "position": [4, 0.5, 0]},
    ]
    nodes = [
        _node("node-hrv-0001", "SNT-HRV-001"),
        _node("node-hrv-0002", "SNT-HRV-001", status="active"),
        # Finished or failed fetches are not open requests.
        _node("node-hrv-0003", "SNT-HRV-001", status="completed"),
        _node("node-hrv-0004", "SNT-HRV-001", status="blocked"),
    ] + [_node(f"node-hrv-01{k}", "SNT-HRV-002", status="sanitizing") for k in range(5)]
    frame = o.build_frame(units, 76.0, nodes=nodes)
    reach = {r["unit_id"]: r["reach"] for rows in frame["buckets"].values() for r in rows}
    assert reach == {"SNT-HRV-001": 2, "SNT-HRV-002": 3, "SNT-WRD-001": 0}
    idle = o.build_frame(units, 76.0, nodes=[])
    assert {r["reach"] for rows in idle["buckets"].values() for r in rows} == {0}

    # QML packs reach, previous reach and the change time; both vertex shaders
    # decode them and ease the swing on the GPU (no per-frame CPU work).
    qml = (ASSETS / "OverseerView.qml").read_text(encoding="utf-8")
    assert "claw + 2 * rs.n + 8 * rs.prev + 32 * limp, rs.t" in qml
    for name in ("hull.vert", "emissive.vert"):
        text = (ASSETS / "shaders" / name).read_text(encoding="utf-8")
        assert "float reachPairs = floor(packed / 2.0);" in text
        assert "(uTime - INSTANCE_DATA.z) / 0.4" in text
        assert "mix(curlAngle" not in text
        assert "reachW * (1.7 + 1.35 * along)" in text
        assert "uTentacles" in text
