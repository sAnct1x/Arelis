"""One app, not eleven. Guards the things the audit found drifting apart."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPlainTextEdit

from arelis.ui.panels.calendar import CalendarPanel
from arelis.ui.panels.camera import CameraPanel
from arelis.ui.panels.conversation import ConversationStage
from arelis.ui.panels.workspace import (
    WorkspacePanel,
    is_workspace_listing,
    status_for_tool_result,
)
from arelis.ui.readiness_strip import ReadinessStrip
from arelis.ui.theme import COLORS, GLASS, METRICS, stylesheet


def test_dock_furniture_is_one_height(qt_app) -> None:
    """Three tiers of button height is how a row ends up looking assembled."""
    panel = WorkspacePanel()
    calendar = CalendarPanel()
    try:
        row = METRICS["row"]
        for widget in (
            panel.project_combo,
            panel.path_edit,
            panel.open_btn,
            panel.save_btn,
            panel.add_root_btn,
            panel.new_root_btn,
            panel.remove_root_btn,
            panel.up_btn,
            panel.refresh_btn,
            panel.recent_combo,
            calendar.prev_btn,
            calendar.today_btn,
            calendar.next_btn,
            calendar.sync_btn,
            calendar.new_btn,
        ):
            assert widget.minimumHeight() == row, widget.objectName()
            assert widget.maximumHeight() == row, widget.objectName()
    finally:
        panel.deleteLater()
        calendar.deleteLater()


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


def test_role_popup_fills_the_plate(qt_app) -> None:
    """Windows reserved a scrollbar lane; transparent track showed a black strip."""
    from PySide6.QtCore import Qt

    stage = ConversationStage()
    try:
        view = stage.role.view()
        assert view is not None
        assert (
            view.verticalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        assert (
            view.horizontalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        parent = view.parentWidget()
        assert parent is not None
        assert parent.objectName() == "ComboPopup"
        css = stylesheet()
        assert COLORS["menu_fill"] in css
        assert "max-width: 96px" not in css.split("#RoleSelect QAbstractItemView")[1][:120]
    finally:
        stage.deleteLater()


def test_attach_rail_is_not_plated_grey(qt_app) -> None:
    """The old filename chip used card_fill and stretched into a grey slab."""
    css = stylesheet()
    assert "AttachmentChip" not in css
    assert "AttachmentTile" in css


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


def test_composer_highlight_drag_does_not_delete_the_draft(qt_app) -> None:
    """The field is a short row. Highlight + mouse up/down used to start a
    Move drag, and the draft vanished when the pointer left the box."""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent, QTextCursor

    stage = ConversationStage()
    try:
        stage.set_idle_mode(False)
        stage.resize(900, 240)
        stage.show()
        qt_app.processEvents()
        field = stage.input
        field.setText("message Arelis about hysteresis")
        cursor = field.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        field.setTextCursor(cursor)
        assert field.textCursor().hasSelection()
        vp = field.viewport()
        below = QPointF(vp.width() / 2, vp.height() + 80)
        move = QMouseEvent(
            QEvent.Type.MouseMove,
            below,
            QPointF(field.mapToGlobal(below.toPoint())),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        field.mouseMoveEvent(move)
        qt_app.processEvents()
        assert field.toPlainText() == "message Arelis about hysteresis"
        assert field.textCursor().hasSelection()
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


def test_systems_menu_allow_opens_settings(qt_app) -> None:
    """Most rows report only. Allow is the way into Settings."""
    strip = ReadinessStrip()
    try:
        strip._rebuild_systems_menu()
        actions = strip._systems_menu.actions()
        assert actions
        header = actions[0].defaultWidget()
        assert header is not None
        assert header.objectName() == "ReadinessSystemsCaption"
        assert "allow" in header.text().lower()
        enabled = [a for a in actions if a.isEnabled()]
        assert len(enabled) == 1
        assert "Allow" in enabled[0].text()
    finally:
        strip.deleteLater()


def test_every_colour_in_the_stylesheet_came_from_a_token() -> None:
    """A literal in the QSS is a surface the palette cannot reach.

    Checked by value rather than by reading the source: every colour the
    stylesheet emits has to be one that COLORS declares, so retuning a token
    moves every pixel it is supposed to move.
    """
    from arelis.ui.theme import apply_theme

    apply_theme("sodium")
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
    assert "#CalendarAgendaList" in qss
    assert "#CalendarJobList" in qss
    assert "#CalendarTabs" in qss
    dock = dock_tab_bar_qss()
    assert COLORS["tab_selected"] in dock
    assert COLORS["raised"] in dock


def test_every_tile_dock_and_line_is_in_the_stylesheet() -> None:
    """A surface with no object-name rule is a second palette."""
    qss = stylesheet()
    for hook in (
        "QDockWidget",
        "#DockTabBar",
        "#GlassDockContent",
        "#InstrumentTitle",
        "#InstrumentAction",
        "#InstrumentIcon",
        "#InstrumentSearch",
        "#CalendarWindow",
        "#CalendarTabs",
        "#CalendarJobList",
        "#CalendarWindowGlass",
        "#ContactsInbox",
        "#NotificationsInbox",
        "#SmsChat",
        "#SettingsDialog",
        "#NotifyCard",
        "#NotifyPill",
        "#DriveStrip",
        "#RoomStrip",
        "#TitleBar",
        "#ChromeTitle",
        "#ChromeHandsBtn",
        "#ChromeSpanBtn",
        "#FilamentBead",
        "#VoidHairline",
        "#DropOverlay",
        "#AttachBar",
        "#ChatView",
        "#ThinkingView",
        "#ConfirmAllow",
        "#DeskList",
        "#DeskEmpty",
        "#DeskHint",
        "#DeskPreview",
    ):
        assert hook in qss, hook


def test_one_corner_radius(qt_app) -> None:
    """Floating plates used to hardcode 16, the notify card 14, the drop overlay 18."""
    from PySide6.QtWidgets import QLabel

    from arelis.ui.calendar_window import CalendarWindow
    from arelis.ui.contacts_inbox import ContactsInboxWindow
    from arelis.ui.glass import GlassFrame, Hairline
    from arelis.ui.notify_inbox import NotificationsInboxWindow
    from arelis.ui.notify_overlay import NotifyOverlay
    from arelis.ui.panels.calendar import CalendarPanel
    from arelis.ui.panels.contacts import ContactsPanel
    from arelis.ui.panels.drive import DriveStrip
    from arelis.ui.panels.instrument import InstrumentPanel
    from arelis.ui.panels.notifications import NotificationsPanel
    from arelis.ui.panels.room import RoomStrip
    from arelis.ui.theme import HAIRLINE

    radius = float(GLASS["radius"])
    plates = (
        (ContactsInboxWindow, ContactsPanel),
        (NotificationsInboxWindow, NotificationsPanel),
        (CalendarWindow, CalendarPanel),
    )
    for factory, panel in plates:
        window = factory(panel())
        try:
            frames = window.findChildren(GlassFrame)
            assert frames
            assert all(frame._radius == radius for frame in frames)
        finally:
            window.deleteLater()

    drive = DriveStrip()
    room = RoomStrip()
    dock = InstrumentPanel("thinking", QLabel("body"))
    overlay = NotifyOverlay()
    line = Hairline()
    try:
        assert drive._radius == radius
        assert not hasattr(room, "_radius")
        assert dock._radius == radius
        assert overlay.card._radius == radius
        assert drive._fill_alpha == int(GLASS["fill_strip"])
        assert line.glow == int(HAIRLINE["rest"])
    finally:
        drive.deleteLater()
        room.deleteLater()
        dock.deleteLater()
        overlay.deleteLater()
        line.deleteLater()


def test_workspace_actions_are_icon_only(qt_app) -> None:
    """Words live in the tooltip; the row is glyphs."""
    panel = WorkspacePanel()
    try:
        assert panel.root_label.isHidden()
        for btn, tip in (
            (panel.open_btn, "Open file"),
            (panel.save_btn, "Save file"),
            (panel.keep_btn, "Keep a note on the desk"),
            (panel.add_root_btn, "Add an existing folder as a project"),
            (panel.new_root_btn, "Create a folder and add it as a project"),
            (
                panel.remove_root_btn,
                "Remove this project from the workspace — files stay on disk",
            ),
            (panel.up_btn, "Up one folder"),
            (panel.refresh_btn, "Refresh this folder"),
        ):
            assert btn.objectName() == "InstrumentIcon", tip
            assert btn.text() == "", tip
            assert btn.toolTip() == tip
            assert btn.accessibleName() == tip
            assert not btn.icon().isNull(), tip
    finally:
        panel.deleteLater()


def test_browse_hides_junk_and_keeps_gitignore(qt_app, tmp_path) -> None:
    root = tmp_path / "lab"
    root.mkdir()
    (root / "notes.txt").write_text("ok", encoding="utf-8")
    (root / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "__pycache__").mkdir()
    (root / "pkg.egg-info").mkdir()
    (root / ".git").mkdir()
    (root / "build").mkdir()
    (root / "gone.pyc").write_text("x", encoding="utf-8")

    panel = WorkspacePanel()
    try:
        panel.set_projects(["lab"], "lab", paths={"lab": str(root)})
        names = [
            panel.browse_list.item(i).text()
            for i in range(panel.browse_list.count())
        ]
        assert "notes.txt" in names
        assert ".gitignore" in names
        assert "src" in names
        assert "build" in names
        assert "__pycache__" not in names
        assert "pkg.egg-info" not in names
        assert ".git" not in names
        assert "gone.pyc" not in names
        assert all(not name.startswith("[dir]") for name in names)
        assert all(not name.startswith("[file]") for name in names)
        notes = panel.browse_list.item(names.index("notes.txt"))
        src = panel.browse_list.item(names.index("src"))
        assert notes is not None
        assert src is not None
    finally:
        panel.deleteLater()


def test_workspace_log_stays_a_strip(qt_app) -> None:
    panel = WorkspacePanel()
    try:
        assert panel.output.isHidden()
        panel.append_output("\n".join(str(n) for n in range(40)))
        lines = panel.output.toPlainText().splitlines()
        assert lines == ["0"]
        assert panel.output.maximumHeight() == METRICS["row"] + 4
        assert panel.output.maximumHeight() < 1000
        assert not panel.output.isHidden()
    finally:
        panel.deleteLater()


def test_status_strip_ignores_listings_and_keeps_wrote() -> None:
    listing = "[dir] docs\n[file] LICENSE\n[file] README.md"
    assert (
        status_for_tool_result("workspace", ok=True, action="list", output=listing)
        is None
    )
    assert (
        status_for_tool_result("workspace", ok=True, action="read", output="hello")
        is None
    )
    assert (
        status_for_tool_result(
            "analyze", ok=True, output="n=3\nmean=1.2"
        )
        is None
    )
    assert (
        status_for_tool_result(
            "workspace",
            ok=True,
            action="write",
            output="Wrote theory_of_relativity.md\nextra chatter",
        )
        == "Wrote theory_of_relativity.md"
    )
    assert (
        status_for_tool_result(
            "workspace", ok=False, output="Not a file: C:/typo.csv"
        )
        == "Not a file: C:/typo.csv"
    )
    assert is_workspace_listing("list", listing, "")
    assert is_workspace_listing("", listing, "")
    assert not is_workspace_listing("write", "Wrote notes.md", "")


def test_browse_to_opens_the_listed_folder(qt_app, tmp_path) -> None:
    root = tmp_path / "lab"
    docs = root / "docs"
    docs.mkdir(parents=True)
    (docs / "guide.md").write_text("hi", encoding="utf-8")
    (root / "notes.txt").write_text("ok", encoding="utf-8")
    panel = WorkspacePanel()
    try:
        panel.set_projects(["lab"], "lab", paths={"lab": str(root)})
        panel.browse_to(str(docs), root_name="lab")
        names = [
            panel.browse_list.item(i).text()
            for i in range(panel.browse_list.count())
        ]
        assert "guide.md" in names
        assert "notes.txt" not in names
        assert panel.browse_label.text() == "docs"
    finally:
        panel.deleteLater()


def test_a_workspace_list_does_not_fill_the_dock(arelis_window, tmp_path) -> None:
    from arelis.core.events import Event, EventType

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("hi", encoding="utf-8")
    win = arelis_window()
    name = tmp_path.name
    win.workspace.set_projects([name], name, paths={name: str(tmp_path)})
    listing = "[file] LICENSE\n[file] README.md"
    win._on_event(
        Event(
            EventType.TOOL_START,
            {"tool": "workspace", "args": {"action": "list", "path": "docs"}},
        )
    )
    win._on_event(
        Event(
            EventType.TOOL_RESULT,
            {
                "tool": "workspace",
                "ok": True,
                "output": listing,
                "args": {"action": "list"},
                "data": {
                    "path": "docs",
                    "abs_path": str(docs),
                    "root_name": name,
                },
            },
        )
    )
    assert win.workspace.output.isHidden()
    assert "[file]" not in win.workspace.output.toPlainText()
    names = [
        win.workspace.browse_list.item(i).text()
        for i in range(win.workspace.browse_list.count())
    ]
    assert "guide.md" in names


def test_directory_read_back_does_not_permission_deny(arelis_window, tmp_path) -> None:
    from arelis.core.events import Event, EventType

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("hi", encoding="utf-8")
    win = arelis_window()
    name = tmp_path.name
    win.workspace.set_projects([name], name, paths={name: str(tmp_path)})
    said: list[str] = []
    win.chat.add_system = said.append  # type: ignore[method-assign]
    win._on_event(
        Event(
            EventType.TOOL_RESULT,
            {
                "tool": "workspace",
                "ok": True,
                "output": "listed .",
                "args": {"action": "read", "path": "."},
                "data": {
                    "path": ".",
                    "abs_path": str(docs),
                    "root_name": name,
                },
            },
        )
    )
    assert not any("Permission denied" in line for line in said)
    names = [
        win.workspace.browse_list.item(i).text()
        for i in range(win.workspace.browse_list.count())
    ]
    assert "guide.md" in names


def test_a_wrote_status_is_one_line_in_the_dock(arelis_window) -> None:
    from arelis.core.events import Event, EventType

    win = arelis_window()
    win._on_event(
        Event(
            EventType.ASSISTANT_DONE,
            {"text": "Wrote theory_of_relativity.md. Here is a long essay about it."},
        )
    )
    assert win.workspace.output.isHidden()
    win._on_event(
        Event(
            EventType.TOOL_RESULT,
            {
                "tool": "workspace",
                "ok": True,
                "output": "Wrote theory_of_relativity.md",
                "args": {"action": "write"},
                "data": {"path": "never-a-real-file-xyz.md"},
            },
        )
    )
    assert win.workspace.output.toPlainText() == "Wrote theory_of_relativity.md"
    assert win.workspace.output.maximumHeight() == METRICS["row"] + 4
    assert not win.workspace.output.isHidden()


def test_python_files_get_quiet_highlight(qt_app, tmp_path) -> None:
    panel = WorkspacePanel()
    try:
        py_path = tmp_path / "sample.py"
        txt_path = tmp_path / "notes.txt"
        py_path.write_text("def foo():\n    return 1\n", encoding="utf-8")
        txt_path.write_text("hello\n", encoding="utf-8")
        panel.set_file(
            "sample.py",
            py_path.read_text(encoding="utf-8"),
            abs_path=str(py_path),
        )
        assert panel._highlight._on
        panel.set_file("notes.txt", "hello\n", abs_path=str(txt_path))
        assert not panel._highlight._on
    finally:
        panel.deleteLater()
