"""Overseer Pass D follow-up: local coreFocus, label layout, draw cap."""

from __future__ import annotations

import time
from pathlib import Path

from arelis.ui import overseer_runtime as o
from tests.overseer_render_helpers import isolated_render

ASSETS = Path(__file__).resolve().parents[1] / "arelis/assets/sentinel/overseer"


def test_core_focus_is_a_local_view_action() -> None:
    """The Core toggle is a camera preset, not a hive job, so it must not
    log 'Unavailable: no existing route for core_focus' under the composer."""
    for name in ("core_focus", "coreFocus", "exit_core", "exitCore"):
        plan = o.resolve_hud_command(name, {})
        assert plan["ok"] is True
        assert plan.get("local") is True
        assert plan["path"] is None
        assert plan["body"] is None
        assert plan["status"] == ""
        assert "Unavailable" not in str(plan["status"])
    # A name that really has no route still refuses.
    missing = o.resolve_hud_command("not_a_route", {})
    assert missing["ok"] is False
    assert "Unavailable" in str(missing["status"])


@isolated_render()
def test_overview_label_layout_skips_work_when_only_spin_changes(qt_app) -> None:
    """Pass D was sampling two 180-point rings every frame and, in overview,
    rebuilding the chip model whenever a ring spun a degree, even though
    overview chips pin to the untilted extremes."""
    from PySide6.QtCore import QSizeF, QUrl
    from PySide6.QtGui import QColor
    from PySide6.QtQml import QQmlEngine, QQmlExpression
    from PySide6.QtQuick import QQuickView

    view = QQuickView()
    view.engine().addImportPath(str(ASSETS))
    view.setColor(QColor("#0b0714"))
    view.setResizeMode(QQuickView.SizeViewToRootObject)
    view.setSource(QUrl.fromLocalFile(str(ASSETS / "OverseerView.qml")))
    assert view.status() == QQuickView.Status.Ready, view.errors()
    root = view.rootObject()
    root.setSize(QSizeF(2110, 1306))
    view.setGeometry(0, 0, 2110, 1306)
    view.show()
    qt_app.processEvents()
    units = [
        {"unit_id": "SNT-WRD-001", "caste": "warden", "state": "PATROLLING", "position": [8, 0.5, 0]},
    ]
    root.applyFrame(o.build_frame(units, 95.1893, 1306.0, snap={"memories_in_context": 4}))
    qt_app.processEvents()
    ctx = QQmlEngine.contextForObject(root)

    def ev(src: str):
        return QQmlExpression(ctx, root, src).evaluate()[0]

    ev("projectOrbLabels()")
    qt_app.processEvents()
    before = int(root.property("orbLabelComputeCount") or 0)
    assert before >= 1
    ev("memorySpin = 40")
    ev("toolsSpin = 90")
    ev("projectOrbLabels()")
    ev("projectOrbLabels()")
    qt_app.processEvents()
    after = int(root.property("orbLabelComputeCount") or 0)
    assert after == before
    ev("cameraDistance = cameraDistance + 5")
    ev("projectOrbLabels()")
    qt_app.processEvents()
    assert int(root.property("orbLabelComputeCount") or 0) == before + 1
    view.close()
    view.deleteLater()
    qt_app.processEvents()


@isolated_render(native_gl=True)
def test_fetch_fixture_stays_within_draw_cap(qt_app) -> None:
    """The 128-unit live-fetch overview fixture must stay at or under 40
    renderStats draws (the Atria cap)."""
    import math

    from PySide6.QtCore import QSizeF, QUrl
    from PySide6.QtGui import QColor
    from PySide6.QtQml import QQmlEngine, QQmlExpression
    from PySide6.QtQuick import QQuickView

    mix = [
        ("sanitizer", 0.16, "SAN"),
        ("warden", 0.28, "WRD"),
        ("stalker", 0.02, "STK"),
        ("harvester", 0.44, "HRV"),
        ("tripwire", 0.10, "TRP"),
    ]
    total = 128
    counts = [max(1, round(total * f)) for _, f, _ in mix]
    counts[3] += total - sum(counts)
    units, n = [], 0
    for (caste, _, pre), c in zip(mix, counts, strict=True):
        for i in range(c):
            a = n * 0.285
            r = 5 + (n % 4) * 5.5
            units.append({
                "unit_id": f"SNT-{pre}-{i+1:03d}",
                "caste": caste,
                "state": "PATROLLING",
                "position": [r * math.cos(a), 0.6, r * math.sin(a)],
                "velocity": [0.3 * math.sin(a), 0, -0.3 * math.cos(a)],
                "heading": [1, 0, 0],
            })
            n += 1
    hrv = next(u for u in units if u["caste"] == "harvester")
    hrv.update(
        state="ENGAGED_HARVEST",
        action="arxiv",
        current_task="arxiv: dark matter halos",
        target_node_id="ht-1",
    )
    nodes = [{
        "node_id": "ht-1",
        "kind": "harvest_target",
        "label": "arXiv",
        "position": [14.0, 1.0, 8.0],
        "status": "EXTRACTING",
        "progress": 0.4,
        "severity": "none",
        "metadata": {"action": "arxiv", "target": "dark matter halos", "unit_id": hrv["unit_id"]},
    }]
    snap = {
        "metrics": {"warrants_minted": 197, "security_events": 0},
        "memories_in_context": 14,
        "tools_running": [
            {"id": "summarize", "elapsed": 4, "timeout": 20},
            {"id": "read_pdf", "elapsed": 2, "timeout": 20},
            {"id": "search_arxiv", "elapsed": 1, "timeout": 20},
        ],
        "recent_receipts": [{
            "ok": True,
            "caste": "harvester",
            "at": "2099-01-01T00:00:00+00:00",
            "source": "https://arxiv.org/abs/1",
            "metadata": {"action": "arxiv", "title": "SPARC: mass models for 175 disk galaxies"},
        }],
    }
    frame = o.build_frame(
        units, 95.1893, 1306.0, nodes=nodes, snap=snap, tok_rate=38,
        receipts=snap["recent_receipts"], snapshot_ts=1_000_000.0,
    )

    view = QQuickView()
    view.engine().addImportPath(str(ASSETS))
    view.setColor(QColor("#0b0714"))
    view.setResizeMode(QQuickView.SizeViewToRootObject)
    view.setSource(QUrl.fromLocalFile(str(ASSETS / "OverseerView.qml")))
    assert view.status() == QQuickView.Status.Ready, view.errors()
    root = view.rootObject()
    root.setSize(QSizeF(2110, 1306))
    view.setGeometry(0, 0, 2110, 1306)
    view.show()
    qt_app.processEvents()
    root.setProperty("reveal", 1.0)
    root.applyFrame(frame)
    qt_app.processEvents()
    ctx = QQmlEngine.contextForObject(root)

    def ev(src: str):
        return QQmlExpression(ctx, root, src).evaluate()[0]

    ev("view.renderStats.extendedDataCollectionEnabled = true")
    draws = 0
    end = time.monotonic() + 20
    while time.monotonic() < end:
        qt_app.processEvents()
        time.sleep(0.01)
        draws = int(ev("view.renderStats.drawCallCount") or 0)
        if draws:
            break
    assert 0 < draws <= 40, f"fetch fixture draws {draws} (cap 40)"
    view.close()
    view.deleteLater()
    qt_app.processEvents()
