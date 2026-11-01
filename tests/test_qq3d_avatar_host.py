"""The Quick 3D avatar host: same API as the web host, chosen by ARELIS_AVATAR_ENGINE in Filament."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

# A stand-in for her private balsam model: one node and one clip timeline.
_STAND_IN = """import QtQuick
import QtQuick3D
import QtQuick.Timeline
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
    assert root.property("hub") is not None
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
