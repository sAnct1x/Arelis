"""Overseer scene, Pass A: idle nodes draw nothing; stars follow the hive."""

from __future__ import annotations

from arelis.ui import overseer_runtime as o


def test_idle_hive_nodes_draw_no_beacon_or_stream() -> None:
    idle = [
        {"node_id": "port-8443", "kind": "bastion", "position": [12.0, 1.0, -7.0]},
        {"node_id": "crystal-1", "kind": "memory", "position": [-4.0, 2.0, 9.0]},
    ]
    # The fixed source beacons (Web, arXiv, ...) still draw; the nodes do not.
    base = o.build_conduits([], [], active_sources=set())
    assert o.build_conduits([], idle, active_sources=set()) == base
    hot = [{"node_id": "port-22", "kind": "bastion", "severity": "high", "position": [3.0, 0.0, 3.0]}]
    assert len(o.build_conduits([], hot, active_sources=set())) > len(base)


def test_star_drift_follows_open_requests_not_throughput() -> None:
    swarm = o.layout_swarm(12)
    idle = o.build_frame(swarm, 96.0, 1306.0, nodes=[])
    assert idle["hiveActivity"] == 0
    # One open request: the hive's harvest_target node for that fetch.
    fetch = {
        "node_id": "fetch-1",
        "kind": "harvest_target",
        "position": [30.0, 2.0, 0.0],
        "metadata": {"unit_id": swarm[0]["unit_id"]},
    }
    assert 0 < o.build_frame(swarm, 96.0, 1306.0, nodes=[fetch])["hiveActivity"] < 1
