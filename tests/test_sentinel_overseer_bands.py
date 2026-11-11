"""PR E: idle units ride tilted multi-lane caste bands sized by unit count (BAND-SPEC.md)."""

from __future__ import annotations

import math

from arelis.ui import overseer_runtime as o
from tests.overseer_render_helpers import isolated_render


def _units(counts: dict[str, int]) -> list[dict]:
    out = []
    for caste, n in counts.items():
        for i in range(n):
            out.append(
                {
                    "unit_id": f"SNT-{caste[:3].upper()}-{i + 1:03d}",
                    "caste": caste,
                    "state": "PATROLLING",
                    "position": [0.0, 0.5, 0.0],
                    "heading": [1.0, 0.0, 0.0],
                }
            )
    return out


def test_idle_units_sit_on_tilted_lanes_scaled_by_unit_count() -> None:
    units = _units({"sanitizer": 16, "warden": 28, "stalker": 2, "harvester": 44, "tripwire": 10})
    frame = o.build_frame(units, 76.0, 780.0, snapshot_ts=1_800_000_000.0)
    # Pass F: no caste lanes. The picket line is the perimeter (r 39);
    # sources sit at r 41. Incoming positions stay put until a live session steps.
    assert frame["bands"] == []
    assert frame["perimeter"] == 39.0
    assert frame["barrier"]["a"] == 32.0
    assert len(frame["fieldEdge"]) == 16
    by_id = {u["unit_id"]: u for u in frame["units"]}
    trip = by_id["SNT-TRI-001"]
    assert trip["position"] == [0.0, 0.5, 0.0]


def test_bands_grow_with_units_and_sources_sit_past_the_perimeter() -> None:
    small = o.band_layout({"harvester": 22, "warden": 15, "sanitizer": 8})
    big = o.band_layout({"harvester": 56, "warden": 38, "sanitizer": 20})
    hs = {b["caste"]: b for b in small["bands"]}["harvester"]
    hb = {b["caste"]: b for b in big["bands"]}["harvester"]
    assert len(hs["lanes"]) == 2 and len(hb["lanes"]) == 4
    assert hb["radius"] > hs["radius"]
    assert big["perimeter"] >= 39.0 and big["sourceRadius"] == round(big["perimeter"] + 2.0, 4)
    nodes, _labels = o.build_source_nodes(
        {sid: 0 for sid, *_ in o.HARVEST_SOURCES}, radius=40.0
    )
    assert nodes and all(
        math.isclose(math.hypot(c["x"], c["z"]), 40.0, abs_tol=0.05) for c in nodes
    )


def test_working_units_keep_their_hive_position() -> None:
    units = _units({"harvester": 12})
    units[0]["state"] = "ENGAGED_HARVEST"
    units[0]["position"] = [3.0, 1.0, -2.0]
    placed, _ = o.place_band_units(units, 1_800_000_000.0)
    assert placed[0]["position"] == [3.0, 1.0, -2.0]


@isolated_render()
def test_scene_background_is_the_floor_grey_without_a_floor_plane(qt_app) -> None:
    """The 1600 m lit floor filled every pixel at every approved camera with one
    flat grey, (15, 14, 17) after the filmic tonemap. The floor draw and its
    full-screen fill go; the sky is the GAP.md near-black #010103."""
    from pathlib import Path

    from PySide6.QtCore import QObject, QUrl
    from PySide6.QtGui import QColor
    from PySide6.QtQuick import QQuickView

    qml = Path(__file__).resolve().parents[1] / "arelis/assets/sentinel/overseer/OverseerView.qml"
    view = QQuickView()
    view.engine().addImportPath(str(qml.parent))
    view.setSource(QUrl.fromLocalFile(str(qml)))
    assert view.status() == QQuickView.Status.Ready, view.errors()
    root = view.rootObject()
    assert root.findChild(QObject, "overseerFloor") is None
    env = root.findChild(QObject, "overseerEnvironment")
    assert env.property("clearColor") == QColor("#010103")
    root.applyFrame(o.build_frame(_units({"warden": 6}), 96.0, 749.0, snapshot_ts=1_800_000_000.0))
    assert root.property("budgetDrawCalls") == root.property("unitDrawCalls") + o.SCENE_FIXED_DRAW
    view.deleteLater()
    qt_app.processEvents()
