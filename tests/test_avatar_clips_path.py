"""Her body clips sit beside the mesh unless ARELIS_AVATAR_CLIPS says otherwise."""

from __future__ import annotations


def test_clips_default_beside_the_mesh_and_env_overrides(tmp_path, monkeypatch) -> None:
    from arelis.ui.persona_face.web_avatar import clips_path

    monkeypatch.delenv("ARELIS_AVATAR_CLIPS", raising=False)
    monkeypatch.setenv("ARELIS_AVATAR_GLB", str(tmp_path / "m" / "ellah.glb"))
    assert clips_path() == tmp_path / "m" / "ellah-anim.glb"
    monkeypatch.setenv("ARELIS_AVATAR_CLIPS", str(tmp_path / "c.glb"))
    assert clips_path() == tmp_path / "c.glb"
