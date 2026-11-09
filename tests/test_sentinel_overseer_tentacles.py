"""Overseer tentacle animation speed maps to real unit activity (GPU INSTANCE_DATA.w)."""

from __future__ import annotations

from pathlib import Path

from arelis.ui import overseer_runtime

ASSETS = Path(__file__).resolve().parents[1] / "arelis/assets/sentinel/overseer"


def test_tentacle_speed_tracks_unit_activity_and_packs_into_instance_data() -> None:
    # Mapping: idle sway slow, busy/working fast, EMP nearly frozen.
    assert overseer_runtime.tentacle_speed("PATROLLING") == 0.55
    assert overseer_runtime.tentacle_speed("IDLE") == 0.55
    assert overseer_runtime.tentacle_speed(None) == 0.55
    assert overseer_runtime.tentacle_speed("ENGAGED_HARVEST") == 2.2
    assert overseer_runtime.tentacle_speed("HARVESTING") == 1.8
    assert overseer_runtime.tentacle_speed("RETURNING") == 1.8
    assert overseer_runtime.tentacle_speed("CARRYING_WARRANT") == 1.8
    assert overseer_runtime.tentacle_speed("ENGAGED_DEFENSE") == 2.5
    assert overseer_runtime.tentacle_speed("VECTORING") == 2.2
    assert overseer_runtime.tentacle_speed("QUARANTINING") == 1.1
    assert overseer_runtime.tentacle_speed("EMP_HALT") == 0.05

    # build_buckets packs speed into each row for InstanceList customData.w.
    units = [
        {"unit_id": "SNT-WRD-001", "caste": "warden", "state": "PATROLLING", "position": [5, 0.5, 0], "lod": 1},
        {"unit_id": "SNT-HRV-001", "caste": "harvester", "state": "ENGAGED_HARVEST", "position": [8, 0.5, 2], "lod": 1},
        {"unit_id": "SNT-SAN-001", "caste": "sanitizer", "state": "EMP_HALT", "position": [3, 0.5, -1], "lod": 2},
    ]
    buckets = overseer_runtime.build_buckets(units)
    by_id = {}
    for rows in buckets.values():
        for row in rows:
            by_id[row["unit_id"]] = row
    assert by_id["SNT-WRD-001"]["speed"] == 0.55
    assert by_id["SNT-HRV-001"]["speed"] == 2.2
    assert by_id["SNT-SAN-001"]["speed"] == 0.05
    assert by_id["SNT-SAN-001"]["limp"] == 1.0

    # Vertex shaders read INSTANCE_DATA.w as activity speed (no per-tentacle QML).
    for name in ("hull.vert", "emissive.vert"):
        text = (ASSETS / "shaders" / name).read_text(encoding="utf-8")
        assert "INSTANCE_DATA.w" in text
        assert "uTime * speed" in text
        assert "max(INSTANCE_DATA.w, 0.05)" in text
