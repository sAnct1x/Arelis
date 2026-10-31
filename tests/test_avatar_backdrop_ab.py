"""ARELIS_AVATAR_BACKDROP=opaque paints her page with the room colour (blank-frame A/B)."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication


def test_opaque_backdrop_arm_paints_her_page_with_the_room_colour(tmp_path, monkeypatch) -> None:
    glb = tmp_path / "ellah.glb"
    glb.write_bytes(b"glTF")
    monkeypatch.setenv("ARELIS_AVATAR_GLB", str(glb))
    QApplication.instance() or QApplication([])
    from arelis.ui import idle_ab
    from arelis.ui.persona_face.web_avatar import WebAvatar
    from arelis.ui.theme import color

    idle_ab.load({"ARELIS_AVATAR_BACKDROP": "opaque"})
    try:
        web = WebAvatar()
        bg = web.view.page().backgroundColor()
        assert bg.alpha() == 255 and bg.rgb() == color("bg0").rgb()
        assert "backdrop=opaque" in idle_ab.line()
        web.deleteLater()
    finally:
        idle_ab.load({})
