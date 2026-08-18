"""One app, not eleven. Guards the things the audit found drifting apart."""

from __future__ import annotations

import re

from PySide6.QtWidgets import QPlainTextEdit

from arelis.ui.panels.camera import CameraPanel
from arelis.ui.panels.conversation import ConversationStage
from arelis.ui.panels.workspace import WorkspacePanel
from arelis.ui.readiness_strip import ReadinessStrip
from arelis.ui.theme import COLORS, GLASS, METRICS, stylesheet


def test_dock_furniture_is_one_height(qt_app) -> None:
    """Three tiers of button height is how a row ends up looking assembled."""
    panel = WorkspacePanel()
    try:
        row = METRICS["row"]
        for widget in (
            panel.project_combo,
            panel.path_edit,
            panel.open_btn,
            panel.save_btn,
            panel.recent_combo,
        ):
            assert widget.height() == row, widget.objectName()
    finally:
        panel.deleteLater()


def test_composer_controls_line_up(qt_app) -> None:
    stage = ConversationStage()
    try:
        # The idle face grows its own prompt to fit the sentence; the row this
        # is about is the workbench composer.
        stage.set_idle_mode(False)
        control = METRICS["control"]
        for widget in (
            stage.role,
            stage.input,
            stage.attach_btn,
            stage.mic_btn,
            stage.conversation_btn,
        ):
            assert widget.height() == control, widget.objectName()
    finally:
        stage.deleteLater()


def test_workbench_composer_keeps_long_text_after_a_tool_sync(qt_app) -> None:
    """NoWrap + a one-line height clipped drafts; a tool turn then reset it."""
    stage = ConversationStage()
    try:
        stage.set_idle_mode(False)
        stage.resize(900, 200)
        stage.show()
        qt_app.processEvents()
        draft = "search for interferometry videos and tell me the top three " * 6
        stage.input.setText(draft)
        stage.input.setCursorPosition(len(draft))
        qt_app.processEvents()
        assert stage.input.toPlainText() == draft
        assert (
            stage.input.lineWrapMode()
            == QPlainTextEdit.LineWrapMode.WidgetWidth
        )
        assert stage.input.height() >= METRICS["control"]
        # Same hammer a tool start / Allow / ASSISTANT_DONE used to apply.
        stage.set_busy(True)
        stage.set_idle_mode(False)
        stage.set_busy(False)
        qt_app.processEvents()
        assert stage.input.toPlainText() == draft
        assert stage.input.textCursor().position() > 0
    finally:
        stage.hide()
        stage.deleteLater()


def test_pickers_are_styled_like_pickers(qt_app) -> None:
    """A combo with no object name renders as bare chrome beside a filled field."""
    workspace = WorkspacePanel()
    camera = CameraPanel()
    try:
        assert workspace.project_combo.objectName() == "InstrumentCombo"
        assert workspace.recent_combo.objectName() == "InstrumentCombo"
        assert camera.device_combo.objectName() == "InstrumentCombo"
    finally:
        workspace.deleteLater()
        camera.deleteLater()


def test_filenames_are_not_set_in_the_code_face(qt_app) -> None:
    panel = WorkspacePanel()
    try:
        assert panel.browse_list.objectName() == "BrowseList"
    finally:
        panel.deleteLater()


def test_notify_chip_is_dressed_as_a_button(qt_app) -> None:
    strip = ReadinessStrip()
    try:
        assert strip.notify_chip.objectName() == "ReadinessNotifyChip"
    finally:
        strip.deleteLater()


def test_systems_menu_says_it_is_read_only(qt_app) -> None:
    """Every row in it is disabled, so the menu has to admit that up front."""
    strip = ReadinessStrip()
    try:
        strip._rebuild_systems_menu()
        actions = strip._systems_menu.actions()
        assert actions
        assert not any(action.isEnabled() for action in actions)
        header = actions[0].defaultWidget()
        assert header is not None
        assert header.objectName() == "ReadinessSystemsCaption"
    finally:
        strip.deleteLater()


def test_every_colour_in_the_stylesheet_came_from_a_token() -> None:
    """A literal in the QSS is a surface the palette cannot reach.

    Checked by value rather than by reading the source: every colour the
    stylesheet emits has to be one that COLORS declares, so retuning a token
    moves every pixel it is supposed to move.
    """
    qss = stylesheet()
    known = {
        re.sub(r"\s+", "", value).lower()
        for value in COLORS.values()
        if value.startswith(("#", "rgb"))
    }
    emitted = re.findall(r"rgba?\([^)]*\)|#[0-9a-fA-F]{6}\b", qss)
    stray = {
        found for found in emitted if re.sub(r"\s+", "", found).lower() not in known
    }
    assert not stray, f"colours with no token behind them: {sorted(stray)}"


def test_native_lists_and_dock_tabs_use_opaque_ember() -> None:
    """Translucent QSS on QTabBar/QListWidget is how Windows grey leaks in."""
    from arelis.ui.theme import dock_tab_bar_qss

    qss = stylesheet()
    assert "#SettingsList" in qss
    dock = dock_tab_bar_qss()
    assert COLORS["tab_selected"] in dock
    assert COLORS["raised"] in dock


def test_one_corner_radius(qt_app) -> None:
    """Floating plates used to hardcode 16, the notify card 14, the drop overlay 18."""
    from arelis.ui.contacts_inbox import ContactsInboxWindow
    from arelis.ui.glass import GlassFrame
    from arelis.ui.notify_inbox import NotificationsInboxWindow
    from arelis.ui.panels.contacts import ContactsPanel
    from arelis.ui.panels.notifications import NotificationsPanel

    radius = float(GLASS["radius"])
    plates = (
        (ContactsInboxWindow, ContactsPanel),
        (NotificationsInboxWindow, NotificationsPanel),
    )
    for factory, panel in plates:
        window = factory(panel())
        try:
            frames = window.findChildren(GlassFrame)
            assert frames
            assert all(frame._radius == radius for frame in frames)
        finally:
            window.deleteLater()
