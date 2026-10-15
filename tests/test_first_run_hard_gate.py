"""First-run model setup must run from the installer path, and hard-gate the window.

Production used to skip both glasses whenever main passed a config dict into
run_ui (always). These tests pin the gate, the incomplete-setup refuse, the
upgrade folder adopt, one-attempt model setup, and the silent-install exe check.
No real Ollama, no real installer download.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

_TAG = "qwen3.5:4b"


@pytest.fixture
def fresh_first_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Empty profile: workspace prompt and model setup both still needed."""
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
    """Mirror production main → run_ui(load_config()): both glasses must be asked.

    Fail-before: on main this skips solely because a config dict was passed.
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
    assert "model" in called, "model glass skipped because config was given"
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


def test_hard_gate_one_attempt_then_refuse(
    fresh_first_run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One incomplete close is enough: no loop, apply returns None."""
    from arelis.config import load_config
    from arelis.setup.state import needs_model_setup
    from arelis.ui import launch as launch_mod

    monkeypatch.setattr(launch_mod, "prompt_for_workspace_root", lambda: None)
    monkeypatch.setattr(launch_mod, "try_quiet_complete_model_setup", lambda: False)
    attempts: list[int] = []

    def incomplete_model():
        attempts.append(1)
        return None

    monkeypatch.setattr(launch_mod, "prompt_for_model_setup", incomplete_model)
    monkeypatch.setattr(launch_mod, "needs_model_setup", needs_model_setup)

    config = load_config()
    out = launch_mod.apply_first_run_glass(config, config_was_given=True)
    assert out is None
    assert len(attempts) == 1
    assert needs_model_setup()


def test_quiet_skip_when_engine_has_shipped_default(
    fresh_first_run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Engine answering + shipped default already local → no wizard, marker set."""
    from arelis.setup import state as setup_state
    from arelis.setup.state import needs_model_setup, shipped_fast_tag
    from arelis.ui import launch as launch_mod

    tag = shipped_fast_tag()
    assert tag
    monkeypatch.setattr(launch_mod, "prompt_for_workspace_root", lambda: None)
    monkeypatch.setattr(
        "arelis.setup.engine.ollama_reachable", lambda *_a, **_k: True
    )
    monkeypatch.setattr(
        "arelis.setup.engine.already_pulled", lambda name, *_a, **_k: name == tag
    )
    opened: list[int] = []
    monkeypatch.setattr(
        launch_mod,
        "prompt_for_model_setup",
        lambda: opened.append(1) or (_ for _ in ()).throw(AssertionError("wizard")),
    )

    from arelis.config import load_config

    out = launch_mod.apply_first_run_glass(load_config(), config_was_given=True)
    assert out is not None
    assert opened == []
    assert not needs_model_setup()
    marker = setup_state._read_marker() or {}
    assert (marker.get("model_setup") or {}).get("complete") is True
    assert (marker.get("model_setup") or {}).get("tag") == tag


