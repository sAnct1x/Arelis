"""Gate 1 on Atria: her look drew nothing and nothing said why.

The port baked absolute box paths (and, run on Windows, backslash paths that QML
string escapes mangle) into the look's LayerGeometry sources, so no geometry loaded.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication


def test_the_look_loads_its_geometry_from_wherever_its_folder_is(tmp_path) -> None:
    QApplication.instance() or QApplication([])
    from PySide6.QtQml import QQmlComponent, QQmlEngine

    from arelis.ui.persona_q3d import geometry, port

    scene = tmp_path / "moved" / port.SCENE_SUBDIR
    scene.mkdir(parents=True)
    np.zeros((3, 3), np.float32).tofile(scene / "g0_position.bin")
    np.zeros((3, 3), np.float32).tofile(tmp_path / "moved" / "g0_Jaw.bin")
    (tmp_path / "moved" / "morphs").mkdir()
    np.zeros((3, 3), np.float32).tofile(tmp_path / "moved" / "morphs" / "g0_Jaw.bin")
    qml = tmp_path / "moved" / "Look.qml"
    qml.write_text(
        "import QtQuick3D\nimport Arelis.PersonaQ3D\n"
        f'LayerGeometry {{ source: {port.geom_ref("g0")}; spec: "VERTEX=position"; '
        f'points: false; morphs: {port.morph_ref("g0", ["Jaw"])} }}\n',
        encoding="utf-8",
    )
    assert geometry.LayerGeometry  # registers the QML type
    engine = QQmlEngine()
    comp = QQmlComponent(engine, QUrl.fromLocalFile(str(qml)))
    geo = comp.create()
    assert geo is not None, comp.errorString()
    assert geo.vertexData().size() == 3 * 12


def test_missing_model_files_fail_loudly_and_say_so_on_her_veil(
    tmp_path, monkeypatch, caplog
) -> None:
    QApplication.instance() or QApplication([])
    from arelis.ui import theme_tokens
    from arelis.ui.persona_face import PersonaPanel, qq3d_avatar

    d = tmp_path / "qq3d"
    (d / "animations").mkdir(parents=True)
    (d / "animations" / "Idle.qad").write_bytes(b"x")
    gone = "/no-such-box/team/avatar-qq3d/scene/g0"  # baked on another machine
    (d / "Ellah_aether.qml").write_text(
        f'import QtQuick3D\nNode {{ Model {{ source: "meshes/body.mesh" }}\n'
        f'  property string g: "{gone}" }}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("ARELIS_AVATAR_QQ3D_DIR", str(d))
    monkeypatch.setenv("ARELIS_AVATAR_ENGINE", "qq3d")
    monkeypatch.setattr(theme_tokens, "active_theme", lambda: "filament")
    caplog.set_level("ERROR", logger="arelis.avatar")
    reason = qq3d_avatar.unavailable_reason()
    if reason and "QtQuick3D unavailable" in reason:
        pytest.skip(reason)
    assert reason and "model files missing (2)" in reason
    assert any(str(d / "meshes" / "body.mesh") in r.getMessage() for r in caplog.records)
    panel = PersonaPanel()
    assert panel.web is None
    assert panel.loading.message == "Her figure couldn't load on this PC."
