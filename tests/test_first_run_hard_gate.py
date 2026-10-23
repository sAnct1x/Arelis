"""First-run still asks for a workspace folder when main passes a config.

Model setup runs when no chat GGUF is on disk. These tests pin the workspace
glass, the wizard gate, and the upgrade path that keeps saved roots.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml


@pytest.fixture
def fresh_first_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Empty profile: the workspace prompt and model setup are both needed."""
    from arelis import onboarding, paths

    root = tmp_path / "state"
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(root))
    monkeypatch.setattr(
        "arelis.config.LOCAL_CONFIG_PATH", root / "data" / "config.local.yaml"
    )
    home = tmp_path / "home"
    (home / "Documents").mkdir(parents=True)
    monkeypatch.setattr(paths, "INSTALL_PARENT", tmp_path / "site-packages")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    assert onboarding.needs_prompt()
    from arelis.setup.state import needs_model_setup

    assert needs_model_setup()
    return home


def test_regression_prompts_run_when_config_was_given(
    fresh_first_run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mirror production main to run_ui(load_config()): both glasses are asked.

    Fail-before: after #337 this skipped the model glass because a config
    dict was passed and needs_model_setup always returned False.
    """
    from arelis.config import load_config
    from arelis.ui import launch as launch_mod

    called: list[str] = []

    def fake_workspace():
        called.append("workspace")
        return Path(fresh_first_run / "Documents" / "Arelis")

    def fake_model():
        called.append("model")
        return None

    monkeypatch.setattr(launch_mod, "prompt_for_workspace_root", fake_workspace)
    monkeypatch.setattr(launch_mod, "prompt_for_model_setup", fake_model)
    monkeypatch.setattr(launch_mod, "try_quiet_complete_model_setup", lambda: False)
    from arelis.setup import state as setup_state

    real_needs = setup_state.needs_model_setup

    def needs_once() -> bool:
        if "model" in called:
            return False
        return real_needs()

    monkeypatch.setattr(setup_state, "needs_model_setup", needs_once)
    monkeypatch.setattr(launch_mod, "needs_model_setup", needs_once)

    config = load_config()
    assert config is not None
    # Production entry: main always passes a config dict.
    out = launch_mod.apply_first_run_glass(config, config_was_given=True)
    assert "workspace" in called, "workspace glass skipped because config was given"
    assert "model" in called, "model glass skipped because no chat GGUF was found"
    assert out is not None


def test_upgrade_skips_folder_dialog_when_roots_already_saved(
    fresh_first_run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Marker missing + saved roots: write marker, keep names and read-only flags."""
    from arelis import onboarding
    from arelis.config import LOCAL_CONFIG_PATH, load_config
    from arelis.ui import first_run as first_run_mod
    from arelis.ui import launch as launch_mod

    notes = fresh_first_run / "Documents" / "notes"
    archive = fresh_first_run / "Documents" / "archive"
    notes.mkdir(parents=True)
    archive.mkdir(parents=True)
    roots = [
        {"name": "notes", "path": str(notes), "read_only": False},
        {"name": "archive", "path": str(archive), "read_only": True},
    ]
    LOCAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_CONFIG_PATH.write_text(
        yaml.safe_dump({"workspace": {"roots": roots}}, sort_keys=False),
        encoding="utf-8",
    )
    assert onboarding.needs_prompt()
    assert onboarding.local_workspace_roots() == roots

    dialog_calls: list[int] = []

    class BoomDialog:
        def __init__(self, *args, **kwargs) -> None:
            dialog_calls.append(1)
            raise AssertionError("folder dialog must not open when roots exist")

    monkeypatch.setattr(first_run_mod, "FirstRunDialog", BoomDialog)
    record = MagicMock(side_effect=AssertionError("record_choice must not run"))
    monkeypatch.setattr(onboarding, "record_choice", record)

    # Skip model glass for this folder-only check.
    monkeypatch.setattr(launch_mod, "try_quiet_complete_model_setup", lambda: True)
    monkeypatch.setattr(launch_mod, "needs_model_setup", lambda: False)
    monkeypatch.setattr(launch_mod, "first_run_blocks_main", lambda: False)

    before = yaml.safe_load(LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))
    out = launch_mod.apply_first_run_glass(load_config(), config_was_given=True)
    after = yaml.safe_load(LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))

    assert out is not None
    assert dialog_calls == []
    record.assert_not_called()
    assert after["workspace"]["roots"] == before["workspace"]["roots"] == roots
    assert onboarding.marker_path().is_file()
    marker = json.loads(onboarding.marker_path().read_text(encoding="utf-8"))
    assert marker["workspace_root"] == str(notes)
    assert not onboarding.needs_prompt()
