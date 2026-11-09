"""Overseer edge source nodes light a beam only on a real harvest fetch."""

from __future__ import annotations

from arelis.ui import overseer_runtime as o


def test_source_nodes_beam_only_when_harvest_fetch_is_live() -> None:
    assert o.normalize_harvest_source("arxiv") == "arxiv"
    assert o.normalize_harvest_source("wikipedia", "Star") == "wikipedia"
    assert o.normalize_harvest_source("horizons", "Mars") == "horizons"
    assert o.normalize_harvest_source("url", "https://example.com/a") == "web"
    assert o.normalize_harvest_source("synthetic") == ""

    idle = o.build_frame(
        [{"unit_id": "SNT-WRD-001", "caste": "warden", "state": "PATROLLING", "position": [4, 0.5, 0]}],
        76.0,
        nodes=[],
    )
    assert idle["activeSources"] == []
    beacons = [c for c in idle["conduits"] if str(c.get("id", "")).startswith("source-beacon:")]
    beams = [c for c in idle["conduits"] if str(c.get("id", "")).startswith("source-beam:")]
    assert {c["source_id"] for c in beacons} == {"arxiv", "wikipedia", "horizons", "web"}
    assert beams == []
    assert len(idle["sourceLabels"]) == 4
    assert all(not row["hot"] for row in idle["sourceLabels"])

    # Live harvest_target node (hive removes it when the fetch ends).
    live_nodes = [
        {
            "node_id": "node-hrv-0007",
            "kind": "harvest_target",
            "label": "ARXIV: fusion",
            "status": "extracting",
            "position": [22.0, 2.0, 4.0],
            "metadata": {"action": "arxiv", "target": "fusion", "unit_id": "SNT-HRV-001"},
        }
    ]
    busy = o.build_frame(
        [
            {
                "unit_id": "SNT-HRV-001",
                "caste": "harvester",
                "state": "ENGAGED_HARVEST",
                "position": [10, 0.5, 2],
                "current_task": "Extracting arxiv: fusion",
            }
        ],
        76.0,
        nodes=live_nodes,
    )
    assert busy["activeSources"] == ["arxiv"]
    beams = [c for c in busy["conduits"] if str(c.get("id", "")).startswith("source-beam:")]
    assert beams and all(c["source_id"] == "arxiv" for c in beams)
    hot = next(row for row in busy["sourceLabels"] if row["id"] == "arxiv")
    cold = next(row for row in busy["sourceLabels"] if row["id"] == "wikipedia")
    assert hot["hot"] is True
    assert cold["hot"] is False

    # Unit task alone (no node yet) still lights the matching source.
    from_task = o.active_harvest_sources(
        units=[{
            "unit_id": "SNT-HRV-002",
            "caste": "harvester",
            "state": "ENGAGED_HARVEST",
            "current_task": "Extracting wikipedia: nebula",
        }],
        nodes=[],
    )
    assert from_task == {"wikipedia"}
