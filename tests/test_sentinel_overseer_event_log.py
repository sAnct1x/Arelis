"""Overseer event log (Iris FIX-LIST rank 2): repeats collapse into one row in
plain words, and the console never shows a cut-off row."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine

from arelis.ui import overseer_runtime
from tests.overseer_render_helpers import isolated_render

ASSETS = Path(__file__).resolve().parents[1] / "arelis/assets/sentinel/overseer"
PACK = "3-Sentinel HUNTER-SEEKER Pack (SNT-TRP-001 + SNT-TRP-002, SNT-TRP-003)"


def _entry(seq: int, t: str, message: str, *, unit: str = "SNT-TRP-001", caste: str = "tripwire",
           level: str = "TRIPWIRE", phase: str = "PACK COMPLETE") -> dict:
    return {"seq": seq, "iso_time": f"13:{t}.000", "unit_id": unit, "caste": caste, "level": level,
            "phase": phase, "message": message}


def test_event_log_collapses_repeats_in_plain_words() -> None:
    deploy, done = f"{PACK} deployed for tripwire:verify", f"{PACK} finished tripwire:verify"
    log = [
        _entry(1, "17:43", "Sentinel Hive initialized: 22 units", unit="HIVE-CORE", caste="",
               level="INFO", phase="BOOT"),
        _entry(2, "18:00", deploy, phase="HUNTER-SEEKER"),
        _entry(3, "18:01", done + " (ok=True, title=)"),
        _entry(4, "19:00", "New listening TCP port(s) opened on host since boot: :8080",
               unit="SNT-WRD-001", caste="warden", level="WARDEN", phase="NEW OS PORT BOUND"),
        _entry(5, "20:00", deploy, phase="HUNTER-SEEKER"),
        _entry(6, "20:01", done + " (ok=True, title=)"),
        _entry(7, "21:00", deploy, phase="HUNTER-SEEKER"),
        _entry(8, "21:01", done + " (ok=False, title=timeout)", level="ALERT",
               phase="HUNTER-KILLER BLOCK"),
        _entry(9, "25:00", deploy, phase="HUNTER-SEEKER"),
        _entry(10, "25:40", done + " (ok=True, title=)"),
        _entry(11, "26:00", deploy, phase="HUNTER-SEEKER"),
    ]
    session = overseer_runtime.LogSession()
    # Overlapping snapshots, as the host sees them: each row counts once.
    session.ingest(log[:6])
    hud = overseer_runtime.build_hud({"telemetry_log": log[3:]}, log_session=session)
    rows = [(r["time"], r["count"], r["range"], r["message"], r["failed"]) for r in hud["logs"]]
    assert rows == [
        ("13:26:00", 1, "", "Tripwire pack of 3 running verify", False),
        ("13:25:40", 3, "13:18:00 to 13:25:40", "Tripwire pack of 3 ran verify, all ok", False),
        ("13:21:01", 1, "", "Tripwire pack of 3 ran verify, failed: timeout", True),
        ("13:19:00", 1, "", "New listening TCP port(s) opened on host since boot: :8080", False),
        ("13:17:43", 1, "", "Sentinel Hive initialized: 22 units", False),
    ]
    assert hud["logs"][1]["raw"].endswith(done + " (ok=True, title=)")
    raw = session.rows(repeats=False)
    assert [r["seq"] for r in raw] == list(range(11, 0, -1))
    assert raw[1]["message"] == "Tripwire pack of 3 ran verify, ok"
    assert not any("title=" in r["message"] or "ok=" in r["message"] for r in raw)


@isolated_render()
def test_event_log_viewport_shows_whole_rows(qt_app) -> None:
    engine = QQmlEngine()
    engine.addImportPath(str(ASSETS))
    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(ASSETS / "OverseerHud.qml")))
    hud = comp.create()
    assert hud is not None, "; ".join(e.toString() for e in comp.errors())
    try:
        for width, height in ((1200, 780), (2110, 1306), (1600, 901)):
            hud.setProperty("width", width)
            hud.setProperty("height", height)
            qt_app.processEvents()
            console = hud.findChild(QObject, "OverseerConsole")
            logs = hud.findChild(QObject, "OverseerLogList")
            top = logs.mapToItem(console, QPointF(0, 0)).y()
            assert logs.height() >= 24 and logs.height() % 24 == 0, (width, logs.height())
            assert top + logs.height() == console.height() - 16, (width, top)
    finally:
        hud.deleteLater()
        qt_app.processEvents()
