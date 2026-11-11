"""Overseer polish rank 3: inspector docked outside the free well."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QSizeF, Qt, QUrl
from PySide6.QtGui import QColor
from PySide6.QtQml import QQmlProperty
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest

from arelis.ui import overseer_runtime
from tests.overseer_render_helpers import isolated_render

HUD_QML = (
    Path(__file__).resolve().parents[1]
    / "arelis/assets/sentinel/overseer/OverseerHud.qml"
)
ASSETS = Path(__file__).resolve().parents[1] / "arelis/assets/sentinel/overseer"


def _units() -> list[dict]:
    return [
        {
            "unit_id": "SNT-HRV-001",
            "caste": "harvester",
            "state": "PATROLLING",
            "tentacles": 8,
            "current_task": "gather ingress",
        },
        {
            "unit_id": "SNT-WRD-001",
            "caste": "warden",
            "state": "PATROLLING",
            "tentacles": 12,
        },
    ]


def _snap() -> dict:
    return {
        "metrics": {"warrants_minted": 238, "security_events": 0},
        "units": _units(),
        "castes": [
            {
                "caste_id": "harvester",
                "allowed_capabilities": [
                    "fetch_url",
                    "query_arxiv",
                    "query_horizons",
                    "query_wikipedia",
                    "write_harvest_report",
                ],
            }
        ],
        "recent_receipts": [],
        "telemetry_log": [
            {
                "seq": 1,
                "iso_time": "13:17:46.100",
                "unit_id": "SNT-HRV-001",
                "caste": "harvester",
                "level": "HARVEST",
                "message": "New listening TCP port :8080 opened on host since boot",
            },
            {
                "seq": 2,
                "iso_time": "13:25:40.120",
                "unit_id": "SNT-TRP-001",
                "caste": "tripwire",
                "level": "TRIPWIRE",
                "message": "3-Sentinel HUNTER-SEEKER Pack (SNT-TRP-001) finished tripwire:verify (ok=True, title=)",
            },
        ],
    }


def _named(root, name: str):
    if root is None:
        return None
    stack = [root]
    while stack:
        cur = stack.pop()
        if cur is None:
            continue
        if cur.objectName() == name:
            return cur
        if hasattr(cur, "childItems"):
            try:
                stack.extend(cur.childItems() or [])
            except RuntimeError:
                pass
    return None


def _show_hud(qt_app, width: int = 2110, height: int = 1306):
    """Lay the HUD out at width x height whatever size the OS gives the window.

    The window manager may clamp a top-level window to the screen (the
    Windows runner gave a 2110 x 1306 request 1028 x 749), so the root item
    owns the size and the view follows it instead of the other way round.
    """
    view = QQuickView()
    view.engine().addImportPath(str(ASSETS))
    view.setColor(QColor("#0b0714"))
    view.setResizeMode(QQuickView.SizeViewToRootObject)
    view.setSource(QUrl.fromLocalFile(str(HUD_QML)))
    assert view.status() == QQuickView.Status.Ready, [e.toString() for e in view.errors()]
    root = view.rootObject()
    assert root is not None
    # The HUD fills its parent; in this bare view that is the clamped window.
    assert QQmlProperty(root, "anchors.fill").reset()
    root.setSize(QSizeF(width, height))
    view.show()
    qt_app.processEvents()
    assert (root.width(), root.height()) == (width, height)
    return view, root


@isolated_render(software=True)
def test_overseer_inspector_docks_outside_well_without_unavailable(qt_app) -> None:
    """One behaviour change: docked inspector only when selected, no unavailable rows."""
    # Free well loses the dock column (360 + 2% edge + 16 gap) when open.
    open_c = overseer_runtime.free_viewport_center(2110, 1306, True)
    closed_c = overseer_runtime.free_viewport_center(2110, 1306, False)
    # Full-bleed scene (chat off): the left edge is the 42 px margin, not a
    # list column, so the open centre is 867 and the right edge is 1692.
    assert abs(open_c[0] - 867.0) < 1.0
    assert open_c[0] < closed_c[0]
    assert abs(overseer_runtime._free_viewport_edges(2110, 1306, True)[2] - 1692.0) < 1.0
    assert overseer_runtime.free_viewport_shift(2110, 1306, True) != overseer_runtime.free_viewport_shift(
        2110, 1306, False
    )

    card = overseer_runtime.inspector_card(
        _units()[0],
        castes=_snap()["castes"],
        receipts=_snap()["recent_receipts"],
        telemetry_log=_snap()["telemetry_log"],
    )
    assert card["unit_id"] == "SNT-HRV-001"
    assert card["role"] == "Gather"
    assert [row["key"] for row in card["live"]] == ["state", "tentacles"]
    assert "Target" in card["missing"]
    assert "Warrant hash" in card["missing"]
    assert card["capabilities"] == [
        "fetch_url",
        "query_arxiv",
        "query_horizons",
        "query_wikipedia",
        "write_harvest_report",
    ]
    assert len(card["recent"]) == 1
    assert "8080" in card["recent"][0]["message"]
    assert "unavailable" not in str(card)

    view, root = _show_hud(qt_app)

    empty_hud = overseer_runtime.build_hud(_snap(), selected_id="", camera_distance=32.0)
    root.setProperty("pills", empty_hud["pills"])
    root.setProperty("swarmRows", empty_hud["swarmRows"])
    root.setProperty("inspector", empty_hud["inspector"])
    root.setProperty("logs", empty_hud["logs"])
    root.setProperty("inspectorOpen", False)
    root.setProperty("selectedUnitId", "")
    qt_app.processEvents()
    panel = _named(root, "OverseerInspector")
    assert panel is not None
    assert bool(panel.property("visible")) is False
    assert empty_hud["inspectorCollapsed"] is True

    hud = overseer_runtime.build_hud(_snap(), selected_id="SNT-HRV-001")
    root.setProperty("pills", hud["pills"])
    root.setProperty("swarmRows", hud["swarmRows"])
    root.setProperty("inspector", hud["inspector"])
    root.setProperty("logs", hud["logs"])
    root.setProperty("inspectorOpen", True)
    root.setProperty("selectedUnitId", "SNT-HRV-001")
    qt_app.processEvents()
    panel = _named(root, "OverseerInspector")
    assert panel is not None
    assert bool(panel.property("visible")) is True
    assert float(panel.property("width") or 0) == 360
    # The 2% overlay margin (42 px) from the right edge of the 2110 window.
    right_edge = float(panel.property("x") or 0) + float(panel.property("width") or 0)
    assert abs(right_edge - (2110 - 42)) < 1.5
    assert float(panel.property("x") or 0) >= 1692 - 1  # well ends at 1692
    height = float(panel.property("height") or 0)
    assert height > 200
    assert height < 900  # hugs content; no 240 px empty band forcing a tall plate

    title = _named(root, "OverseerInspectorTitle")
    assert title is not None and "SNT-HRV-001" in str(title.property("text") or "")
    role = _named(root, "OverseerInspectorRole")
    assert role is not None
    assert "Harvester" in str(role.property("text") or "")
    assert "Gather" in str(role.property("text") or "")
    state = _named(root, "OverseerInspector_state")
    assert state is not None and "PATROLLING" in str(state.property("text") or "")
    tent = _named(root, "OverseerInspector_tentacles")
    assert tent is not None and "8" in str(tent.property("text") or "")
    assert _named(root, "OverseerInspector_eyes") is None  # missing, not a row
    miss = _named(root, "OverseerInspectorMissingList")
    assert miss is not None
    miss_text = str(miss.property("text") or "")
    assert "Eyes" in miss_text and "Target" in miss_text
    assert "unavailable" not in miss_text.lower()
    recent = _named(root, "OverseerInspectorRecent")
    assert recent is not None and bool(recent.property("visible")) is True
    retask = _named(root, "OverseerAction_retask")
    assert retask is not None
    assert bool(retask.property("enabled")) is False
    assert "unavailable" not in str(retask.property("Accessible.name") or "").lower()
    deselect = _named(root, "OverseerInspectorDeselect")
    assert deselect is not None

    # Deselect hides the dock.
    root.unitChosen.emit("")
    qt_app.processEvents()
    # Signal alone does not clear selectedUnitId on a bare HUD; the View does.
    # Drive the same path the View uses:
    root.setProperty("selectedUnitId", "")
    root.setProperty("inspectorOpen", False)
    root.setProperty("inspector", overseer_runtime.inspector_card(None))
    qt_app.processEvents()
    assert bool(panel.property("visible")) is False

    view.deleteLater()
    qt_app.processEvents()


@isolated_render(software=True)
def test_overseer_retire_confirms_in_place(qt_app) -> None:
    """First Retire click arms; second posts; selection change clears without posting."""
    view, root = _show_hud(qt_app)

    hud = overseer_runtime.build_hud(_snap(), selected_id="SNT-HRV-001")
    root.setProperty("pills", hud["pills"])
    root.setProperty("swarmRows", hud["swarmRows"])
    root.setProperty("inspector", hud["inspector"])
    root.setProperty("logs", hud["logs"])
    root.setProperty("inspectorOpen", True)
    root.setProperty("selectedUnitId", "SNT-HRV-001")
    root.setProperty("missionQuery", "")
    qt_app.processEvents()

    seen: list[tuple[str, dict]] = []

    def _capture(name, payload) -> None:
        seen.append((str(name), overseer_runtime.coerce_hud_payload(payload)))

    root.hudCommand.connect(_capture)

    retire = _named(root, "OverseerAction_retire")
    assert retire is not None

    def click_retire() -> None:
        mid = QPointF(
            float(retire.property("width") or 8) / 2.0,
            float(retire.property("height") or 8) / 2.0,
        )
        QTest.mouseClick(
            view, Qt.LeftButton, Qt.NoModifier, retire.mapToScene(mid).toPoint()
        )
        qt_app.processEvents()

    def retire_label() -> str:
        for child in retire.childItems() or []:
            value = child.property("text")
            if value is not None:
                return str(value)
        return ""

    # First click arms only: no hudCommand.
    click_retire()
    assert bool(root.property("retireArmed")) is True
    assert seen == []
    assert retire_label() == "Confirm retire"

    # Second click within the window emits retire and clears the arm.
    click_retire()
    assert len(seen) == 1
    assert seen[0][0] == "retire"
    assert seen[0][1].get("unit_id") == "SNT-HRV-001"
    assert seen[0][1].get("caste") == "harvester"
    assert bool(root.property("retireArmed")) is False
    assert retire_label() == "Retire"

    # Arm again, then change selection: arm clears without posting again.
    seen.clear()
    click_retire()
    assert bool(root.property("retireArmed")) is True
    assert seen == []
    root.setProperty("selectedUnitId", "SNT-WRD-001")
    qt_app.processEvents()
    assert bool(root.property("retireArmed")) is False
    assert seen == []

    view.deleteLater()
    qt_app.processEvents()


def test_overseer_retask_recall_copy_is_plain() -> None:
    """Retask/Recall tips and the inspector docs use plain words, not jargon."""
    hud = (HUD_QML).read_text(encoding="utf-8")
    docs = (
        Path(__file__).resolve().parents[1] / "docs/sentinels.md"
    ).read_text(encoding="utf-8")
    assert "Not available: the hive cannot give one unit a new job." in hud
    assert (
        "Not available: Recall would shrink the whole caste, not just this unit."
        in hud
    )
    assert "fail-closed per-unit retask" not in hud
    assert "caste scale-down is not a per-unit recall" not in hud
    top = docs.split("## When Sentinel is offline")[0]
    assert "fail-closed" not in top
    assert "caste scale-down" not in top
    assert "dispatch_task path" not in top
    assert "the hive cannot give one unit a new job" in top
    assert "shrink the whole caste, not just this unit" in top
