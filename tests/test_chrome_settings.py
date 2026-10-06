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


def test_recent_workspace_files_drop_junk_and_missing(tmp_path: Path, monkeypatch) -> None:
    from arelis.ui.layout_store import load_recent_workspace_files, settings

    ini = tmp_path / "ui_layout.ini"
    monkeypatch.setattr("arelis.ui.layout_store._settings_path", lambda: ini)
    alive = tmp_path / "kept.md"
    alive.write_text("ok", encoding="utf-8")
    ghost = tmp_path / "gone.md"
    cache = tmp_path / "tool_cache" / "scrape.txt"
    cache.parent.mkdir()
    cache.write_text("scraped", encoding="utf-8")
    s = settings()
    s.setValue(
        "recent_workspace_files",
        [str(alive), str(ghost), str(cache), "arelis:notes.md", "gone-note.md"],
    )
    s.sync()
    recent = load_recent_workspace_files()
    assert str(alive) in recent
    assert "arelis:notes.md" in recent
    assert str(ghost) not in recent
    assert str(cache) not in recent
    assert "gone-note.md" not in recent


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
        },
        list_models=lambda: [],
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
    assert values["ui"]["scale"] == 1.0
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
        list_models=lambda: [],
    )
    try:
        assert dlg.tabs.tabText(dlg.tabs.currentIndex()) == "allow"
        assert dlg.confirm_browser.isChecked() is False
        assert dlg.confirm_send.isChecked() is True
        assert dlg.ask_is_grant.isChecked() is True
        assert dlg.ask_is_grant.text() == "the ask is the grant"
        assert dlg._allow_local_h.text() == "On her own"
        assert dlg._allow_always_h.text() == "Even when you named it"
        assert "job you named" in dlg._allow_grant_blurb.text()
        assert dlg._allow_ask_all.text() == "ask me everything"
        assert dlg._allow_trust_local.text() == "never ask about local work"
        dlg.ask_is_grant.setChecked(False)
        assert dlg._allow_local_h.text() == "Pause every time"
        assert "even a job you named" in dlg._allow_grant_blurb.text()
        dlg._preset_allow_trust_local()
        values = dlg.values()["agent"]
        assert values["confirm_writes"] is False
        assert values["confirm_send"] is True
        assert values["confirm_run"] is True
        assert values["ask_is_grant"] is True
        assert dlg._allow_local_h.text() == "On her own"
        dlg._preset_allow_everything()
        everything = dlg.values()["agent"]
        assert everything["confirm_browser"] is True
        assert everything["ask_is_grant"] is False
        assert dlg._allow_local_h.text() == "Pause every time"
    finally:
        dlg.close()


def test_mail_and_texts_checkbox_is_locked(qt_app) -> None:
    from arelis.ui.settings_dialog import SettingsDialog

    dlg = SettingsDialog(
        {
            "voice": {},
            "presence": {},
            "agent": {"confirm_send": False},
            "workspace": {
                "named_roots": [
                    {"name": "arelis", "path": str(Path.cwd()), "read_only": False}
                ]
            },
            "tools": {"sms": {"inbound": {"ingest": {}}}},
        },
        initial_tab="Allow",
        list_models=lambda: [],
    )
    try:
        assert dlg.confirm_send.isChecked() is True
        assert dlg.confirm_send.isEnabled() is False
        tip = dlg.confirm_send.toolTip()
        assert "Every mail and text always asks." in tip
        assert "Filament (testing) is exempt." in tip
        assert "while it is under testing" not in tip
        writes_tip = dlg.confirm_writes.toolTip()
        assert "Deletes always pause." in writes_tip
        assert "when this is on" not in writes_tip
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
        assert widgets.index(bar.title) < widgets.index(bar.hands_btn)
        assert widgets.index(bar.hands_btn) < widgets.index(bar.view_btn)
        assert widgets.index(bar.view_btn) < widgets.index(bar.rooms_btn)
        assert widgets.index(bar.rooms_btn) < widgets.index(bar.settings_btn)
        assert widgets.index(bar.settings_btn) < widgets.index(bar.span_btns[1])
        assert bar.title.text() == "arelis"
        assert bar.hands_btn.text() == "hands"
        assert hasattr(bar, "max_btn")
        bar.set_slim(True)
        bar.set_hands_visible(True)
        bar.set_home_band(2560, 2560, 7680)
        assert bar._span_left.width() == 2560
        assert bar._span_right.width() == 2560
        bar.set_home_band(2560, 2560, 2560)
        assert bar._span_left.width() == 0
        bar.set_home_band(0, 0, 0)
        assert bar._span_left.width() == 0
        assert bar.view_btn.isHidden()
        assert not bar.hands_btn.isHidden()
        assert not bar.span_btns[1].isHidden()
        assert bar.height() == 32
        bar.set_span_choice(1)
        assert bar.span_btns[1].isChecked()
        bar.set_slim(False)
        assert not bar.view_btn.isHidden()
        assert bar.hands_btn.isHidden()
        assert bar.span_btns[1].isHidden()
        assert bar.height() == 40
    finally:
        bar.close()


def test_window_buttons_fade_in_when_the_cursor_is_near(qt_app) -> None:
    """Sodium and filament share TitleBar. The three buttons stay out until
    the pointer is in their corner, and they stay in the layout either way.
    """
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from arelis.ui import caption_fade as fade_mod
    from arelis.ui.chrome import TitleBar

    saved = (
        fade_mod._CAPTION_FADE_IN_MS,
        fade_mod._CAPTION_FADE_OUT_MS,
        fade_mod._CAPTION_HIDE_MS,
        fade_mod._CAPTION_POLL_MS,
    )
    fade_mod._CAPTION_FADE_IN_MS = 1
    fade_mod._CAPTION_FADE_OUT_MS = 1
    fade_mod._CAPTION_HIDE_MS = 5_000
    fade_mod._CAPTION_POLL_MS = 60_000
    cursor = {"at": QPoint(-4000, -4000)}
    original_pos = fade_mod.QCursor.pos
    fade_mod.QCursor.pos = staticmethod(lambda: cursor["at"])

    bar = TitleBar()
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(bar)
    host.resize(960, 80)
    try:
        host.show()
        qt_app.processEvents()
        assert bar._caption.width() > 40
        assert not bar.min_btn.isHidden()
        assert not bar.max_btn.isHidden()
        assert not bar.close_btn.isHidden()
        assert bar._caption_poll.isActive()
        assert bar._caption.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        origin = bar._caption.mapToGlobal(QPoint(0, bar._caption.height() // 2))
        cursor["at"] = QPoint(origin.x() - 40, origin.y())
        assert bar._cursor_near_caption()
        cursor["at"] = QPoint(origin.x() - 80, origin.y())
        assert not bar._cursor_near_caption()

        on_close = bar.close_btn.mapToGlobal(bar.close_btn.rect().center())
        cursor["at"] = on_close
        bar._drag_pos = QPoint(1, 1)
        assert not bar._cursor_near_caption()
        bar._drag_pos = None
        assert bar._cursor_near_caption()

        bar._sync_caption_hover()
        _settle_caption(bar, qt_app)
        assert bar._caption_opacity == 1.0
        assert not bar._caption.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        bar.set_slim(True)
        qt_app.processEvents()
        cursor["at"] = bar.close_btn.mapToGlobal(bar.close_btn.rect().center())
        bar._sync_caption_hover()
        _settle_caption(bar, qt_app)
        assert bar._caption_opacity == 1.0
        assert bar.height() == 32

        cursor["at"] = QPoint(-4000, -4000)
        bar.title.setFocus()
        assert not bar._caption_pinned()
        bar._sync_caption_hover()
        _settle_caption(bar, qt_app)
        assert bar._caption_opacity == 0.0
        assert bar._caption.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        bar.close_btn.set_strength(0.35)
        assert bar.close_btn._fade_buffer is not None
        assert not bar.close_btn._fade_buffer.isNull()
        bar.close_btn.repaint()
        bar.close_btn.set_strength(0.0)
        assert bar.close_btn._fade_buffer is None

        host.hide()
        qt_app.processEvents()
        assert not bar._caption_poll.isActive()
    finally:
        fade_mod.QCursor.pos = original_pos
        (
            fade_mod._CAPTION_FADE_IN_MS,
            fade_mod._CAPTION_FADE_OUT_MS,
            fade_mod._CAPTION_HIDE_MS,
            fade_mod._CAPTION_POLL_MS,
        ) = saved
        host.close()
        bar.close()


def test_plate_close_fades_until_the_cursor_is_near(qt_app) -> None:
    """A tile that only has a close still uses the same corner fade."""
    from PySide6.QtCore import QAbstractAnimation, QPoint, Qt
    from PySide6.QtWidgets import QHBoxLayout, QWidget

    from arelis.ui import caption_fade as fade_mod
    from arelis.ui.caption_fade import CaptionTool, watch_caption

    saved = (fade_mod._CAPTION_FADE_IN_MS, fade_mod._CAPTION_POLL_MS)
    fade_mod._CAPTION_FADE_IN_MS = 1
    fade_mod._CAPTION_POLL_MS = 60_000
    cursor = {"at": QPoint(-4000, -4000)}
    original_pos = fade_mod.QCursor.pos
    fade_mod.QCursor.pos = staticmethod(lambda: cursor["at"])
    host = QWidget()
    btn = CaptionTool()
    btn.setFixedSize(28, 28)
    lay = QHBoxLayout(host)
    lay.addStretch(1)
    lay.addWidget(btn)
    hover = watch_caption(host, btn)
    host.resize(420, 48)
    try:
        host.show()
        qt_app.processEvents()
        assert btn.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        assert hover.opacity == 0.0
        cursor["at"] = btn.mapToGlobal(btn.rect().center())
        hover.sync()
        if hover.anim.state() == QAbstractAnimation.State.Running:
            hover.anim.setCurrentTime(max(hover.anim.duration(), 0))
        qt_app.processEvents()
        assert hover.opacity == 1.0
        assert not btn.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    finally:
        fade_mod.QCursor.pos = original_pos
        fade_mod._CAPTION_FADE_IN_MS, fade_mod._CAPTION_POLL_MS = saved
        host.close()


def test_every_plate_watches_its_window_buttons() -> None:
    """Sodium tiles and the filament chat plate share the corner fade."""
    from pathlib import Path

    root = Path("arelis/ui")
    for name in (
        "chrome.py",
        "dialog.py",
        "settings_dialog.py",
        "contacts_inbox.py",
        "notify_inbox.py",
        "mail_peek.py",
        "sms_chat.py",
        "calendar_window.py",
        "world_window.py",
        "filament_field.py",
    ):
        text = (root / name).read_text(encoding="utf-8")
        assert "watch_caption(" in text, name


def _settle_caption(bar, qt_app) -> None:
    from PySide6.QtCore import QAbstractAnimation

    if bar._caption_hide_timer.isActive():
        bar._caption_hide_timer.stop()
        bar._hide_caption_if_idle()
    anim = bar._caption_anim
    if anim.state() == QAbstractAnimation.State.Running:
        anim.setCurrentTime(max(anim.duration(), 0))
    qt_app.processEvents()


def test_every_dock_keeps_an_object_name() -> None:
    """No QSS targets these names, which makes them look deletable. They are not.

    QMainWindow.saveState() identifies docks by object name, and layout_store
    writes that state to ui_layout.ini. A dock without one is simply dropped
    from the saved layout, so it stops returning to where it was left — a
    failure that shows up a day later with nothing pointing back to the cause.
    """
    from pathlib import Path

    src = Path("arelis/ui/window_build.py").read_text(encoding="utf-8")
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

    src = Path("arelis/ui/window_chrome.py").read_text(encoding="utf-8")
    start = src.index("def _show_view_menu")
    end = src.index("\n    def ", start + 1)
    body = src[start:end]
    assert "act_thinking" in body
    assert "act_settings" not in body
    assert "menu.addAction(self.act_settings)" not in body
    assert 'addMenu(tr("themes"))' in body
    assert 'addMenu(tr("Language"))' in body
    # Ctrl+, wiring stays on the window action list.
    assert 'QAction("settings…"' in src or "settings…" in src


def test_settings_has_no_theme_tab(qt_app) -> None:
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
        list_models=lambda: [],
    )
    try:
        labels = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
        assert labels == [
            "audio",
            "window",
            "allow",
            "notify",
            "folders",
            "memory",
        ]
        assert "theme" not in labels
        assert not hasattr(dlg, "theme_combo")
        assert "theme" not in dlg.values().get("ui", {})
        assert dlg.mail_address.placeholderText()
        assert dlg.mail_password.echoMode() != 0
        assert dlg.make_token_btn.text() == "Create a pairing code"
        assert dlg.install_blurb.text()
        assert "Gradle" not in dlg.install_blurb.text()
        assert dlg.companion_status.text()
        assert "Gradle" not in dlg.companion_status.text()
        assert dlg.fetch_gemma_btn.text() == "Download offline copy"
        assert dlg.pair_more.isHidden()
        assert "Apply" in dlg.stt_enabled.toolTip()
        assert "Apply" in dlg.tts_enabled.toolTip()
        assert "restart" not in dlg.stt_enabled.toolTip().lower()
        values = dlg.values()
        assert "address" in values["mail"]
        assert "app_password" in values["mail"]
    finally:
        dlg.close()


def test_view_menu_themes_submenu(arelis_window) -> None:
    from arelis.ui.theme import THEME_IDS, active_theme

    window = arelis_window()
    assert tuple(window._theme_actions) == THEME_IDS
    assert window._theme_actions["sodium"].isChecked()
    assert active_theme() == "sodium"
    window._choose_theme("sodium", True)
    assert window._theme_actions["sodium"].isChecked()


def test_theme_persists_in_local_config(tmp_path: Path, monkeypatch) -> None:
    from arelis.ui.theme import apply_theme

    local = tmp_path / "config.local.yaml"
    monkeypatch.setattr("arelis.config.LOCAL_CONFIG_PATH", local)
    merge_local_config({"ui": {"theme": "sodium"}}, path=local)
    data = yaml.safe_load(local.read_text(encoding="utf-8"))
    assert data["ui"]["theme"] == "sodium"
    apply_theme("sodium")


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
        list_models=lambda: [],
    )
    try:
        assert dlg.tabs.tabText(dlg.tabs.currentIndex()) == "notify"
        assert dlg.pair_qr.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Fixed
        assert dlg.pair_qr.hasScaledContents() is False
        assert dlg.pair_status.wordWrap() is True
        texts = dlg._notify_channels["sms"]
        assert isinstance(texts, type(dlg.language_combo))
        before = texts.currentIndex()
        scrolled = dlg.notify_scroll.verticalScrollBar().value()
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent

        from arelis.ui.qr_image import pairing_pixmap

        dlg.resize(560, 640)
        dlg.show()
        pix = pairing_pixmap(
            "http://192.168.1.2:8765/" + ("k" * 80),
            scale=4,
            pad=16,
            max_side=232,
        )
        dlg._set_pair_qr(pix)
        qt_app.processEvents()
        assert dlg.notify_scroll.verticalScrollBar().maximum() > 0
        wheel = QWheelEvent(
            QPointF(4, 4),
            QPointF(4, 4),
            QPoint(0, 0),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        qt_app.sendEvent(texts, wheel)
        assert texts.currentIndex() == before
        assert not wheel.isAccepted()
        # The window delivers an unaccepted wheel to parents. sendEvent does not.
        target = texts.parentWidget()
        while target is not None and not wheel.isAccepted():
            qt_app.sendEvent(target, wheel)
            target = target.parentWidget()
        qt_app.processEvents()
        assert dlg.notify_scroll.verticalScrollBar().value() != scrolled
    finally:
        dlg.close()


def test_notify_qr_keeps_its_full_square(qt_app) -> None:
    """The link plate used to paint over the bottom of the code."""
    from PySide6.QtCore import QRect

    from arelis.ui.qr_image import pairing_pixmap
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
        initial_tab="notify",
        list_models=lambda: [],
    )
    try:
        dlg.resize(560, 700)
        dlg.show()
        pix = pairing_pixmap(
            "http://192.168.86.248:8765/" + ("k" * 160),
            scale=4,
            pad=16,
            max_side=232,
        )
        dlg._set_pair_qr(pix)
        qt_app.processEvents()
        assert pix.width() <= 232
        assert dlg.pair_qr.width() == pix.width()
        assert dlg.pair_qr.height() == pix.height()
        assert not dlg.notify_url.isVisible()
        dlg.pair_more_btn.setChecked(True)
        qt_app.processEvents()

        def box(widget) -> QRect:
            origin = widget.mapTo(dlg, QPoint(0, 0))
            return QRect(origin, widget.size())

        assert dlg.notify_url.isVisible()
        assert not box(dlg.pair_qr).intersects(box(dlg.notify_url))
        grabbed = dlg.pair_qr.grab()
        assert grabbed.size() == pix.size()
        corner = grabbed.toImage().pixelColor(8, grabbed.height() - 8)
        source = pix.toImage().pixelColor(8, pix.height() - 8)
        assert abs(corner.red() - source.red()) < 8
        assert abs(corner.green() - source.green()) < 8
        assert abs(corner.blue() - source.blue()) < 8
    finally:
        dlg.close()
