"""Her body clips sit beside the mesh unless ARELIS_AVATAR_CLIPS says otherwise, and a missing file is an error."""

from __future__ import annotations

import logging


def test_clips_default_beside_the_mesh_and_env_overrides(tmp_path, monkeypatch) -> None:
    from arelis.ui.persona_face.web_avatar import clips_path

    monkeypatch.delenv("ARELIS_AVATAR_CLIPS", raising=False)
    monkeypatch.setenv("ARELIS_AVATAR_GLB", str(tmp_path / "m" / "ellah.glb"))
    assert clips_path() == tmp_path / "m" / "ellah-anim.glb"
    monkeypatch.setenv("ARELIS_AVATAR_CLIPS", str(tmp_path / "c.glb"))
    assert clips_path() == tmp_path / "c.glb"


def test_missing_clips_log_an_error_naming_the_path(tmp_path, monkeypatch, caplog) -> None:
    from arelis.ui.persona_face.web_avatar import check_clips

    missing = tmp_path / "ellah-anim.glb"
    monkeypatch.setenv("ARELIS_AVATAR_CLIPS", str(missing))
    caplog.set_level(logging.INFO, logger="arelis.avatar")
    assert check_clips() is False
    assert [(r.levelno, r.getMessage()) for r in caplog.records] == [
        (logging.ERROR, f"[avatar] clips missing at {missing}")
    ]
    missing.write_bytes(b"glTF")
    caplog.clear()
    assert check_clips() is True
    assert not caplog.records
