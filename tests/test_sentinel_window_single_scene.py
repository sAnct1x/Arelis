"""Opening the Sentinels window builds one Overseer scene, in its own window."""

from __future__ import annotations

from PySide6 import QtQuick

from arelis import sentinel_control
from arelis.ui.sentinel_host import SentinelWindow, teardown_sentinel_window


def test_nested_show_during_scene_build_keeps_one_threaded_scene(
    qt_app, monkeypatch, tmp_path
) -> None:
    # On a shown window Qt recreates the native window when the first native
    # scene child is added, and that sends showEvent (so refresh) from inside
    # the scene build. Offscreen does not do this, so it is made here.
    # The scene must be a QQuickWindow (own render thread), not a QQuickWidget,
    # whose GPU-waiting frames run on the GUI thread with the main window's.
    real = QtQuick.QQuickView
    built = []

    class NestedShowView(real):
        def __init__(self, *args) -> None:
            super().__init__(*args)
            built.append(self)
            if len(built) == 1:
                win.refresh()

    (tmp_path / "OverseerView.qml").write_text("import QtQuick\nItem {}\n")
    monkeypatch.setattr(QtQuick, "QQuickView", NestedShowView)
    monkeypatch.setattr(sentinel_control, "overseer_url", lambda: "http://127.0.0.1:9/#tok")
    monkeypatch.setattr(sentinel_control, "bridge_target", lambda: None)
    win = SentinelWindow(None)
    monkeypatch.setattr(win, "_asset_dir", lambda: tmp_path)
    win.refresh()
    qt_app.processEvents()
    try:
        assert built == [win._scene]
        assert win._stack.currentWidget() is win._live
    finally:
        teardown_sentinel_window(type("Owner", (), {"sentinel_window": win})())
