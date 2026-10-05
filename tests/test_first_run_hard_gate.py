"""First-run model setup must run from the installer path, and hard-gate the window.

Production used to skip both glasses whenever main passed a config dict into
run_ui (always). These tests pin the gate, the incomplete-setup refuse, and the
silent-install exe check. No real Ollama, no real installer download.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from arelis.setup.catalog import EMBED_TAG
from arelis.ui.setup_wizard import _PrepareWorker

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
    # Stay needing model setup so the hard-gate loop would re-ask; stop after
    # one incomplete answer by flipping the need off for the refuse path test
    # companion. Here we only care that both prompts were invoked once config
    # was given, so make model setup report done after the first ask.
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


def test_hard_gate_incomplete_blocks_main(
    fresh_first_run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the model dialog returns without a complete marker, main stays blocked."""
    from arelis.setup.state import needs_model_setup
    from arelis.ui import launch as launch_mod
    from arelis.ui import setup_wizard as wizard

    class FakeDialog:
        _picked = type("M", (), {"tag": _TAG})()

        def exec(self) -> int:
            return 0

    monkeypatch.setattr(wizard, "ModelSetupDialog", lambda parent=None: FakeDialog())
    assert needs_model_setup()
    assert wizard.prompt_for_model_setup() is None
    assert needs_model_setup()
    assert launch_mod.first_run_blocks_main()


def test_hard_gate_loops_until_model_ready(
    fresh_first_run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Incomplete closes re-open the model glass until prepare succeeds."""
    from arelis.config import load_config
    from arelis.setup.state import needs_model_setup, record_model_choice
    from arelis.ui import launch as launch_mod

    monkeypatch.setattr(launch_mod, "prompt_for_workspace_root", lambda: None)
    attempts: list[int] = []

    def flaky_model():
        attempts.append(1)
        if len(attempts) < 2:
            return None
        record_model_choice(_TAG)
        return _TAG

    monkeypatch.setattr(launch_mod, "prompt_for_model_setup", flaky_model)
    monkeypatch.setattr(launch_mod, "needs_model_setup", needs_model_setup)
    monkeypatch.setattr(
        "arelis.setup.state._window_for_tag",
        lambda tag: 0,
    )

    config = load_config()
    out = launch_mod.apply_first_run_glass(config, config_was_given=True)
    assert out is not None
    assert len(attempts) == 2
    assert not needs_model_setup()


def test_prompt_for_model_setup_returns_none_when_incomplete(
    fresh_first_run: Path, monkeypatch: pytest.MonkeyPatch, qt_app
) -> None:
    """Closing without prepare success must not return a tag."""
    from arelis.setup.state import needs_model_setup
    from arelis.ui import setup_wizard as wizard

    class FakeDialog:
        _picked = type("M", (), {"tag": _TAG})()

        def exec(self) -> int:
            return 0  # rejected

    monkeypatch.setattr(wizard, "ModelSetupDialog", lambda parent=None: FakeDialog())
    assert needs_model_setup()
    assert wizard.prompt_for_model_setup() is None
    assert needs_model_setup()


def test_silent_install_without_exe_fails_before_pull(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, qt_app
) -> None:
    """Exit code 0 is not enough: ollama.exe must exist before pull."""
    import arelis.ui.setup_wizard as wizard
    from arelis.setup.plain_errors import PLAIN

    pull = MagicMock()
    find_calls = {"n": 0}

    def find_exe():
        find_calls["n"] += 1
        # First call triggers download path; after "successful" install still missing.
        return None

    monkeypatch.setattr(wizard, "ollama_reachable", lambda: False)
    monkeypatch.setattr(wizard, "find_ollama_exe", find_exe)
    monkeypatch.setattr(wizard, "download_ollama_setup", MagicMock())
    monkeypatch.setattr(wizard, "run_ollama_setup", MagicMock(return_value=None))
    monkeypatch.setattr(wizard, "start_ollama", MagicMock(return_value=None))
    monkeypatch.setattr(wizard, "already_pulled", lambda tag: False)
    monkeypatch.setattr(wizard, "pull_tag", pull)
    monkeypatch.setattr(wizard, "runtime_dir", lambda: tmp_path)

    failed: list[str] = []
    ok: list[bool] = []
    worker = _PrepareWorker(_TAG)
    worker.failed.connect(failed.append)
    worker.finished_ok.connect(lambda: ok.append(True))
    worker.run()

    assert ok == []
    assert len(failed) == 1
    assert failed[0] == PLAIN["installer"]
    pull.assert_not_called()
    assert EMBED_TAG  # imported for parity with setup_worker tests


def test_run_ollama_setup_requires_exe_after_silent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    from arelis.setup.engine import run_ollama_setup

    setup = tmp_path / "OllamaSetup.exe"
    setup.write_bytes(b"setup")
    monkeypatch.setattr(
        "arelis.setup.engine.hidden_run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr("arelis.setup.engine.find_ollama_exe", lambda: None)
    problem = run_ollama_setup(setup)
    assert problem is not None
    assert "not found" in problem.lower()

    exe = tmp_path / "ollama.exe"
    exe.write_bytes(b"x")
    monkeypatch.setattr("arelis.setup.engine.find_ollama_exe", lambda: exe)
    assert run_ollama_setup(setup) is None
