"""The Quick 3D avatar host: same API as the web host, chosen by ARELIS_AVATAR_ENGINE in Filament."""

from __future__ import annotations

import logging

import pytest
from PySide6.QtCore import QEvent, QObject
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

# A stand-in for her private balsam model: one node and one clip timeline.
_STAND_IN = """import QtQuick
import QtQuick3D
import QtQuick.Timeline
import Arelis.PersonaQ3D
Node {
    Model { source: "#Cube"; scale: Qt.vector3d(0.3, 1.7, 0.3); materials: PrincipledMaterial {} }
    Timeline { objectName: "Idle"; startFrame: 0; endFrame: 1000
        animations: [TimelineAnimation { duration: 1000; from: 0; to: 1000; running: false }] }
}
"""


def _model(tmp_path, monkeypatch, *, clips: bool = True):
    d = tmp_path / "qq3d"
    d.mkdir()
    (d / "Ellah_anim.qml").write_text(_STAND_IN, encoding="utf-8")
    if clips:
        (d / "animations").mkdir()
        (d / "animations" / "Idle.qad").write_bytes(b"x")
    monkeypatch.setenv("ARELIS_AVATAR_QQ3D_DIR", str(d))
    return d


def test_host_calls_set_the_scene_properties(tmp_path, monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    _model(tmp_path, monkeypatch)
    from arelis.ui.persona_face.qq3d_avatar import QQ3DAvatar, unavailable_reason

    if unavailable_reason():
        pytest.skip(unavailable_reason())
    host = QQ3DAvatar()
    host.resize(200, 400)
    host.show()
    for _ in range(40):
        if host.is_ready():
            break
        QTest.qWait(100)
    if not host.is_ready():
        pytest.skip("no Quick 3D rendering here")
    root = host.root
    host.set_state("speaking")
    assert root.property("avatarState") == "speaking" and root.property("speaking") is True
    host.set_state("rest")
    assert root.property("avatarState") == "idle" and root.property("speaking") is False
    host.set_level(0.5)
    assert abs(root.property("level") - 0.5) < 1e-6
    host.close()


def _ready_host(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    _model(tmp_path, monkeypatch)
    from arelis.ui.persona_face.qq3d_avatar import QQ3DAvatar, unavailable_reason

    if unavailable_reason():
        pytest.skip(unavailable_reason())
    host = QQ3DAvatar()
    host.resize(200, 400)
    host.show()
    for _ in range(40):
        if host.is_ready():
            break
        QTest.qWait(100)
    if not host.is_ready():
        pytest.skip("no Quick 3D rendering here")
    return host


def test_avatar_state_drives_the_mixer(tmp_path, monkeypatch) -> None:
    host = _ready_host(tmp_path, monkeypatch)
    mixer = host.root.findChild(QObject, "mixer")
    assert mixer is not None
    host.set_state("speaking")
    for _ in range(30):
        if mixer.property("mode") == "speaking":
            break
        QTest.qWait(50)
    assert mixer.property("mode") == "speaking"
    host.close()


def test_frametime_log_writes_one_gate_line_per_frame(tmp_path, monkeypatch) -> None:
    log = tmp_path / "frames.csv"
    monkeypatch.setenv("ARELIS_FRAMETIME_LOG", str(log))
    host = _ready_host(tmp_path, monkeypatch)
    for _ in range(10):
        host.view.update()
        QTest.qWait(50)
    host.close()
    host.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    lines = log.read_text(encoding="utf-8").splitlines()
    assert lines, "no frame lines"
    for line in lines:  # gate_capture.file_frames: t_epoch_ms,frame_ms
        t, ms = (float(x) for x in line.split(","))
        assert t > 1.6e12 and 0 <= ms < 60_000


def test_missing_clips_log_one_error_naming_the_folder(tmp_path, monkeypatch, caplog) -> None:
    d = _model(tmp_path, monkeypatch, clips=False)
    from arelis.ui.persona_face.qq3d_avatar import check_clips

    caplog.set_level(logging.ERROR, logger="arelis.avatar")
    assert check_clips() is False
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert errors == [f"[avatar] clips missing at {d / 'animations'}"]


def test_she_loads_the_look_not_the_plain_model(tmp_path, monkeypatch) -> None:
    from arelis.ui.persona_face.qq3d_avatar import model_path

    d = _model(tmp_path, monkeypatch)
    (d / "Ellah_aether.qml").write_text(_STAND_IN, encoding="utf-8")
    assert model_path() == d / "Ellah_aether.qml"


def test_over_a_see_through_clear_the_bloom_keys_its_alpha(tmp_path, monkeypatch) -> None:
    host = _ready_host(tmp_path, monkeypatch)
    bloom = host.root.findChild(QObject, "bloom")
    assert bloom is not None and bloom.property("keyAlpha") == 1


def test_narrow_band_backs_the_camera_off_so_she_fits_across(tmp_path, monkeypatch) -> None:
    host = _ready_host(tmp_path, monkeypatch)
    cam = host.root.findChild(QObject, "cam")
    host.resize(200, 400)
    QTest.qWait(100)
    wide = cam.property("camZ")
    host.resize(50, 400)
    QTest.qWait(100)
    assert cam.property("camZ") > wide * 1.9
    host.close()


def test_frame_bottom_meets_her_soles_at_any_band_width(tmp_path, monkeypatch) -> None:
    import math

    host = _ready_host(tmp_path, monkeypatch)
    root, cam = host.root, host.root.findChild(QObject, "cam")
    for width in (200, 50):
        host.resize(width, 400)
        QTest.qWait(100)
        half = math.tan(math.radians(cam.property("fieldOfView") / 2)) * cam.property("camZ")
        bottom = cam.property("y") - cam.property("tilt") - half
        assert abs(bottom - root.property("soleY")) < 1e-3
    host.close()


def test_her_view_runs_the_full_band_height(tmp_path, monkeypatch) -> None:
    """A view stopping short of the band cut her floor and glow on a hard line (a box)."""
    QApplication.instance() or QApplication([])
    _model(tmp_path, monkeypatch)
    monkeypatch.setenv("ARELIS_AVATAR_ENGINE", "qq3d")
    monkeypatch.setattr("arelis.ui.persona_face.qq3d_avatar.wanted", lambda theme=None: True)
    from arelis.ui.persona_face.panel import PersonaPanel
    from arelis.ui.persona_face.qq3d_avatar import unavailable_reason

    if unavailable_reason():
        pytest.skip(unavailable_reason())
    panel = PersonaPanel()
    panel.resize(300, 700)
    panel.show()
    QTest.qWait(50)
    if panel.web is None:  # no GPU or GL here: her host failed and the panel dropped it
        panel.close()
        pytest.skip("no Quick 3D rendering here")
    assert panel.web.geometry().height() == panel.height()
    panel.close()


def test_in_filament_the_camera_slides_so_she_stands_right_of_centre(tmp_path, monkeypatch) -> None:
    """She is the full-window base layer: the camera slides, so her centre lands right of centre."""
    monkeypatch.setattr("arelis.ui.theme.active_theme", lambda: "filament")
    host = _ready_host(tmp_path, monkeypatch)  # skips where Quick 3D cannot render (no root)
    host.resize(1600, 900)
    QTest.qWait(50)
    from arelis.ui.persona_stage import FIGURE_X

    assert abs(host.root.property("figureX") - FIGURE_X) < 1e-6
    assert host.root.property("camShift") < 0
    host.close()


def test_her_host_puts_the_gui_thread_ahead_of_a_busy_model(tmp_path, monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    from PySide6.QtCore import QThread

    _model(tmp_path, monkeypatch)
    from arelis.ui.persona_face.qq3d_avatar import QQ3DAvatar, unavailable_reason

    if unavailable_reason():
        pytest.skip(unavailable_reason())
    main = QThread.currentThread()
    main.setPriority(QThread.Priority.NormalPriority)
    host = QQ3DAvatar()
    if host.control.rhi() is None:  # no GPU or GL here: she fails before her render thread
        host.close()
        pytest.skip("no Quick 3D rendering here")
    try:
        assert main.priority() == QThread.Priority.HighPriority
    finally:
        host.close()
        main.setPriority(QThread.Priority.NormalPriority)


def test_her_frames_render_off_the_gui_thread(tmp_path, monkeypatch) -> None:
    """Her scene renders on its own thread, so chat, Python and the filament timer never share her frame."""
    import threading

    from PySide6.QtCore import Qt

    host = _ready_host(tmp_path, monkeypatch)
    view = host.view.quickWindow() if hasattr(host.view, "quickWindow") else host.view
    threads: set[int] = set()
    view.afterRendering.connect(
        lambda: threads.add(threading.get_ident()), Qt.ConnectionType.DirectConnection
    )
    for _ in range(40):
        host.root.setProperty("level", 0.5 if len(threads) % 2 else 0.25)
        view.update()
        QTest.qWait(50)
        if threads:
            break
    host.close()
    assert threads, "no frame rendered"
    assert threading.main_thread().ident not in threads


def test_she_draws_when_her_window_is_restored_from_minimized(tmp_path, monkeypatch) -> None:
    """A window that starts minimized and is restored at the same size still gets her frames."""
    from PySide6.QtWidgets import QWidget

    QApplication.instance() or QApplication([])
    _model(tmp_path, monkeypatch)
    from arelis.ui.persona_face.qq3d_avatar import QQ3DAvatar, unavailable_reason

    if unavailable_reason():
        pytest.skip(unavailable_reason())
    top = QWidget()
    top.resize(200, 400)
    top.showMinimized()
    host = QQ3DAvatar(top)
    if host.control.rhi() is None:  # no GPU or GL here: she never draws, minimized or not
        top.close()
        pytest.skip("no Quick 3D rendering here")
    host.resize(200, 400)
    host.show()
    QTest.qWait(300)
    frames: list[int] = []
    host._render.frame_ready.connect(lambda: frames.append(1))
    top.showNormal()
    for _ in range(100):
        QTest.qWait(50)
        if frames:
            break
    top.close()
    assert frames, "no frame after the window was restored"


def test_her_pipeline_cache_is_saved_after_the_first_frame(tmp_path, monkeypatch) -> None:
    # A hard-killed app never reaches Qt's own save-on-teardown.
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "data"))
    host = _ready_host(tmp_path, monkeypatch)
    from PySide6.QtGui import QRhi

    from arelis.ui.persona_face.qq3d_avatar import pipeline_cache_path

    if host.control.rhi().backend() == QRhi.Implementation.Metal:
        host.close()  # Qt's Metal backend keeps no pipeline cache data (binary archives off)
        pytest.skip("Metal gives no pipeline cache data")

    path = pipeline_cache_path()
    for _ in range(40):
        if path.exists() and path.stat().st_size:
            break
        host.view.update()
        QTest.qWait(50)
    saved = path.exists() and path.stat().st_size > 0
    host.close()
    assert saved


@pytest.mark.real_qq3d_model
def test_model_lookup_is_app_then_override_then_bundled(tmp_path, monkeypatch) -> None:
    from arelis.ui.persona_face import qq3d_avatar

    monkeypatch.delenv("ARELIS_AVATAR_QQ3D_DIR", raising=False)
    monkeypatch.setattr(qq3d_avatar, "_saved_user_env", lambda name: "")
    monkeypatch.setattr(qq3d_avatar, "user_data_dir", lambda: tmp_path)
    user = tmp_path / "avatar" / "qq3d"
    user.mkdir(parents=True)
    (user / "pipeline.cache").write_bytes(b"x")  # a cache alone is not a model
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.setenv("ARELIS_AVATAR_QQ3D_DIR", str(other))  # set, but holds no model
    bundled = qq3d_avatar.bundled_model_dir()
    assert (bundled / qq3d_avatar.LOOK_FILE).is_file()
    assert qq3d_avatar.model_source() == ("bundled", bundled)
    (other / qq3d_avatar.LOOK_FILE).write_text("x", encoding="utf-8")
    assert qq3d_avatar.model_source() == ("override", other)
    (user / qq3d_avatar.LOOK_FILE).write_text("x", encoding="utf-8")
    assert qq3d_avatar.model_source() == ("app", user)


def test_dispose_during_a_slow_frame_waits_for_it_before_freeing_the_control(
    tmp_path, monkeypatch
) -> None:
    """A frame outliving stop()'s wait must keep the control until run() returns."""
    import time

    QApplication.instance() or QApplication([])
    _model(tmp_path, monkeypatch)
    from arelis.ui.persona_face import qq3d_avatar
    from arelis.ui.persona_face.qq3d_avatar import QQ3DAvatar, unavailable_reason

    if unavailable_reason():
        pytest.skip(unavailable_reason())
    host = QQ3DAvatar()
    host.resize(200, 400)
    host.show()
    render = host._render
    real_render, real_wait = render._calls["render"], qq3d_avatar._RenderThread.wait
    render._calls["render"] = lambda: (time.sleep(0.6), real_render())
    monkeypatch.setattr(
        qq3d_avatar._RenderThread, "wait", lambda self, ms=-1: real_wait(self, 50 if ms > 0 else ms)
    )
    for _ in range(100):
        if render.busy or render.error:
            break
        QTest.qWait(10)
    if not render.busy:
        pytest.skip("no Quick 3D rendering here")
    host._dead = True  # only the render thread is under test
    render.dispose()
    for _ in range(100):
        if not render.isRunning() and render not in qq3d_avatar._LIVE:
            break
        QTest.qWait(20)
    assert render.error is None
    assert render not in qq3d_avatar._LIVE


def test_she_stays_hidden_and_not_ready_until_the_mixer_poses_her(tmp_path, monkeypatch) -> None:
    """A loaded model shows its bind pose (the T-pose) until the mixer's first frame writes a clip
    pose: she is not drawn, and the host is not ready, before that."""
    QApplication.instance() or QApplication([])
    _model(tmp_path, monkeypatch)
    from arelis.ui.persona_face.qq3d_avatar import QQ3DAvatar, unavailable_reason

    if unavailable_reason():
        pytest.skip(unavailable_reason())
    host = QQ3DAvatar()
    if getattr(host, "root", None) is None:
        pytest.skip("no Quick 3D scene here")
    mixer = host.root.findChild(QObject, "mixer")
    mixer.setProperty("running", False)  # her first pose has not been written yet
    host.resize(200, 400)
    host.show()
    figure = host.root.findChild(QObject, "figure")
    for _ in range(20):
        if host.root.property("clipCount"):  # the model has loaded
            break
        QTest.qWait(50)
    if not host.root.property("clipCount"):
        pytest.skip("the stand-in model did not load here")
    QTest.qWait(300)
    assert figure.property("visible") is False and not host.is_ready()
    mixer.setProperty("running", True)
    for _ in range(40):
        if host.is_ready():
            break
        QTest.qWait(100)
    if not host.is_ready():
        pytest.skip("no Quick 3D rendering here")
    assert figure.property("visible") is True
    host.close()


def test_her_view_has_its_camera_so_the_chest_strand_does_not_warn(tmp_path, monkeypatch) -> None:
    """mapFrom3DScene (the chest strand, each frame) warns every call without the view's camera."""
    from PySide6.QtQml import QQmlEngine, QQmlExpression

    host = _ready_host(tmp_path, monkeypatch)
    view = host.root.findChild(QObject, "view")
    # QQuick3DCamera* has no Python converter: ask QML, on the loaded scene.
    expr = QQmlExpression(QQmlEngine.contextForObject(view), view, "camera !== null")
    has_camera, _undefined = expr.evaluate()
    host.close()
    assert has_camera is True


def test_filament_scales_her_down_with_her_soles_on_the_floor(tmp_path, monkeypatch) -> None:
    import math

    from arelis.ui.persona_stage import figure_scale

    assert abs(figure_scale("filament") - 0.85) < 1e-6 and figure_scale("sodium") == 1.0
    host = _ready_host(tmp_path, monkeypatch)
    root, cam = host.root, host.root.findChild(QObject, "cam")
    host.resize(400, 400)
    QTest.qWait(100)
    full = cam.property("camZ")
    root.setProperty("figureScale", figure_scale("filament"))
    QTest.qWait(100)
    # She draws 0.85 as tall (the camera backs off), and the frame bottom still meets her soles.
    assert abs(full / cam.property("camZ") - 0.85) < 1e-3
    half = math.tan(math.radians(cam.property("fieldOfView") / 2)) * cam.property("camZ")
    assert abs(cam.property("y") - cam.property("tilt") - half - root.property("soleY")) < 1e-3
    host.close()


def test_quit_with_a_frame_in_flight_never_waits_and_never_destroys_a_running_thread() -> None:
    """Quit or a theme switch during her cold first frame (a 10 s+ pipeline compile).

    dispose used to wait up to 5 s on the GUI thread, then let the app exit with the thread
    still in run(), which Qt aborts on. Now it returns at once, the thread finishes its frame
    and frees the rest, and at exit a thread still in a frame is pinned, not destroyed.
    """
    import threading
    import time

    from PySide6.QtCore import QCoreApplication
    from PySide6.QtQuick import QQuickRenderControl, QQuickWindow

    from arelis.ui import live_threads
    from arelis.ui.persona_face import qq3d_avatar

    QApplication.instance() or QApplication([])
    in_frame, release = threading.Event(), threading.Event()

    class Stuck(qq3d_avatar._RenderThread):
        def _loop(self) -> None:  # a frame that sits in its compile until released
            in_frame.set()
            release.wait(30)

        def _release(self) -> None:
            pass

    def started():
        control = QQuickRenderControl()
        t = Stuck(control, QQuickWindow(control))
        qq3d_avatar._LIVE.add(t)
        t.start()
        assert in_frame.wait(5)
        return t

    render = started()
    t0 = time.monotonic()
    render.dispose()  # what destroyed and aboutToQuit call
    assert time.monotonic() - t0 < 0.5
    assert render.isRunning() and any(p is render for p in live_threads._PARKED)
    release.set()
    assert render.wait(5000)
    for _ in range(20):
        QCoreApplication.processEvents()
        if render._control is None:
            break
        time.sleep(0.01)
    assert render._control is None and render not in qq3d_avatar._LIVE

    in_frame.clear()
    release.clear()
    render = started()
    t0 = time.monotonic()
    pinned = qq3d_avatar._drain_at_exit(0.2)  # the app is gone; the frame is not done
    assert time.monotonic() - t0 < 2.0 and pinned == [render]
    release.set()  # let the pinned thread end before the test process does
    assert render.wait(5000)


def test_her_scene_builds_without_the_app_event_filters(tmp_path, monkeypatch) -> None:
    """Her real model creates about 86,000 keyframes in one step, each sending ChildAdded through
    every Python app filter: seconds of frozen GUI thread on first load. They build lifted."""
    import shutil
    from pathlib import Path

    from arelis.ui import app_filters

    app = QApplication.instance() or QApplication([])
    d = _model(tmp_path, monkeypatch)
    qad = Path(__file__).parents[1] / "arelis/assets/qq3d/animations/cc_Base_Head_rotation_0.qad"
    shutil.copy(qad, d / "animations" / "head.qad")
    groups = "\n".join(
        '        KeyframeGroup { target: head; property: "rotation"; keyframeSource: "animations/head.qad" }'
        for _ in range(4)
    )
    (d / "Ellah_anim.qml").write_text(
        _STAND_IN.replace("Node {", "Node {\n    Node { id: head }", 1).replace(
            "running: false }]", f"running: false }}]\n{groups}", 1
        ),
        encoding="utf-8",
    )
    from arelis.ui.persona_face.qq3d_avatar import QQ3DAvatar, unavailable_reason

    if unavailable_reason():
        pytest.skip(unavailable_reason())
    seen = []

    class Count(QObject):
        def eventFilter(self, obj, event) -> bool:
            if event.type() == QEvent.Type.ChildAdded and type(obj) is QObject:
                seen.append(1)  # a keyframe added to its group (no Python type for either)
            return False

    counter = Count()
    app_filters.install(app, counter)
    try:
        host = QQ3DAvatar()
        host.resize(200, 400)
        host.show()
        for _ in range(60):
            if host.is_ready() or host._dead:
                break
            QTest.qWait(100)
        if not host.is_ready():
            pytest.skip("no Quick 3D rendering here")
        assert seen == []
        host.close()
    finally:
        app_filters.remove(app, counter)


def test_each_frame_reads_back_the_one_before_it_and_a_still_scene_settles(
    tmp_path, monkeypatch
) -> None:
    """A readback of the frame just drawn made endFrame wait on the GPU every frame (half rate
    with the model generating): the previous frame's copy is queued ahead of this frame's draw."""
    QApplication.instance() or QApplication([])
    _model(tmp_path, monkeypatch)
    from arelis.ui.persona_face.qq3d_avatar import QQ3DAvatar, unavailable_reason

    if unavailable_reason():
        pytest.skip(unavailable_reason())
    host = QQ3DAvatar()
    host.resize(200, 400)
    host.show()
    for _ in range(60):
        if host.is_ready() or host._dead:
            break
        QTest.qWait(100)
    if not host.is_ready():
        pytest.skip("no Quick 3D rendering here")
    render, order = host._render, []
    real_read, real_draw = render._queue_readback, render._calls["render"]
    monkeypatch.setattr(render, "_queue_readback", lambda: (order.append("read"), real_read())[1])
    render._calls["render"] = lambda: (order.append("draw"), real_draw())
    real_end = render._calls["endFrame"]
    render._calls["endFrame"] = lambda: (order.append("end"), real_end())
    for i in range(100):  # drive frames until two have been drawn (slow under a loaded box)
        host.set_level(0.2 + 0.05 * (i % 10))
        host._request()
        QTest.qWait(40)
        if order.count("draw") >= 2:
            break
    for _ in range(50):
        QTest.qWait(20)
        if render._drawn and host._image_seq == render._drawn and not render.busy:
            break
    frames = "".join(o[0] for o in order).split("e")  # r=read, d=draw, one string per frame
    drawn = [f for f in frames if "d" in f]
    assert "rd" in drawn and all(f in ("d", "rd") for f in drawn), frames  # never d then r
    assert host._image_seq == render._drawn > 1  # the last drawn frame lands once she is still
    host.close()
