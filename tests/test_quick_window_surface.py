"""ARELIS_SURFACE=quickwindow on a real X display: the widgets and her avatar on the QQuickView.

Each case runs in a child process on xcb under app.exec(): offscreen never exposes the
threaded window, and QTest.qWait holds the GIL, which deadlocks the render thread the first
time Quick 3D syncs a Python QQuick3DGeometry (her LayerGeometry) during a frame.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_HEAD = """
import os
os.environ["ARELIS_SURFACE"] = "quickwindow"
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QWidget
app = QApplication([])
from arelis.ui.persona_face import quick_surface
host = QWidget()
host.resize(640, 400)
s = quick_surface.surface_for(host)
QTimer.singleShot(30000, app.quit)
"""


def _run(body: str, tmp_path: Path) -> str:
    from arelis.ui.persona_face import qq3d_avatar

    if qq3d_avatar.unavailable_reason():
        pytest.skip(qq3d_avatar.unavailable_reason())
    if not os.environ.get("DISPLAY"):
        pytest.skip("needs an X display: offscreen never exposes the threaded window")
    env = dict(
        os.environ,
        QT_QPA_PLATFORM="xcb",
        PYTHONPATH=str(Path(__file__).parents[1]),
        ARELIS_DATA_DIR=str(tmp_path),  # the pipeline cache lands here, not the repo
    )
    run = subprocess.run(
        [sys.executable, "-c", _HEAD + body + "\napp.exec()\n"],
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    return run.stdout + "\n--stderr--\n" + run.stderr[-3000:]


def test_widgets_under_the_native_view_reach_the_screen_through_it(tmp_path) -> None:
    """The view is a native child over every widget: their pixels must be drawn on it."""
    out = _run(
        """
label = QLabel("x", host)
label.setGeometry(100, 100, 80, 40)
label.setStyleSheet("background: #ff0000")
host.show()
def first():
    print("first", hex(s.grabWindow().pixel(120, 110)), flush=True)
    label.setStyleSheet("background: #00ff00")  # a repaint of one widget, not the window
    QTimer.singleShot(400, second)
def second():
    print("second", hex(s.grabWindow().pixel(120, 110)), flush=True)
    app.quit()
QTimer.singleShot(1500, first)
""",
        tmp_path,
    )
    assert "first 0xffff0000" in out, out
    assert "second 0xff00ff00" in out, out


def test_her_avatar_attaches_and_follows_her_panel_on_the_view(tmp_path) -> None:
    out = _run(
        """
panel = QWidget(host)
panel.setGeometry(300, 50, 300, 340)
av = quick_surface.QuickSurfaceAvatar(panel)
av.setGeometry(10, 20, 280, 300)
seen = {"ready": False, "fail": ""}
av.ready.connect(lambda: seen.update(ready=True))
av.failed.connect(lambda why: seen.update(fail=why))
def check():
    if not (seen["ready"] or seen["fail"]):
        QTimer.singleShot(200, check)
        return
    sl = av._slot
    print("ready", seen, (sl.x(), sl.y(), sl.width(), sl.height()), flush=True)
    panel.move(200, 60)
    QTimer.singleShot(100, moved)
def moved():
    sl = av._slot
    print("moved", (sl.x(), sl.y(), sl.isVisible()), flush=True)
    av.hide()
    print("hidden", av._slot.isVisible(), flush=True)
    app.quit()
host.show()
QTimer.singleShot(200, check)
""",
        tmp_path,
    )
    assert "ready {'ready': True, 'fail': ''} (310.0, 70.0, 280.0, 300.0)" in out, out
    assert "moved (210.0, 80.0, True)" in out, out
    assert "hidden False" in out, out
