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
    from arelis.ui.persona_face.qq3d_avatar import pipeline_cache_path

    path = pipeline_cache_path()
    for _ in range(40):
        if path.exists() and path.stat().st_size:
            break
        host.view.update()
        QTest.qWait(50)
    saved = path.exists() and path.stat().st_size > 0
    host.close()
    assert saved


def test_her_frames_are_paced_by_the_screen_refresh_not_by_each_finished_frame(
    tmp_path, monkeypatch
) -> None:
    """Asked for frames nonstop, she draws one per refresh slot, not one as soon as the last lands."""
    import time

    from PySide6.QtCore import QTimer

    host = _ready_host(tmp_path, monkeypatch)
    host._render.interval_s = 0.05  # a 20 Hz screen, so the cadence is unmistakable
    QTest.qWait(200)
    frames: list[float] = []
    host._render.frame_ready.connect(lambda: frames.append(time.perf_counter()))
    nag = QTimer()
    nag.setInterval(1)
    nag.timeout.connect(host._request)  # a scene that changes every millisecond
    nag.start()
    QTest.qWait(1000)
    nag.stop()
    host.close()
    assert 10 <= len(frames) <= 24, f"{len(frames)} frames in 1 s at a 50 ms refresh"
