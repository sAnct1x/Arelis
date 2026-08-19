"""Model setup is skipped once a brain is pinned, and records both chips."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from arelis import onboarding, paths
from arelis.setup import state as setup_state


@pytest.fixture
def fresh_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "state"
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(root))
    monkeypatch.setattr(
        "arelis.config.LOCAL_CONFIG_PATH", root / "data" / "config.local.yaml"
    )
    monkeypatch.setattr(setup_state, "LOCAL_CONFIG_PATH", root / "data" / "config.local.yaml")
    home = tmp_path / "home"
    (home / "Documents").mkdir(parents=True)
    monkeypatch.setattr(paths, "INSTALL_PARENT", tmp_path / "site-packages")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    return root


def test_a_stranger_is_asked_about_a_model(fresh_install: Path) -> None:
    onboarding.record_choice(None)
    assert setup_state.needs_model_setup()


def test_pinning_a_tag_is_one_model_on_both_chips(fresh_install: Path) -> None:
    onboarding.record_choice(None)
    setup_state.record_model_choice("qwen3.5:9b")
    local = yaml.safe_load(
        (fresh_install / "data" / "config.local.yaml").read_text(encoding="utf-8")
    )
    assert local["models"]["fast"] == "qwen3.5:9b"
    assert local["models"]["research"] == "qwen3.5:9b"
    assert not setup_state.needs_model_setup()


def test_an_existing_local_pin_is_not_a_new_user(fresh_install: Path) -> None:
    from arelis.config import merge_local_config

    onboarding.record_choice(None)
    merge_local_config({"models": {"fast": "qwen3.5:9b", "research": "qwen3.5:9b"}})
    assert not setup_state.needs_model_setup()


def test_rewriting_the_folder_keeps_the_brain_choice(fresh_install: Path) -> None:
    """Workspace consent and model setup share first-run.json. Merge, do not clobber."""
    onboarding.record_choice(None)
    setup_state.record_model_choice("qwen3.5:9b")
    onboarding.record_choice(None)
    marker = json.loads(onboarding.marker_path().read_text(encoding="utf-8"))
    assert marker["model_setup"]["complete"] is True
    assert marker["model_setup"]["tag"] == "qwen3.5:9b"
    assert not setup_state.needs_model_setup()
