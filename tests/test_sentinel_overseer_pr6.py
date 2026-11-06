"""PR6 Overseer: inset, fade lifecycle, scene filter, list window, LOD, zoom."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from arelis.ui.sentinel_host import (
    SentinelWindow,
    attach_sentinel_mote,
    teardown_sentinel_window,
)
from arelis.ui.sentinel_presence import (
    FADE_CLOSE_MS,
    FADE_CLOSED,
    FADE_OPEN,
    FADE_OPEN_MS,
    REDUCED_MS,
    RIGHT_UNCOVERED,
    PresenceController,
    fade_duration_ms,
    inset_geometry,
    mote_pos,
    right_uncovered,
)

LOGIC = Path(__file__).resolve().parents[1] / "sentinel/sentinel/ui/overseer/overseer_logic.js"


def _node_logic_checks() -> dict:
    script = r"""
const L = require(process.argv[1]);
const out = {};
out.lod200 = L.chooseLod(200, null);
out.lod70 = L.chooseLod(70, null);
out.lod50 = L.chooseLod(50, null);
out.hystStay = L.chooseLod(160, 0);
out.hystLeave = L.chooseLod(150, 0);
out.hystEnter1 = L.chooseLod(70, 2);
out.hystStay2 = L.chooseLod(65, 2);
out.sil2 = L.silhouette(2);
out.win = L.virtualWindow(0, 748, 100);
out.demo = L.snapshotUnits({demo: true, units: [{unit_id: "SNT-DEMO"}]}).length;
out.mixed = L.snapshotUnits({
  units: [
    {unit_id: "SNT-FAKE", demo: true},
    {unit_id: "SNT-SYN", synthetic: true},
    {unit_id: "SNT-WRD-001", caste: "warden", state: "PATROLLING"},
  ],
}).map((u) => u.unit_id);
out.dolly = L.cursorDolly([0, 0, 0], [10, 0, 0], 10, 20);
out.pitchClose = L.pitchDeg(L.ZOOM_MIN);
out.pitchWide = L.pitchDeg(L.ZOOM_MAX);
out.inspWide = L.inspectorCollapsed(L.ZOOM_MAX, null);
out.inspSelected = L.inspectorCollapsed(L.ZOOM_MAX, "SNT-WRD-001");
out.rubberLo = L.wheelStep(L.ZOOM_MIN, -1);
out.chipWide = L.chipState(30, false, 100);
out.chipClose = L.chipState(50, false, 10);
out.groups = L.groupUnits([
  {unit_id: "SNT-WRD-002", caste: "warden", state: "ENGAGED"},
  {unit_id: "SNT-WRD-001", caste: "warden", state: "PATROLLING"},
  {unit_id: "SNT-STK-001", caste: "stalker", state: "VECTORING"},
], "caste");
out.empOk = L.actionAllowed("emp_halt");
out.firewall = L.actionAllowed("firewall");
out.kill = L.actionAllowed("kill");
out.grant = L.actionAllowed("grant");
out.idle = L.emptyTaskLabel(null);
out.stateLabel = L.emptyTaskLabel("PATROLLING");
out.zoomReduced = L.zoomDuration("focus", true);
console.log(JSON.stringify(out));
"""
    proc = subprocess.run(
        ["node", "-e", script, str(LOGIC)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout)


def test_overseer_inset_fade_scene_list_lod_zoom_and_lifecycle(qt_app, monkeypatch) -> None:
    geom = inset_geometry(2560, 1392)
    assert geom == (40, 44, 2110, 1306)
    assert right_uncovered(2560, geom) == RIGHT_UNCOVERED == 410
    small = inset_geometry(1280, 696)
    assert small[0] == 20 and small[1] == 22
    assert small[2] == 1055 and small[3] == 653
    assert mote_pos(2560, 1392) == (1250, 1090)
    assert fade_duration_ms(opening=True, reduced=False) == FADE_OPEN_MS == 650
    assert fade_duration_ms(opening=False, reduced=False) == FADE_CLOSE_MS == 500
    assert fade_duration_ms(opening=True, reduced=True) == REDUCED_MS == 200
    assert fade_duration_ms(opening=False, reduced=True) == 200

    presence = PresenceController()
    class _Surf:
        def __init__(self) -> None:
            self.presenceOpacity = 1.0

        def setProperty(self, key: str, value: object) -> None:
            setattr(self, key, value)

    surf = _Surf()
    assert presence.opacity == FADE_CLOSED
    assert presence.open_window() == 650
    assert presence.opacity == FADE_OPEN == 0.20
    presence.apply_to(surf)
    assert surf.presenceOpacity == 0.20
    assert presence.restore("error") == 500
    assert presence.opacity == FADE_CLOSED
    assert presence.last_reason == "error"
    presence.apply_to(surf)
    assert surf.presenceOpacity == 1.0
    assert presence.restore("quit", reduced=True) == 200
    assert presence.last_reason == "quit"

    js = _node_logic_checks()
    assert js["lod200"] == 0
    assert js["lod70"] == 1
    assert js["lod50"] == 2
    assert js["hystStay"] == 0
    assert js["hystLeave"] == 1
    assert js["hystEnter1"] == 1
    assert js["hystStay2"] == 2
    assert js["sil2"]["head"] == "tapered"
    assert js["sil2"]["lenses"] == 1
    assert js["sil2"]["tentacles"] == 4
    assert js["sil2"]["plates"] is False
    assert js["sil2"]["linkChains"] is False
    assert js["win"]["alive"] == 23
    assert js["win"]["rowH"] == 44
    assert js["demo"] == 0
    assert js["mixed"] == ["SNT-WRD-001"]
    assert js["dolly"] == [-10, 0, 0]
    assert js["pitchClose"] == 22
    assert js["pitchWide"] == 55
    assert js["inspWide"] is True
    assert js["inspSelected"] is False
    assert abs(js["rubberLo"] - 6 * 0.92) < 0.01
    assert js["chipWide"]["badges"] is True
    assert js["chipClose"]["chips"] is True
    assert [g["key"] for g in js["groups"]] == ["warden", "stalker"]
    assert js["groups"][0]["active"] == 1
    assert js["groups"][0]["units"][0]["unit_id"] == "SNT-WRD-002"
    assert js["empOk"] is True
    assert js["firewall"] is False
    assert js["kill"] is False
    assert js["grant"] is False
    assert js["idle"] == "idle"
    assert js["stateLabel"] == "patrolling"
    assert js["zoomReduced"] == 120

    owner = QWidget()
    owner.resize(2560, 1392)
    owner._quick_surface = _Surf()
    mote = attach_sentinel_mote(owner)
    assert mote is not None
    assert mote.pos().x() == 1250 - 11
    assert mote.pos().y() == 1090 - 11
    from arelis import sentinel_control

    monkeypatch.setattr(sentinel_control, "overseer_url", lambda: None)
    win = SentinelWindow(owner)
    owner.sentinel_window = win
    flags = win.windowFlags()
    assert bool(flags & Qt.WindowType.FramelessWindowHint)
    assert bool(flags & Qt.WindowType.Tool)
    win.show()
    qt_app.processEvents()
    assert win.geometry().width() == 2110
    assert win.geometry().height() == 1306
    assert win.presence.opacity == FADE_OPEN
    assert owner._quick_surface.presenceOpacity == FADE_OPEN
    assert win.is_offline()
    assert mote.isHidden()
    theme = win.property("sentinelTheme")
    assert theme in {"filament", "night", "sodium", "matrix"} or theme
    win.close()
    assert win.presence.opacity == FADE_CLOSED
    assert win.presence.last_reason == "close"
    assert owner._quick_surface.presenceOpacity == FADE_CLOSED
    assert not mote.isHidden()

    win2 = SentinelWindow(owner)
    owner.sentinel_window = win2
    win2.show()
    qt_app.processEvents()
    assert win2.presence.opacity == FADE_OPEN
    teardown_sentinel_window(owner)
    assert win2.presence.last_reason == "quit"
    assert win2.presence.opacity == FADE_CLOSED
    assert owner._quick_surface.presenceOpacity == FADE_CLOSED

    err_owner = QWidget()
    err_owner.resize(2560, 1392)
    err_owner._quick_surface = _Surf()
    err = SentinelWindow(err_owner)
    monkeypatch.setattr(sentinel_control, "overseer_url", lambda: "http://127.0.0.1:9/#token")
    monkeypatch.setattr(err, "_ensure_view", lambda: None)
    err.refresh()
    assert err.last_error()
    assert err.presence.last_reason == "error"
    assert err.presence.opacity == FADE_CLOSED
    assert err_owner._quick_surface.presenceOpacity == FADE_CLOSED
    err.close()
