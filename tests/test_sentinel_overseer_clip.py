"""Near-plane regression; no native window, screenshot, or CI helper mutation."""

from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine


def test_overseer_close_subject_is_in_front_of_camera_near_plane(qt_app):
    qml = (
        Path(__file__).resolve().parents[1]
        / "arelis/assets/sentinel/overseer/OverseerView.qml"
    )
    engine = QQmlEngine()
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(qml)))
    assert component.status() == QQmlComponent.Status.Ready, component.errors()
    root = component.create()
    assert root is not None, component.errors()
    root.setParent(engine)
    camera = next(
        node for node in root.findChildren(QObject)
        if "PerspectiveCamera" in node.metaObject().className()
    )
    # The nearest approved dolly point is still 6 m, not a narrower FOV
    # or a moved target. Qt's implicit near plane of 10 m excludes it.
    root.setProperty("cameraDistance", 6.0)
    root.setProperty("cameraPitch", 22.0)
    assert camera.property("clipNear") == 1.0
    assert camera.property("clipNear") < root.property("cameraDistance")
    assert camera.property("fieldOfView") == 35.0
    assert camera.property("clipFar") == 10000.0
