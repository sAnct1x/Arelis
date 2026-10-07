"""Mail and texts stay on the asking side of the readiness strip."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.config import load_config
from arelis.presence.readiness import ReadinessSnapshot, _confirm_chip
from arelis.ui.readiness_strip import ReadinessStrip


def test_strip_reports_mail_and_texts_asking_when_settings_say_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qt_app
) -> None:
    local = tmp_path / "config.local.yaml"
    local.write_text(
        "agent:\n  confirm_send: false\nlocation:\n  enabled: false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("arelis.config.LOCAL_CONFIG_PATH", local)
    cfg = load_config()
    assert cfg["agent"]["confirm_send"] is False

    chip = _confirm_chip(cfg)
    assert chip.key == "confirm"
    on, marker, off = chip.detail.partition(". Off:")
    assert "send" in on
    assert marker == "" or "send" not in off

    strip = ReadinessStrip()
    strip.apply(ReadinessSnapshot(chips=(chip,)))
    rows = [action.text() for action in strip._systems_menu.actions()]
    joined = "\n".join(rows)
    assert chip.detail in joined
    assert "send" in joined
