"""Window shell helpers and local config merge for Settings."""

from __future__ import annotations

from pathlib import Path

import yaml
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QSizePolicy, QWidget

from arelis.config import deep_merge, load_config, merge_local_config
from arelis.ui.window_resize import HTBOTTOM, HTLEFT, HTTOPLEFT, hit_test_resize


def test_window_resize_does_not_import_win32_ctypes_at_module_level() -> None:
    """Linux ctypes has no windll or wintypes.

    Importing them at the top of window_resize.py aborted pytest collection on
    every Ubuntu runner before a single test ran. The hit-test helpers this
    file exercises are platform-neutral; only the DWM / WS_THICKFRAME calls
    need the Win32 names, and those already return on anything but win32.
    """
    import ast

    src = Path("arelis/ui/window_resize.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "ctypes":
            names = {alias.name for alias in node.names}
            forbidden = names & {"windll", "wintypes"}
            assert not forbidden, (
                "window_resize.py imports Windows-only ctypes names at "
                f"module level: {sorted(forbidden)}"
            )


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
    prefs = values["ui_prefs"]
    assert prefs["away_rest"] is False
    assert prefs["away_rest_min"] == 45
    dlg.close()


def test_settings_allow_tab(qt_app) -> None:
    from arelis.ui.settings_dialog import SettingsDialog

    dlg = SettingsDialog(
        {
            "voice": {},
            "presence": {},
            "agent": {"confirm_browser": False, "confirm_send": True},
            "workspace": {
                "named_roots": [
                    {"name": "arelis", "path": str(Path.cwd()), "read_only": False}
                ]
            },
            "tools": {"sms": {"inbound": {"ingest": {}}}},
        },
        initial_tab="Allow",
    )
    try:
        assert dlg.tabs.tabText(dlg.tabs.currentIndex()) == "allow"
        assert dlg.confirm_browser.isChecked() is False
        assert dlg.confirm_send.isChecked() is True
        dlg._preset_allow_trust_local()
        values = dlg.values()["agent"]
        assert values["confirm_writes"] is False
        assert values["confirm_send"] is True
        dlg._preset_allow_everything()
        assert dlg.values()["agent"]["confirm_browser"] is True
    finally:
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


def test_title_bar_is_view_rooms_settings(qt_app) -> None:
    from arelis.ui.chrome import TitleBar

    bar = TitleBar()
    try:
        assert bar.view_btn.text() == "view"
        assert bar.rooms_btn.text() == "rooms"
        assert bar.settings_btn.text() == "settings"
        widgets = [
            bar.layout().itemAt(i).widget()
            for i in range(bar.layout().count())
            if bar.layout().itemAt(i).widget() is not None
        ]
        assert widgets.index(bar.view_btn) < widgets.index(bar.rooms_btn)
        assert widgets.index(bar.rooms_btn) < widgets.index(bar.settings_btn)
        assert hasattr(bar, "max_btn")
    finally:
        bar.close()


def test_every_dock_keeps_an_object_name() -> None:
    """No QSS targets these names, which makes them look deletable. They are not.

    QMainWindow.saveState() identifies docks by object name, and layout_store
    writes that state to ui_layout.ini. A dock without one is simply dropped
    from the saved layout, so it stops returning to where it was left — a
    failure that shows up a day later with nothing pointing back to the cause.
    """
    from pathlib import Path

    src = Path("arelis/ui/app.py").read_text(encoding="utf-8")
    for dock in (
        "ThinkingDock",
        "WorkspaceDock",
        "HistoryDock",
        "CameraDock",
    ):
        assert f'setObjectName("{dock}")' in src, (
            f"{dock} lost its object name; saved layouts will forget that dock"
        )
    assert 'setObjectName("CalendarDock")' not in src


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
        assert dlg.tabs.tabText(dlg.tabs.currentIndex()) == "notify"
        assert dlg.pair_qr.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Fixed
        assert dlg.pair_qr.hasScaledContents() is False
        assert dlg.pair_status.wordWrap() is True
    finally:
        dlg.close()
