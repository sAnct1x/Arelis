"""A wipe must take published leftovers and refuse a checkout."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis import paths
from arelis import uninstall as wipe


def test_residue_is_empty_on_a_checkout() -> None:
    assert paths.is_source_checkout()
    assert wipe.residue_dirs() == []


def test_looks_like_source_tree_needs_both_markers(tmp_path: Path) -> None:
    clone = tmp_path / "Arelis"
    clone.mkdir()
    (clone / "pyproject.toml").write_text("[project]\nname = 'arelis'\n", encoding="utf-8")
    assert not wipe.looks_like_source_tree(clone)
    (clone / "tests").mkdir()
    assert wipe.looks_like_source_tree(clone)


def test_residue_skips_a_documents_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    local = tmp_path / "Local"
    local.mkdir()
    docs = tmp_path / "Documents" / "Arelis"
    docs.mkdir(parents=True)
    (docs / "pyproject.toml").write_text("[project]\nname = 'arelis'\n", encoding="utf-8")
    (docs / "tests").mkdir()
    profile = local / "Arelis"
    profile.mkdir()
    runtime = local / "Arelis-runtime"
    runtime.mkdir()
    sandbox = local / "Arelis-dev"
    sandbox.mkdir()

    monkeypatch.setattr(wipe, "is_source_checkout", lambda: False)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    monkeypatch.setattr(wipe, "user_data_dir", lambda: profile)
    monkeypatch.setattr(wipe, "default_workspace_root", lambda: docs)

    leftover = set(wipe.residue_dirs())
    assert profile.resolve() in leftover
    assert runtime.resolve() in leftover
    assert sandbox.resolve() in leftover
    assert docs.resolve() not in leftover


def test_purge_on_a_checkout_only_touches_tasks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    doomed = tmp_path / "must-survive"
    doomed.mkdir()
    (doomed / "keep.txt").write_text("x", encoding="utf-8")

    monkeypatch.setattr(wipe, "residue_dirs", lambda: [doomed])
    monkeypatch.setattr(
        "arelis.jobs.schedule.remove_all_tasks", lambda: ["news"]
    )

    assert paths.is_source_checkout()
    gone = wipe.purge_user_state()
    assert gone == ["task:news"]
    assert (doomed / "keep.txt").is_file()


def test_purge_removes_published_dirs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gone_dir = tmp_path / "Arelis"
    gone_dir.mkdir()
    (gone_dir / "secrets.yaml").write_text("x", encoding="utf-8")

    monkeypatch.setattr(wipe, "is_source_checkout", lambda: False)
    monkeypatch.setattr(wipe, "residue_dirs", lambda: [gone_dir])
    monkeypatch.setattr("arelis.jobs.schedule.remove_all_tasks", lambda: [])

    gone = wipe.purge_user_state()
    assert str(gone_dir) in gone
    assert not gone_dir.exists()


def test_purge_flag_runs_before_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from arelis import main as entry

    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "state"))

    def refuse(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the configuration must not be read to wipe data")

    monkeypatch.setattr(entry, "load_config", refuse)
    monkeypatch.setattr(wipe, "purge_user_state", lambda: [r"C:\gone"])
    monkeypatch.setattr("arelis.uninstall.purge_user_state", lambda: [r"C:\gone"])

    assert entry.main(["--purge-user-data"]) == 0
