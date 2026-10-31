"""#261: a source checkout reinstalls its dependencies when pyproject.toml changes."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from arelis import dev_sync
from arelis import main as main_mod


def test_a_changed_pyproject_syncs_once_and_a_failed_sync_retries(tmp_path, monkeypatch) -> None:
    repo, venv = tmp_path / "repo", tmp_path / "venv"
    repo.mkdir()
    venv.mkdir()
    (repo / "pyproject.toml").write_text('dependencies = ["a"]\n', encoding="utf-8")
    monkeypatch.setattr(dev_sync, "INSTALL_PARENT", repo)
    monkeypatch.setattr(dev_sync, "is_source_checkout", lambda: True)
    monkeypatch.setattr(sys, "prefix", str(venv))
    calls: list[list[str]] = []
    code = [1]

    def run(cmd, **_kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=code[0], stderr="no network")

    assert dev_sync.sync_checkout_deps(run) is False  # failed, so no stamp
    code[0] = 0
    assert dev_sync.sync_checkout_deps(run) is True
    assert dev_sync.sync_checkout_deps(run) is False  # unchanged: no install
    (repo / "pyproject.toml").write_text('dependencies = ["a", "b"]\n', encoding="utf-8")
    assert dev_sync.sync_checkout_deps(run) is True
    assert len(calls) == 3
    assert calls[-1][-4:] == ["install", "-q", "-e", str(repo)]

    # Launching the window is what runs it.
    class LaunchedError(Exception):
        pass

    def stop():
        raise LaunchedError

    monkeypatch.setattr(dev_sync, "sync_checkout_deps", stop)
    monkeypatch.setattr(main_mod, "load_config", lambda *a, **k: {})
    monkeypatch.setattr(main_mod, "configure_logging", lambda: None)
    monkeypatch.setattr(main_mod, "install_unhandled_hook", lambda: None)
    monkeypatch.setattr("arelis.hidden_proc.install_hidden_subprocess", lambda: None)
    monkeypatch.setattr("arelis.ui.app.run_ui", lambda *a, **k: 0)
    with pytest.raises(LaunchedError):
        main_mod.main([])
