"""Opening the Sentinels window builds one Overseer scene, not two."""

from __future__ import annotations

from PySide6 import QtQuickWidgets

from arelis import sentinel_control
from arelis.ui.sentinel_host import SentinelWindow, teardown_sentinel_window


def test_nested_show_during_scene_build_keeps_one_scene(qt_app, monkeypatch, tmp_path) -> None:
    # On a shown window Qt recreates the native window when the first
    # QQuickWidget is added, and that sends showEvent (so refresh) from
    # inside the QQuickWidget constructor. Offscreen does not do this,
    # so the nested call is made here the way Qt makes it on xcb.
    real = QtQuickWidgets.QQuickWidget
    nested = []

    class NestedShowWidget(real):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            if not nested:  # Qt recreates the window once, for the first one
                nested.append(True)
                parent.refresh()

    (tmp_path / "OverseerView.qml").write_text("import QtQuick\nItem {}\n")
    monkeypatch.setattr(QtQuickWidgets, "QQuickWidget", NestedShowWidget)
    monkeypatch.setattr(sentinel_control, "overseer_url", lambda: "http://127.0.0.1:9/#tok")
    monkeypatch.setattr(sentinel_control, "bridge_target", lambda: None)
    win = SentinelWindow(None)
    monkeypatch.setattr(win, "_asset_dir", lambda: tmp_path)
    win.refresh()
    qt_app.processEvents()
    try:
        assert len(win.findChildren(real)) == 1
        assert win._stack.currentWidget() is win._scene
    finally:
        teardown_sentinel_window(type("Owner", (), {"sentinel_window": win})())
