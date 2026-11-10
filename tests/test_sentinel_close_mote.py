"""The Sentinels close x is drawn inside the Overseer scene, not under it."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QObject

from arelis import sentinel_control
from arelis.ui.sentinel_host import SentinelWindow, teardown_sentinel_window

_ASSETS = Path(__file__).resolve().parents[1] / "arelis" / "assets" / "sentinel" / "overseer"


def test_scene_draws_the_close_x_and_it_closes_the_window(qt_app, monkeypatch, tmp_path) -> None:
    # The scene's native window covered the widget x on screen (Atria, box xcb).
    shutil.copy(_ASSETS / "OverseerCloseMote.qml", tmp_path)
    (tmp_path / "OverseerView.qml").write_text(
        "import QtQuick\nItem { width: 400; height: 300; OverseerCloseMote {} }\n"
    )
    monkeypatch.setattr(sentinel_control, "overseer_url", lambda: "http://127.0.0.1:9/#tok")
    monkeypatch.setattr(sentinel_control, "bridge_target", lambda: None)
    win = SentinelWindow(None)
    monkeypatch.setattr(win, "_asset_dir", lambda: tmp_path)
    try:
        win.show()
        qt_app.processEvents()
        assert win._stack.currentWidget() is win._live
        assert not win._close_mote.isVisible()
        mote = win._scene.rootObject().findChild(QObject, "SentinelCloseMote")
        mote.activated.emit()
        qt_app.processEvents()
        assert not win.isVisible()
    finally:
        teardown_sentinel_window(type("Owner", (), {"sentinel_window": win})())
