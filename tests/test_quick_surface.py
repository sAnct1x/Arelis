"""ARELIS_SURFACE=quick: the window builds one Quick surface, and her figure renders off its thread."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from PySide6.QtTest import QTest


def test_flag_on_builds_one_quick_surface(qt_app, monkeypatch) -> None:
    monkeypatch.setenv("ARELIS_SURFACE", "quick")
    monkeypatch.setenv("ARELIS_AVATAR_ENGINE", "qq3d")
    from PySide6.QtQuickWidgets import QQuickWidget

    from arelis.ui.persona_face import qq3d_avatar
    from arelis.ui.persona_face.panel import PersonaPanel

    if qq3d_avatar.unavailable_reason():
        pytest.skip(qq3d_avatar.unavailable_reason())
    monkeypatch.setattr(qq3d_avatar, "wanted", lambda theme=None: True)

    from arelis.ui.app import ArelisWindow

    bridge = Mock()
    win = ArelisWindow({"ui": {}}, bridge, None, Mock())
    win.resize(900, 600)
    win.show()
    panel = win.persona_panel
    assert isinstance(panel, PersonaPanel)
    host = panel.web
    seen = []  # the breathing loading state holds her slot until her scene is ready
    for _ in range(60):
        surface = getattr(host, "surface", None)
        quick_root = surface.rootObject() if surface is not None else None
        if quick_root is not None:
            seen.append(quick_root.property("loading"))
        if host is not None and (host.is_ready() or getattr(host, "_dead", False)):
            break
        QTest.qWait(100)
    if getattr(host, "_dead", False) and not host.is_ready():
        pytest.skip("no Quick 3D rendering here: her render control did not start")
    assert host.is_ready(), "her scene on the surface never reported ready"
    surfaces = win.findChildren(QQuickWidget)
    assert len(surfaces) == 1 and surfaces[0].parentWidget() is win
    assert win.children().index(surfaces[0]) <= min(
        win.children().index(c)
        for c in win.findChildren(type(win.stage))
        if c.parentWidget() is win
    )
    assert host.root is not None and host.surface is surfaces[0]
    for _ in range(100):  # the breathing state stays until her first posed frame lands
        if surfaces[0].rootObject().property("loading") is False:
            break
        QTest.qWait(100)
    assert True in seen and surfaces[0].rootObject().property("loading") is False, seen
    host.set_state("speaking")
    assert host.root.property("speaking") is True
    win.hide()


def test_night_backdrop_is_drawn_by_the_surface(qt_app, monkeypatch) -> None:
    """Qt punches a QQuickWidget's rect out of the window's own paint: the room must be on it."""
    monkeypatch.setenv("ARELIS_SURFACE", "quick")
    from PySide6.QtQuickWidgets import QQuickWidget

    from arelis.ui.app import ArelisWindow
    from arelis.ui.theme import apply_theme

    win = ArelisWindow({"ui": {}}, Mock(), None, Mock())
    win.resize(900, 600)
    win.show()
    apply_theme("night")
    surface = win.findChildren(QQuickWidget)[0]
    QTest.qWait(300)
    win.repaint()
    QTest.qWait(300)
    # Offscreen Qt has no QRhi to render the surface, so read what it was given to draw.
    source = surface.rootObject().property("backdropSource")
    win.hide()
    apply_theme("sodium")
    assert source.startswith("image://")
    shot = (
        surface.engine()
        .imageProvider("arelisorbit")
        .requestImage(source.split("//", 1)[1].split("/", 1)[1], None, None)
    )
    px = shot.pixelColor(shot.width() // 2, shot.height() // 2)
    assert px.alpha() == 255 and (px.red(), px.green(), px.blue()) != (0, 0, 0)


def test_frametime_log_records_surface_frames(qt_app, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ARELIS_SURFACE", "quick")
    path = tmp_path / "frames.csv"
    monkeypatch.setenv("ARELIS_FRAMETIME_LOG", str(path))
    from PySide6.QtWidgets import QWidget

    from arelis.ui.persona_face import quick_surface

    win = QWidget()
    surface = quick_surface.surface_for(win)
    for _ in range(3):  # offscreen Qt has no QRhi, so stand in for three rendered frames
        surface.quickWindow().afterRendering.emit()
    import shiboken6

    shiboken6.delete(surface)  # the log closes with its surface
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and all(float(v) >= 0 for v in lines[0].split(","))


def test_the_cropped_overlay_is_placed_at_its_offset(qt_app, monkeypatch) -> None:
    """The worker's overlay covers only its box: the surface puts it there, not over the window."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QWidget

    from arelis.ui.persona_face.quick_surface import _quick_widget_class

    host = QWidget()
    host.resize(800, 500)
    s = _quick_widget_class()(host)
    s.resize(800, 500)
    host.show()
    QTest.qWait(100)
    img = QImage(400, 200, QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(2.0)
    img.setOffset(QPoint(120, 60))
    img.fill(0)
    s.set_orbit(img)
    r = s.rootObject().property("orbitRect")
    assert (r.x(), r.y(), r.width(), r.height()) == (120, 60, 200, 100)
    host.hide()


_LOAD_SURFACE = """
import os
os.environ["ARELIS_SURFACE"] = "quick"
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtTest import QTest
app = QApplication([])
from arelis.ui.persona_face import quick_surface
host = QWidget()
host.resize(640, 400)
s = quick_surface.surface_for(host)
host.show()
QTest.qWait(600)
print("root", s.rootObject() is not None)
"""


def test_the_surface_loads_without_unbound_shader_properties() -> None:
    """Every field of common.glsl's block has a property on the overlay ShaderEffect.

    Offscreen never renders a QQuickWidget (no warning there either way), so the surface is
    loaded in a child process on the X display.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    from arelis.ui.persona_face import qq3d_avatar

    if qq3d_avatar.unavailable_reason():
        pytest.skip(qq3d_avatar.unavailable_reason())
    if not os.environ.get("DISPLAY"):
        pytest.skip("needs an X display: offscreen never renders the surface")
    env = dict(os.environ, QT_QPA_PLATFORM="xcb", PYTHONPATH=str(Path(__file__).parents[1]))
    run = subprocess.run(
        [sys.executable, "-c", _LOAD_SURFACE],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert "root True" in run.stdout, run.stderr[-2000:]
    assert "does not have a matching property" not in run.stderr


def test_her_load_renders_off_the_gui_thread_and_the_surface_draws_it(qt_app) -> None:
    """Her scene's frames (where her meshes upload and her pipelines compile) never run on
    the GUI thread: in the QQuickWidget they did, and a cold load froze the window ~10 s twice,
    so the tray menu could not open to Quit. The surface still draws her in her slot."""
    import threading

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget

    from arelis.ui.persona_face import qq3d_avatar, quick_surface

    if qq3d_avatar.unavailable_reason():
        pytest.skip(qq3d_avatar.unavailable_reason())
    win = QWidget()
    win.resize(640, 480)
    made = []
    real_surface_for = quick_surface.surface_for

    def counting_surface_for(top):
        made.append(top)
        return real_surface_for(top)

    quick_surface.surface_for = counting_surface_for
    try:
        av = quick_surface.QuickSurfaceAvatar(win)
        if getattr(av, "control", None) is not None and av.control.rhi() is None:
            win.close()
            assert av.root is None  # the panel and _drop read it on this path too
            pytest.skip("no Quick 3D rendering here: her render control did not start")
        av.setGeometry(320, 0, 320, 480)
        win.show()
        for _ in range(20):
            if av.root is not None and av.root.window() is not None and av.surface is not None:
                break
            QTest.qWait(50)
        av._attach()  # a second attach (a re-entrant show) must not attach her again
    finally:
        quick_surface.surface_for = real_surface_for
    assert av.root is not None and av.root.window() is not None
    threads: set[int] = set()
    av.root.window().afterRendering.connect(
        lambda: threads.add(threading.get_ident()), Qt.ConnectionType.DirectConnection
    )
    for _ in range(100):
        if threads and av.is_ready() and av.surface is not None:
            if av.surface.rootObject().property("figureSource"):
                break
        av.root.window().update()
        QTest.qWait(50)
    figure = av.surface.rootObject().property("figureSource") if av.surface else ""
    win.close()
    assert threads, "her scene rendered no frame"
    assert threading.main_thread().ident not in threads
    # Her scene is in its own window, not the QQuickWidget's (which renders on the GUI thread).
    assert av.root.window() is not av.surface.quickWindow()
    assert len(made) == 1
    assert figure.startswith("image://")


def test_loading_clears_on_a_frame_begun_after_ready_and_frames_keep_coming(qt_app) -> None:
    """Ready means posed, but the frame in flight may predate it: the breathing state stays
    until a frame begun after ready lands, and frames are asked for until then even when the
    scene asks for none (a still scene on macOS CI never cleared it)."""
    from PySide6.QtWidgets import QWidget

    from arelis.ui.persona_face import quick_surface

    class Surface:
        loading = True
        figures = 0

        def set_loading(self, on: bool) -> None:
            self.loading = on

        def set_figure(self, image) -> None:
            self.figures += 1

    host = QWidget()
    av = quick_surface.QuickSurfaceAvatar(host)
    av.surface = Surface()
    asked = []
    av._request = lambda *a: asked.append(1)
    av._ready, av._shown_from = True, None
    av._render._started = 1  # frame 1 is in flight at ready
    quick_surface.QuickSurfaceAvatar._on_status(av)  # ready: shown from frame 2 on
    assert av._shown_from == 2 and asked
    av._render.image, av._render.image_seq = None, 1
    av._on_frame()  # the frame in flight at ready
    assert av.surface.loading is True and len(asked) >= 2
    av._render.image_seq = 2
    av._on_frame()  # the first frame begun after ready
    assert av.surface.loading is False and av.surface.figures == 2
    host.deleteLater()


def test_unset_surface_defaults_to_quick_and_override_still_works(monkeypatch) -> None:
    from arelis.ui.persona_face import qq3d_avatar, quick_surface

    monkeypatch.setattr(qq3d_avatar, "_saved_user_env", lambda name: "")
    monkeypatch.delenv("ARELIS_SURFACE", raising=False)
    assert quick_surface.surface_choice() == ("quick", "default")
    monkeypatch.setenv("ARELIS_SURFACE", "widget")
    assert quick_surface.surface_choice() == ("widget", "env")


def test_a_host_deleted_before_it_attaches_runs_nothing_late(qt_app, qtbot) -> None:
    """A theme switch or a window teardown can delete her host in the turn that built it."""
    from PySide6.QtWidgets import QWidget
    from shiboken6 import Shiboken

    from arelis.ui.persona_face import quick_surface

    host = QWidget()
    av = quick_surface.QuickSurfaceAvatar(host)
    Shiboken.delete(av)
    QTest.qWait(20)  # pytest-qt fails the test on any exception raised in the event loop
    host.deleteLater()


def test_her_frames_do_not_repaint_the_empty_host_widget(qt_app) -> None:
    """The surface draws her; an update() on the host per frame recomposited the window."""
    from PySide6.QtWidgets import QWidget

    from arelis.ui.persona_face import quick_surface

    class Surface:
        def set_loading(self, on: bool) -> None:
            pass

        def set_figure(self, image) -> None:
            pass

    host = QWidget()
    av = quick_surface.QuickSurfaceAvatar(host)
    av.surface = Surface()
    updates = []
    av.update = lambda *a: updates.append(1)
    av._render.image, av._render.image_seq = None, 1
    av._on_frame()
    host.deleteLater()
    assert updates == []


def test_her_chest_reaches_the_strand_once_her_scene_has_compiled(qt_app, monkeypatch) -> None:
    """Her scene compiles asynchronously: root only exists after __init__ has returned."""
    from PySide6.QtWidgets import QWidget

    from arelis.ui.persona_face import quick_surface
    from arelis.ui.persona_face.qq3d_avatar import unavailable_reason

    if unavailable_reason():
        pytest.skip(unavailable_reason())
    host = QWidget()
    av = quick_surface.QuickSurfaceAvatar(host)
    calls = []
    monkeypatch.setattr(av, "_on_chest", lambda *a: calls.append(1))
    for _ in range(100):
        if getattr(av, "root", None) is not None:
            break
        QTest.qWait(20)
    root = av.root
    if root is None:
        host.deleteLater()
        pytest.skip("her scene did not load here")
    root.chestChanged.emit()
    host.deleteLater()
    assert calls
