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
    bands = {b["caste"]: b for b in frame["bands"]}
    # BAND-SPEC 100-unit row: Sanitizer 2 lanes, Warden 3, Harvester 4.
    assert [len(bands[c]["lanes"]) for c in ("sanitizer", "warden", "harvester")] == [2, 3, 4]
    assert math.isclose(bands["harvester"]["radius"], 15.2 + 1.1 * math.sqrt(44), abs_tol=1e-3)
    assert frame["perimeter"] == 35.0
    by_id = {u["unit_id"]: u for u in frame["units"]}
    harv = [by_id[f"SNT-HAR-{i + 1:03d}"] for i in range(44)]
    radii = sorted(round(math.hypot(u["position"][0], u["position"][2]), 1) for u in harv)
    # Spread over four lanes, not one flat ring.
    assert radii[-1] - radii[0] > 3.0
    # The band is tilted: idle units leave the ground plane, above and below.
    heights = [u["position"][1] for u in harv]
    assert max(heights) > 2.0 and min(heights) < -1.0
    # Wardens and Stalkers share one band; Tripwires ride the perimeter.
    assert bands["warden"]["units"] == 30
    trip = by_id["SNT-TRI-001"]
    assert math.isclose(math.hypot(trip["position"][0], trip["position"][2]), 35.0, abs_tol=0.05)


def test_bands_grow_with_units_and_sources_sit_past_the_perimeter() -> None:
    small = o.band_layout({"harvester": 22, "warden": 15, "sanitizer": 8})
    big = o.band_layout({"harvester": 56, "warden": 38, "sanitizer": 20})
    hs = {b["caste"]: b for b in small["bands"]}["harvester"]
    hb = {b["caste"]: b for b in big["bands"]}["harvester"]
    assert len(hs["lanes"]) == 2 and len(hb["lanes"]) == 4
    assert hb["radius"] > hs["radius"]
    assert big["perimeter"] > 35.0 and big["sourceRadius"] == round(big["perimeter"] + 5.0, 4)
    beacons = [
        c
        for c in o.build_harvest_source_conduits(radius=40.0)
        if str(c.get("id", "")).startswith("source-beacon:")
    ]
    assert beacons and all(
        math.isclose(math.hypot(c["sx"], c["sz"]), 40.0, abs_tol=0.05) for c in beacons
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
    flat grey, (15, 14, 17) after the filmic tonemap. The clear colour #111013
    tonemaps to (15, 14, 18), so the floor draw and its full-screen fill go."""
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
    assert env.property("clearColor") == QColor("#111013")
    root.applyFrame(o.build_frame(_units({"warden": 6}), 96.0, 749.0, snapshot_ts=1_800_000_000.0))
    assert root.property("budgetDrawCalls") == root.property("unitDrawCalls") + o.SCENE_FIXED_DRAW
    view.deleteLater()
    qt_app.processEvents()
