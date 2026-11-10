"""Overseer glyph trails carry only real harvest titles and URLs back to the core."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from arelis.ui import overseer_runtime as o

ASSETS = Path(__file__).resolve().parents[1] / "arelis/assets/sentinel/overseer"
NOW = 1_800_000_000.0


def _receipt(rid: str, title: str, *, age: float = 0.5, action: str = "arxiv",
             source: str = "http://arxiv.org/abs/1606.09251v1", caste: str = "harvester",
             ok: bool = True) -> dict:
    at = datetime.fromtimestamp(NOW, UTC) - timedelta(seconds=age)
    return {"receipt_id": rid, "unit_id": "SNT-HRV-001", "caste": caste, "kind": "catalog",
            "source": source, "ok": ok, "sha256": "0" * 64, "span": "x",
            "metadata": {"action": action, "title": title}, "at": at.isoformat()}


def test_glyph_trails_come_only_from_fresh_titled_harvest_results() -> None:
    unit = [{"unit_id": "SNT-HRV-001", "caste": "harvester", "state": "RETURNING", "position": [5, 0.5, 2]}]
    receipts = [
        _receipt("r1", "SPARC: mass models for 175 disk galaxies"),
        _receipt("r2", "Cuspy halo problem", action="wikipedia",
                 source="https://en.wikipedia.org/wiki/Cuspy_halo_problem", age=1.0),
        _receipt("r3", ""),  # no title in the snapshot: no trail, no made-up text
        _receipt("r4", "Old result", age=9.0),  # past the 5 s lifetime
        _receipt("r5", "Failed fetch", ok=False),
        _receipt("r6", "Sanitizer note", caste="sanitizer"),
    ]
    frame = o.build_frame(unit, 76.0, receipts=receipts, snapshot_ts=NOW)
    trails = frame["glyphTrails"]
    assert [t["id"] for t in trails] == ["r1", "r2"]
    arxiv, wiki = trails
    assert arxiv["lanes"] == ["SPARC: mass models for 175 disk galaxies", "arxiv.org/abs/1606.09251v1"]
    assert wiki["source_id"] == "wikipedia"
    assert wiki["lanes"][0] == "Cuspy halo problem"
    labels = {row["id"]: row for row in frame["sourceLabels"]}
    assert (arxiv["x"], arxiv["z"], arxiv["color"]) == (labels["arxiv"]["x"], labels["arxiv"]["z"], labels["arxiv"]["color"])

    assert o.build_frame(unit, 76.0, receipts=receipts[2:], snapshot_ts=NOW)["glyphTrails"] == []
    assert o.build_frame(unit, 76.0)["glyphTrails"] == []

    # A fifth live trail ends the oldest; lanes stop at 60 glyphs, ASCII only.
    many = [_receipt(f"m{k}", "\u00c5ngstr\u00f6m " + "x" * 80, age=0.1 * k) for k in range(5)]
    capped = o.build_frame(unit, 76.0, receipts=many, snapshot_ts=NOW)["glyphTrails"]
    assert [t["id"] for t in capped] == ["m0", "m1", "m2", "m3"]
    assert capped[0]["lanes"][0].startswith("Angstrom xx")
    assert all(len(lane) <= o.GLYPH_LANE_MAX for t in capped for lane in t["lanes"])
    assert sum(len(lane) for t in capped for lane in t["lanes"]) <= o.GLYPH_CAP

    # One instanced quad per glyph; one size for every source; flow runs on the GPU.
    vert = (ASSETS / "shaders" / "glyph.vert").read_text(encoding="utf-8")
    assert "float size = 0.5 * step(0.001, vAlpha);" in vert
    assert "uTime - INSTANCE_DATA.y" in vert
    assert "float t = (age * arcLen / 2.5 - slot * spacing) / arcLen;" in vert
    qml = (ASSETS / "OverseerView.qml").read_text(encoding="utf-8")
    assert 'vertexShader: "shaders/glyph.vert"' in qml
    assert "instancing: root.glyphList" in qml
