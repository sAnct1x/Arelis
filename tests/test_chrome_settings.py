"""Window shell helpers and local config merge for Settings."""

from __future__ import annotations

from pathlib import Path

import yaml
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QWidget

from arelis.config import deep_merge, load_config, merge_local_config
from arelis.ui.window_resize import HTBOTTOM, HTLEFT, HTTOPLEFT, hit_test_resize


def test_deep_merge_nested() -> None:
    base = {"voice": {"enabled": True, "stt": {"enabled": True}}, "a": 1}
    deep_merge(base, {"voice": {"input_device": "Headset", "stt": {"enabled": False}}})
    assert base["a"] == 1
    assert base["voice"]["enabled"] is True
    assert base["voice"]["input_device"] == "Headset"
    assert base["voice"]["stt"]["enabled"] is False


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
    monkeypatch.setattr(
        "arelis.ui.layout_store._settings_path", lambda: ini
    )
    assert load_recent_workspace_files() == []
    push_recent_workspace_file("arelis:README.md")
    push_recent_workspace_file("interferometer:notes.txt")
    push_recent_workspace_file("arelis:README.md")
    assert load_recent_workspace_files()[:2] == [
        "arelis:README.md",
        "interferometer:notes.txt",
    ]


def test_settings_roots_values(qt_app) -> None:
    from arelis.ui.settings_dialog import SettingsDialog

    dlg = SettingsDialog(
        {
            "voice": {},
            "presence": {},
            "workspace": {
                "named_roots": [
                    {"name": "arelis", "path": str(Path.cwd()), "read_only": False},
                    {
                        "name": "docs",
                        "path": str(Path.cwd()),
                        "read_only": True,
                    },
                ]
            },
            "tools": {"sms": {"inbound": {"ingest": {}}}},
        }
    )
    values = dlg.values()
    roots = values["workspace"]["roots"]
    assert roots[0]["name"] == "arelis"
    assert roots[1]["read_only"] is True
    channels = values["ui"]["notifications"]["channels"]
    assert channels["sms"] == "voice"
    assert channels["calendar"] == "visual"
    dlg.close()


def test_load_config_merges_local(tmp_path: Path, monkeypatch) -> None:
    default = tmp_path / "default.yaml"
    default.write_text(
        "voice:\n  enabled: true\n  input_device: ''\n"
        "workspace:\n  roots: ['.']\n"
        "location:\n  enabled: false\n",
        encoding="utf-8",
    )
    local = tmp_path / "config.local.yaml"
    local.write_text("voice:\n  input_device: Logitech\n", encoding="utf-8")
    monkeypatch.setattr("arelis.config.DEFAULT_CONFIG_PATH", default)
    monkeypatch.setattr("arelis.config.LOCAL_CONFIG_PATH", local)
    monkeypatch.setattr("arelis.config.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("arelis.config.PACKAGE_ROOT", tmp_path)
    cfg = load_config()
    assert cfg["voice"]["input_device"] == "Logitech"
    assert cfg["voice"]["enabled"] is True


def test_hit_test_resize_corners(qt_app) -> None:
    w = QWidget()
    w.setGeometry(100, 100, 400, 300)
    w.show()
    qt_app.processEvents()

    from arelis.ui.window_resize import hit_test_resize_at

    geo = w.frameGeometry()
    try:
        assert (
            hit_test_resize_at(w, geo.left() + 2, geo.top() + 2) == HTTOPLEFT
        )
        assert (
            hit_test_resize_at(w, geo.left() + 2, geo.center().y()) == HTLEFT
        )
        assert (
            hit_test_resize_at(w, geo.center().x(), geo.bottom() - 2) == HTBOTTOM
        )
        assert hit_test_resize_at(w, geo.center().x(), geo.center().y()) is None
        # Cursor-based helper still works.
        from arelis.ui import window_resize as wr

        original = wr.QCursor.pos
        try:
            wr.QCursor.pos = staticmethod(
                lambda: QPoint(geo.left() + 2, geo.center().y())
            )
            assert hit_test_resize(w) == HTLEFT
        finally:
            wr.QCursor.pos = original
    finally:
        w.close()


def test_title_bar_has_settings(qt_app) -> None:
    from arelis.ui.chrome import TitleBar

    bar = TitleBar()
    assert bar.settings_btn.text() == "settings"
    assert hasattr(bar, "max_btn")
    bar.close()


def test_view_menu_omits_settings() -> None:
    """Settings is title-bar only — View must not duplicate it."""
    from pathlib import Path

    src = Path("arelis/ui/app.py").read_text(encoding="utf-8")
    start = src.index("def _show_view_menu")
    end = src.index("\n    def ", start + 1)
    body = src[start:end]
    assert "act_thinking" in body
    assert "act_settings" not in body
    assert "menu.addAction(self.act_settings)" not in body
    # Ctrl+, wiring stays on the window action list.
    assert 'QAction("settings…"' in src or "settings…" in src


def test_settings_opens_notify_tab(qt_app) -> None:
    from arelis.ui.settings_dialog import SettingsDialog

    dlg = SettingsDialog(
        {
            "voice": {},
            "presence": {},
            "workspace": {
                "named_roots": [
                    {"name": "arelis", "path": str(Path.cwd()), "read_only": False}
                ]
            },
            "tools": {"sms": {"inbound": {"ingest": {}}}},
        },
        initial_tab="Notify",
    )
    try:
        assert dlg.tabs.tabText(dlg.tabs.currentIndex()) == "Notify"
    finally:
        dlg.close()
