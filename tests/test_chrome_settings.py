"""Window shell helpers and local config merge for Settings."""

from __future__ import annotations

from pathlib import Path

import yaml

from arelis.config import merge_local_config


def test_merge_local_config_roundtrip(tmp_path: Path, monkeypatch) -> None:
    local = tmp_path / "config.local.yaml"
    monkeypatch.setattr("arelis.config.LOCAL_CONFIG_PATH", local)
    merge_local_config({"voice": {"input_device": "Mic A", "output_volume": 0.5}}, path=local)
    merge_local_config({"voice": {"output_device": "Speakers"}}, path=local)
    data = yaml.safe_load(local.read_text(encoding="utf-8"))
    assert data["voice"]["input_device"] == "Mic A"
    assert data["voice"]["output_volume"] == 0.5
    assert data["voice"]["output_device"] == "Speakers"


def test_recent_workspace_files_roundtrip(tmp_path: Path, monkeypatch) -> None:
    from arelis.ui.layout_store import load_recent_workspace_files, push_recent_workspace_file

    ini = tmp_path / "ui_layout.ini"
    monkeypatch.setattr("arelis.ui.layout_store._settings_path", lambda: ini)
    assert load_recent_workspace_files() == []
    push_recent_workspace_file("arelis:README.md")
    push_recent_workspace_file("interferometer:notes.txt")
    push_recent_workspace_file("arelis:README.md")
    assert load_recent_workspace_files()[:2] == [
        "arelis:README.md",
        "interferometer:notes.txt",
    ]


def test_away_rest_prefs_roundtrip(tmp_path: Path, monkeypatch) -> None:
    from arelis.ui.layout_store import (
        clamp_away_rest_min,
        load_ui_prefs,
        save_ui_prefs,
    )

    ini = tmp_path / "ui_layout.ini"
    monkeypatch.setattr("arelis.ui.layout_store._settings_path", lambda: ini)
    assert clamp_away_rest_min(40) == 45
    assert clamp_away_rest_min("60") == 60
    save_ui_prefs(away_rest=True, away_rest_min=30, world_reach=1.8)
    prefs = load_ui_prefs()
    assert prefs["away_rest"] is True
    assert prefs["away_rest_min"] == 30
    assert abs(prefs["world_reach"] - 1.8) < 1e-9


def _settle_caption(bar, qt_app) -> None:
    from PySide6.QtCore import QAbstractAnimation

    if bar._caption_hide_timer.isActive():
        bar._caption_hide_timer.stop()
        bar._hide_caption_if_idle()
    anim = bar._caption_anim
    if anim.state() == QAbstractAnimation.State.Running:
        anim.setCurrentTime(max(anim.duration(), 0))
    qt_app.processEvents()


def test_theme_persists_in_local_config(tmp_path: Path, monkeypatch) -> None:
    from arelis.ui.theme import apply_theme

    local = tmp_path / "config.local.yaml"
    monkeypatch.setattr("arelis.config.LOCAL_CONFIG_PATH", local)
    merge_local_config({"ui": {"theme": "sodium"}}, path=local)
    data = yaml.safe_load(local.read_text(encoding="utf-8"))
    assert data["ui"]["theme"] == "sodium"
    apply_theme("sodium")


