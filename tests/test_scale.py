"""Display scale: OS DPI first, optional zoom, window fits the desk."""

from __future__ import annotations

from pathlib import Path

import yaml

from arelis.ui.scale import (
    SCALE_DEFAULT,
    clamp_rect,
    clamp_scale,
    configure_display_scale,
    fit_size,
    nearest_scale_preset,
    scale_from_config,
    scale_preset_label,
)
from arelis.ui.theme import DEFAULT_THEME, theme_from_config


def test_shipped_theme_is_sodium() -> None:
    raw = yaml.safe_load(
        (Path("arelis/config/default.yaml")).read_text(encoding="utf-8")
    )
    assert raw["ui"]["theme"] == "sodium"
    assert raw["ui"]["scale"] == 1.0
    assert DEFAULT_THEME == "sodium"
    assert theme_from_config({}) == "sodium"
    assert theme_from_config({"ui": {}}) == "sodium"
    assert theme_from_config({"ui": {"theme": "filament"}}) == "filament"


def test_clamp_scale_stays_in_range() -> None:
    assert clamp_scale(1) == 1.0
    assert clamp_scale("1.25") == 1.25
    assert clamp_scale(0.1) == 0.75
    assert clamp_scale(9) == 2.0
    assert clamp_scale("nope") == SCALE_DEFAULT
    assert clamp_scale(None) == SCALE_DEFAULT
    assert nearest_scale_preset(1.2) == 1.25
    assert scale_preset_label(1.0) == "follow display"
    assert scale_preset_label(1.5) == "150%"


def test_scale_from_config_defaults_to_follow_display() -> None:
    assert scale_from_config(None) == 1.0
    assert scale_from_config({}) == 1.0
    assert scale_from_config({"ui": {"scale": 1.5}}) == 1.5


def test_configure_display_scale_leaves_os_dpi_alone(monkeypatch) -> None:
    env: dict[str, str] = {}
    assert configure_display_scale({"ui": {"scale": 1.0}}, env) == 1.0
    assert "QT_SCALE_FACTOR" not in env
    assert configure_display_scale({"ui": {"scale": 1.25}}, env) == 1.25
    assert env["QT_SCALE_FACTOR"] == "1.25"


def test_configure_display_scale_respects_existing_env() -> None:
    env = {"QT_SCALE_FACTOR": "2"}
    configure_display_scale({"ui": {"scale": 1.25}}, env)
    assert env["QT_SCALE_FACTOR"] == "2"


def test_fit_size_1080p_keeps_design() -> None:
    # 1920×1080 minus a taskbar is still larger than 1440×900.
    assert fit_size(1440, 900, 1920, 1040) == (1440, 900)


def test_fit_size_small_laptop_shrinks() -> None:
    w, h = fit_size(1440, 900, 1366, 728)
    assert w <= int(1366 * 0.92)
    assert h <= int(728 * 0.92)
    assert w < 1440
    assert h < 900


def test_fit_size_4k_at_150_is_already_logical() -> None:
    # 3840×2160 at 150% ≈ 2560×1440 logical. Do not grow to fill it.
    assert fit_size(1440, 900, 2560, 1400) == (1440, 900)


def test_fit_size_4k_at_100_still_opens_design_size() -> None:
    assert fit_size(1440, 900, 3840, 2160) == (1440, 900)


def test_clamp_rect_stays_on_overlapping_screen() -> None:
    screens = [(0, 0, 1920, 1040), (1920, 0, 1920, 1080)]
    x, y, w, h = clamp_rect(200, 80, 1440, 900, screens)
    assert (x, y, w, h) == (200, 80, 1440, 900)


def test_clamp_rect_recenters_when_monitor_is_gone() -> None:
    # Saved on a right-hand 4K that was unplugged.
    screens = [(0, 0, 1920, 1040)]
    x, y, w, h = clamp_rect(4000, 200, 1600, 1000, screens)
    assert w <= 1920
    assert h <= 1040
    assert 0 <= x <= 1920 - w
    assert 0 <= y <= 1040 - h


def test_settings_reads_interface_scale(qt_app) -> None:
    from arelis.ui.settings_dialog import SettingsDialog

    dlg = SettingsDialog(
        {
            "voice": {},
            "presence": {},
            "ui": {"scale": 1.25},
            "workspace": {
                "named_roots": [
                    {"name": "arelis", "path": str(Path.cwd()), "read_only": False}
                ]
            },
            "tools": {"sms": {"inbound": {"ingest": {}}}},
        }
    )
    try:
        assert dlg.ui_scale.currentData() == 1.25
        assert dlg.values()["ui"]["scale"] == 1.25
    finally:
        dlg.close()


def test_apply_settings_persists_scale(arelis_window, tmp_path, monkeypatch) -> None:
    from arelis.ui.settings_host import apply_settings

    local = tmp_path / "config.local.yaml"
    monkeypatch.setattr("arelis.config.LOCAL_CONFIG_PATH", local)
    window = arelis_window()
    apply_settings(window, {"ui": {"scale": 1.5}, "voice": {}, "presence": {}, "ui_prefs": {}})
    assert window.config["ui"]["scale"] == 1.5
    saved = yaml.safe_load(local.read_text(encoding="utf-8"))
    assert saved["ui"]["scale"] == 1.5


def test_clamp_rect_shrinks_to_smaller_desk() -> None:
    screens = [(0, 0, 1280, 720)]
    x, y, w, h = clamp_rect(-40, -20, 1600, 1000, screens)
    assert w <= int(1280 * 0.92)
    assert h <= int(720 * 0.92)
    assert x >= 0
    assert y >= 0
    assert x + w <= 1280
    assert y + h <= 720
