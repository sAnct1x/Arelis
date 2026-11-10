"""Overseer Pass B (GAP items 10 to 12): header as overlay text, the tok/s
readout, the legend, the replay strip and the Dispatch origin line."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QFont
from PySide6.QtQml import QQmlComponent, QQmlEngine

from arelis.llm import token_meter
from arelis.ui import overseer_runtime
from tests.overseer_render_helpers import isolated_render

ASSETS = Path(__file__).resolve().parents[1] / "arelis/assets/sentinel/overseer"
WARRANTS_TIP = "Evidence receipts in memory (includes up to 120 from earlier runs)"


def _texts(item) -> list[str]:
    if not item.isVisible():
        return []
    out = [str(item.property("text"))] if item.property("text") else []
    for child in item.childItems():
        out += _texts(child)
    return out


def _hud(qt_app, width: int = 2110, height: int = 1306):
    engine = QQmlEngine()
    engine.addImportPath(str(ASSETS))
    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(ASSETS / "OverseerHud.qml")))
    hud = comp.create()
    assert hud is not None, "; ".join(e.toString() for e in comp.errors())
    hud.setProperty("width", width)
    hud.setProperty("height", height)
    qt_app.processEvents()
    return (engine, comp), hud


SNAP = {
    "metrics": {"warrants_minted": 238, "security_events": 0},
    "units": [
        {"unit_id": "SNT-WRD-001", "caste": "warden", "state": "VECTORING"},
        {"unit_id": "SNT-WRD-002", "caste": "warden", "state": "PATROLLING"},
        {"unit_id": "SNT-HRV-001", "caste": "harvester", "state": "VECTORING",
         "current_task": "Vectoring to arxiv: dwarf galaxy rotation curves"},
    ],
    "telemetry_log": [
        {"seq": 1, "iso_time": "13:25:39.001", "message": "boot"},
        {"seq": 2, "iso_time": "13:25:40.120", "message": "3-Sentinel Pack (SNT-TRP-001) "
         "finished tripwire:verify (ok=True, title=)"},
    ],
}


@isolated_render(software=True)
def test_header_summary_line_carries_every_strip_number(qt_app) -> None:
    _engine, hud = _hud(qt_app)
    try:
        hud.setProperty("pills", overseer_runtime.build_hud(SNAP)["pills"])
        qt_app.processEvents()
        title = hud.findChild(QObject, "OverseerTitle")
        assert _texts(title)[0] == "Sentinels"
        assert title.childItems()[0].property("color").name() == "#e8dcfb"
        line = " ".join(_texts(hud.findChild(QObject, "OverseerSummary")))
        assert line == (
            "3 units ·  1 fetching ·  0 threats ·  2 Wardens patrolling · 1 engaged ·  "
            "238 warrants ·  last 13:25:40 Tripwire verify, ok ·  "
            "hive live · all local · sending out blocked"
        )
        assert hud.findChild(QObject, "OverseerStatusStrip") is None
        warrants = hud.findChild(QObject, "OverseerStrip_warrants")
        assert warrants.property("color").name() == "#cdb2f7"
        tips = [str(o.property("text")) for o in warrants.findChildren(QObject)
                if "ToolTipAttached" in o.metaObject().className()]
        assert tips == [WARRANTS_TIP]

        # 1028 px: pieces drop from the right, none reach Emergency stop.
        hud.setProperty("width", 1028)
        qt_app.processEvents()
        stop = hud.findChild(QObject, "OverseerEmergencyStop").mapToItem(hud, QPointF(0, 0)).x()
        shown = [c for c in hud.findChild(QObject, "OverseerSummary").childItems() if c.isVisible()]
        assert 3 <= len(shown) < 7
        right = max(c.mapToItem(hud, QPointF(c.width(), 0)).x() for c in shown)
        assert right <= stop - 16
    finally:
        hud.deleteLater()
        qt_app.processEvents()


@isolated_render(software=True)
def test_tok_rate_readout_only_while_tokens_flow(qt_app) -> None:
    t0 = time.monotonic() + 10_000.0
    assert token_meter.rate(t0) == 0.0
    for i in range(40):
        token_meter.note_token(t0 + i * 0.025)
    flowing = token_meter.rate(t0 + 1.0)
    assert 38 <= flowing <= 41
    assert token_meter.rate(t0 + 1.0 + token_meter.STALE_S + 0.01) == 0.0

    _engine, hud = _hud(qt_app)
    try:
        readout = hud.findChild(QObject, "OverseerTokRate")
        assert not readout.isVisible()
        hud.setProperty("tokRate", round(flowing))
        qt_app.processEvents()
        assert readout.isVisible() and readout.property("text") == f"{round(flowing)} tok/s"
        assert readout.property("font").family() == "Space Mono"
        stop = hud.findChild(QObject, "OverseerEmergencyStop")
        assert readout.mapToItem(hud, QPointF(0, 0)).y() >= stop.mapToItem(hud, QPointF(0, stop.height())).y()
        hud.setProperty("tokRate", 0)
        qt_app.processEvents()
        assert not readout.isVisible()
    finally:
        hud.deleteLater()
        qt_app.processEvents()


@isolated_render(software=True)
def test_legend_lists_castes_counts_roles_and_red_eye_note(qt_app) -> None:
    _engine, hud = _hud(qt_app)
    try:
        hud.setProperty("pills", overseer_runtime.build_hud(SNAP)["pills"])
        qt_app.processEvents()
        legend = hud.findChild(QObject, "OverseerLegend")
        assert _texts(legend) == [
            "Warden", "2", "guards the core",
            "Harvester", "1", "fetches sources",
            "Sanitizer", "0", "checks results",
            "Tripwire", "0", "watches the edge",
            "Stalker", "0", "hunts threats",
            "Red eyes appear only on a real threat.",
        ]
        assert legend.property("x") == round(2110 * 0.02)
        replay = hud.findChild(QObject, "OverseerReplay")
        bottom = legend.mapToItem(hud, QPointF(0, legend.height())).y()
        assert bottom <= replay.mapToItem(hud, QPointF(0, 0)).y()
    finally:
        hud.deleteLater()
        qt_app.processEvents()


@isolated_render(software=True)
def test_replay_strip_ticks_last_ten_minutes_and_click_opens_event(qt_app) -> None:
    from PySide6.QtQuick import QQuickView
    from PySide6.QtTest import QTest

    now = time.time()
    session = overseer_runtime.LogSession()
    session.ingest([
        {"seq": 1, "timestamp": now - 900, "level": "HARVEST", "caste": "harvester",
         "message": "old"},
        {"seq": 2, "timestamp": now - 300, "level": "HARVEST", "caste": "harvester",
         "message": "SNT-HRV-001 deployed for arxiv"},
        {"seq": 3, "timestamp": now - 150, "level": "TRIPWIRE", "caste": "tripwire",
         "message": "verify"},
        {"seq": 4, "timestamp": now - 60, "level": "THREAT", "caste": "warden", "message": "x"},
    ])
    ticks = session.replay_ticks(now)
    assert [(t["seq"], t["kind"]) for t in ticks] == [(2, "fetch"), (3, "tripwire"), (4, "threat")]

    view = QQuickView()
    view.engine().addImportPath(str(ASSETS))
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.resize(1028, 749)
    view.setSource(QUrl.fromLocalFile(str(ASSETS / "OverseerHud.qml")))
    hud = view.rootObject()
    assert hud is not None, [e.toString() for e in view.errors()]
    try:
        view.show()
        hud.setProperty("logs", [{"seq": s, "time": "", "summary": str(s)} for s in (2, 3, 4)])
        hud.setProperty("replayTicks", ticks)
        qt_app.processEvents()
        track = hud.findChild(QObject, "OverseerReplayTrack")
        marks = [c for c in track.childItems() if c.metaObject().className().startswith("QQuickRect")]
        assert len(marks) == 3
        band = track.parentItem()
        xs = [c.mapToItem(band, QPointF(0, 0)).x() for c in marks]
        # -300 s sits at the middle ("-5"), -60 s near "now" on the right.
        assert abs(xs[0] - band.width() / 2) <= 3
        assert abs(xs[2] - band.width() * 0.9) <= 3
        assert hud.property("eventsOpen") is False
        tip = marks[1].mapToItem(hud, QPointF(1, marks[1].height() / 2))
        QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(round(tip.x()), round(tip.y())))
        qt_app.processEvents()
        assert hud.property("eventsOpen") is True
        # Re-sending the same ticks adds nothing (the strip appends new seqs only).
        hud.setProperty("replayTicks", list(ticks))
        qt_app.processEvents()
        assert len([c for c in track.childItems() if c.metaObject().className().startswith("QQuickRect")]) == 3
    finally:
        view.close()
        view.deleteLater()
        qt_app.processEvents()


@isolated_render(software=True)
def test_inspector_names_a_task_sent_from_dispatch(qt_app) -> None:
    at = time.mktime((2026, 11, 9, 23, 58, 0, 0, 0, -1))
    dispatches = [{"query": "dwarf galaxy rotation curves", "at": at}]
    card = overseer_runtime.build_hud(SNAP, selected_id="SNT-HRV-001", dispatches=dispatches)
    assert card["inspector"]["origin"] == "task from Dispatch at 11:58 PM"
    # A unit on another task, or with no Dispatch sent, names no origin.
    other = overseer_runtime.build_hud(SNAP, selected_id="SNT-WRD-001", dispatches=dispatches)
    assert other["inspector"]["origin"] == ""
    assert overseer_runtime.build_hud(SNAP, selected_id="SNT-HRV-001")["inspector"]["origin"] == ""

    _engine, hud = _hud(qt_app)
    try:
        hud.setProperty("inspector", card["inspector"])
        hud.setProperty("selectedUnitId", "SNT-HRV-001")
        qt_app.processEvents()
        origin = hud.findChild(QObject, "OverseerInspectorOrigin")
        assert origin.isVisible() and origin.property("text") == "task from Dispatch at 11:58 PM"
    finally:
        hud.deleteLater()
        qt_app.processEvents()


@isolated_render(software=True)
def test_tok_rate_readout_has_no_stray_period_on_narrow_header(qt_app) -> None:
    """The 1028 px header must render "38 tok/s", not "38. tok/s".

    The string is already "38 tok/s". A star showing through the gap after
    "8" is what reads as a period on the 1028 px shot; the sky-coloured
    plate covers that gap. QtRendering and PreferNoHinting also stop a
    hinted "8" from leaving its own baseline blob. This fails if the plate
    or the hinting fix is reverted.
    """
    from PySide6.QtCore import QByteArray
    from PySide6.QtQml import QQmlComponent

    pack, hud = _hud(qt_app, width=1028, height=749)
    engine, _comp = pack
    try:
        hud.setProperty("tokRate", 38)
        qt_app.processEvents()
        readout = hud.findChild(QObject, "OverseerTokRate")
        assert readout.isVisible()
        assert readout.property("text") == "38 tok/s"
        assert "." not in str(readout.property("text"))
        plate = hud.findChild(QObject, "OverseerTokRatePlate")
        assert plate is not None and plate.isVisible()
        fills = [
            c for c in plate.childItems()
            if c.property("color") is not None
        ]
        assert any(c.property("color").name() == "#010103" for c in fills)
        assert plate.width() >= readout.implicitWidth()
        assert plate.height() >= readout.implicitHeight()
        probe = QQmlComponent(engine)
        probe.setData(
            QByteArray(
                b"import QtQuick\n"
                b"QtObject {\n"
                b"    property bool isQtRendering: false\n"
                b"    function check(item) { isQtRendering = item.renderType === Text.QtRendering }\n"
                b"}"
            ),
            QUrl(),
        )
        enums = probe.create()
        assert enums is not None, "; ".join(e.toString() for e in probe.errors())
        enums.check(readout)
        assert enums.property("isQtRendering") is True
        font = readout.property("font")
        assert font.hintingPreference() == QFont.PreferNoHinting
        enums.deleteLater()

    finally:
        hud.deleteLater()
        qt_app.processEvents()
