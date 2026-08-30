"""World stage is a source checkout. Installer copies do not offer it."""

from __future__ import annotations

from arelis.spatial.grant import grant_for, world_stage_allowed
from arelis.ui.world_host import should_offer_world, world_available


def test_installer_extra_does_not_list_rebound_or_spatial() -> None:
    import tomllib
    from pathlib import Path

    data = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    extras = data["project"]["optional-dependencies"]
    installer = extras["installer"]
    joined = " ".join(installer).lower()
    assert "rebound" not in joined
    assert "spatial" not in joined
    assert "mediapipe" not in joined
    assert "astro" in extras
    assert any("rebound" in str(x).lower() for x in extras["astro"])


def test_checkout_may_offer_the_stage() -> None:
    assert world_stage_allowed() is True
    assert world_available() is True
    assert should_offer_world("physics") is True
    assert should_offer_world("lab") is False
    assert should_offer_world(None) is False
    assert grant_for("physics", True).allowed is True


def test_install_root_hides_the_stage(monkeypatch) -> None:
    from pathlib import Path

    import arelis.spatial.grant as grant
    import arelis.update as update

    monkeypatch.setattr(update, "install_root", lambda: Path("C:/installed"))
    assert grant.world_stage_allowed() is False
    assert world_available() is False
    assert should_offer_world("physics") is False
    assert grant.grant_for("physics", True).allowed is False


def test_a_wheel_without_tests_hides_the_stage(monkeypatch) -> None:
    import arelis.spatial.grant as grant
    import arelis.update as update

    monkeypatch.setattr(update, "install_root", lambda: None)
    monkeypatch.setattr(grant, "is_source_checkout", lambda: False)
    assert grant.world_stage_allowed() is False
    assert world_available() is False
    assert should_offer_world("physics") is False
