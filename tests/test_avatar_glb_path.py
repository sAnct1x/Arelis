"""A source checkout still finds the avatar model in the installed copy's folder."""

from __future__ import annotations

from arelis.ui.persona_face import web_avatar


def test_dev_copy_finds_the_model_under_localappdata(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(web_avatar.GLB_ENV, raising=False)
    monkeypatch.setattr(web_avatar, "user_data_dir", lambda: tmp_path / "repo")
    model = tmp_path / "local" / "Arelis" / "avatar" / "ellah.glb"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"glTF")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert web_avatar.glb_path() == model
