"""Calm first paint, fonts, and listen-pulse affordances."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.ui.icons import conversation_icon, microphone_icon
from arelis.ui.theme import load_fonts


def test_reset_layout_is_conversation_only(qt_app) -> None:
    from arelis.ui.app import ArelisWindow, BusBridge

    window = ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
    )
    try:
        window.think_dock.show()
        window.work_dock.show()
        window.history_dock.show()
        window.contacts_inbox.show()
        window.calendar_window.show()
        window._reset_layout()
        # isVisible() stays false while the window itself is hidden; isHidden()
        # is the dock's own show/hide latch.
        assert window.think_dock.isHidden()
        assert window.work_dock.isHidden()
        assert window.history_dock.isHidden()
        assert window.calendar_window.isHidden()
        assert window.contacts_inbox.isHidden()
        assert window.notify_inbox.isHidden()
        assert not window.act_thinking.isChecked()
        assert not window.act_contacts.isChecked()
        assert not window.act_calendar.isChecked()
    finally:
        window.hide()
        window.loop.close()


def test_typing_in_the_window_composer_notes_engagement(arelis_window, qt_app) -> None:
    """The live TypeError was the window slot, not ConversationStage.

    QPlainTextEdit.textChanged has no argument. Connecting a one-arg lambda
    logged CRITICAL on every keystroke and never called _note_engagement.
    Typing into ConversationStage alone does not cover that connection.
    """
    from PySide6.QtTest import QTest

    window = arelis_window()
    window._reset_layout()
    window.history_dock.show()
    window._away_rest = True
    window._enter_away_rest()
    assert window._away_resting

    composer = window.conversation.input
    composer.setFocus()
    QTest.keyClicks(composer, "hi")
    qt_app.processEvents()

    assert composer.toPlainText() == "hi"
    assert not window._away_resting


def test_away_rest_collapses_then_click_restores(qt_app) -> None:
    from arelis.ui.app import ArelisWindow, BusBridge

    window = ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
    )
    try:
        window._reset_layout()
        window.history_dock.show()
        window.think_dock.show()
        window._away_rest = True
        window._enter_away_rest()
        assert window._away_resting
        assert window.history_dock.isHidden()
        assert window.think_dock.isHidden()
        window._note_engagement()
        assert not window._away_resting
        assert not window.history_dock.isHidden()
        assert not window.think_dock.isHidden()
        window._enter_away_rest()
        window._on_event(Event(EventType.THINKING, {"text": "boot noise"}))
        assert window.think_dock.isHidden()
    finally:
        window.hide()
        window.loop.close()


def test_thinking_trace_reveals_the_dock(qt_app) -> None:
    from arelis.ui.app import ArelisWindow, BusBridge

    window = ArelisWindow(
        {
            "ui": {
                "default_width": 800,
                "default_height": 600,
                "thinking_open": False,
                "workspace_open": False,
            },
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
    )
    try:
        window._reset_layout()
        assert window.think_dock.isHidden()
        window._on_event(Event(EventType.THINKING, {"text": "considering Vega"}))
        assert not window.think_dock.isHidden()
        assert window.act_thinking.isChecked()
    finally:
        window.hide()
        window.loop.close()


def test_load_fonts_prefers_bundled_plex_when_present(qt_app) -> None:
    font_dir = Path(__file__).resolve().parents[1] / "arelis" / "ui" / "fonts"
    zen = font_dir / "ZenKakuGothicNew-Regular.ttf"
    bundled = [
        font_dir / "IBMPlexSans-Regular.ttf",
        font_dir / "IBMPlexSans-SemiBold.ttf",
        font_dir / "IBMPlexMono-Regular.ttf",
    ]
    families = load_fonts()
    assert "body" in families
    assert "mono" in families
    if zen.is_file():
        return
    if not all(path.is_file() for path in bundled):
        return
    assert "Plex" in families["body"]
    assert "Plex" in families["mono"]


def test_live_icons_accept_a_pulse(qt_app) -> None:
    assert not microphone_icon(22, live=True, pulse=0.6).isNull()
    assert not conversation_icon(22, live=True, pulse=1.2).isNull()


def test_role_combo_is_not_editable(qt_app) -> None:
    """Editable+readOnly LineEdit ate Windows popup clicks (U1 / S01-S10)."""
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage(default_role="fast")
    try:
        assert not stage.role.isEditable()
        assert stage.role.currentText() == "fast"
        stage.role.setCurrentText("research")
        assert stage.role.currentText() == "research"
    finally:
        stage.deleteLater()


def test_role_status_syncs_composer_combo(qt_app) -> None:
    from arelis.ui.app import ArelisWindow, BusBridge

    window = ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
    )
    try:
        assert window.conversation.role.currentText() == "fast"
        window._on_event(
            Event(
                EventType.STATUS,
                {
                    "message": (
                        "Role set to `research`. New messages use it unless you pick another chip."
                    )
                },
            )
        )
        assert window.conversation.role.currentText() == "research"
        assert window._current_role == "research"
    finally:
        window.hide()
        window.loop.close()


def _dock_with_panel(title: str = "history"):
    """A dock shaped like the real ones: dock → shell → InstrumentPanel."""
    from PySide6.QtWidgets import QDockWidget, QLabel, QVBoxLayout, QWidget

    from arelis.ui.panels.instrument import InstrumentPanel

    panel = InstrumentPanel(title, QLabel("body"))
    shell = QWidget()
    QVBoxLayout(shell).addWidget(panel)
    dock = QDockWidget(title)
    dock.setObjectName(f"{title.title()}Dock")
    dock.setWidget(shell)
    return dock, shell, panel


def test_floating_instrument_raises_fill_alpha(qt_app) -> None:
    from arelis.ui.dock_surface import (
        DOCKED_FILL_ALPHA,
        FLOATING_FILL_ALPHA,
        apply_dock_surface,
    )

    dock, _shell, panel = _dock_with_panel()
    assert panel._fill_alpha == DOCKED_FILL_ALPHA
    apply_dock_surface(dock, True)
    assert panel._fill_alpha == FLOATING_FILL_ALPHA
    apply_dock_surface(dock, False)
    assert panel._fill_alpha == DOCKED_FILL_ALPHA
    dock.deleteLater()


def test_one_call_seals_the_whole_dock_subtree(qt_app) -> None:
    """The ghost is one frame of translucency on a float, anywhere in the tree.

    A floating dock is its own top-level HWND, and WA_TranslucentBackground makes
    that a Windows layered window whose bitmap the OS keeps across hide/resize
    and re-presents before Qt paints. Sealing the dock but missing the shell, or
    the shell but not the panel, is how a stale copy survived. One call has to
    settle all three, or the next fix is another writer racing the others.
    """
    from PySide6.QtCore import Qt

    from arelis.ui.dock_surface import apply_dock_surface

    dock, shell, panel = _dock_with_panel()
    for surface in (dock, shell, panel):
        apply_dock_surface(dock, True)
        assert not surface.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        assert surface.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        assert surface.autoFillBackground()
        assert surface.graphicsEffect() is None

    apply_dock_surface(dock, False)
    for surface in (dock, shell, panel):
        assert surface.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        assert not surface.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
    dock.deleteLater()


def test_panel_fill_alpha_cannot_relayer_a_float(qt_app) -> None:
    """GlassFrame derives translucency from fill alpha; a dock must not.

    ``set_fill_alpha`` on a lone plate deciding its own surface is fine. On a
    dock it is a second writer, and the float only has to lose that race once
    for Windows to start caching a bitmap of it.
    """
    from PySide6.QtCore import Qt

    from arelis.ui.dock_surface import apply_dock_surface

    dock, _shell, panel = _dock_with_panel()
    apply_dock_surface(dock, True)
    panel.set_fill_alpha(0)
    assert not panel.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert panel.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
    dock.deleteLater()


def test_drag_undock_seals_before_the_flag_swap(qt_app) -> None:
    """Undock-by-drag defers window flags to keep the mouse grab, not the seal.

    The old code deferred both, so the panel spent the whole drag as a
    translucent top-level window — the one state that leaves a ghost behind.
    """
    from PySide6.QtCore import Qt

    from arelis.ui.dock_surface import apply_dock_chrome, begin_drag_undock, end_drag_undock

    dock, shell, panel = _dock_with_panel()
    begin_drag_undock(dock)
    apply_dock_chrome(dock, True)
    for surface in (dock, shell, panel):
        assert not surface.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    # The header the drag is holding stays put until mouse-up.
    assert panel._float_chrome.isHidden()
    assert end_drag_undock(dock)
    apply_dock_chrome(dock, True)
    assert not panel._float_chrome.isHidden()
    dock.deleteLater()


def test_inbound_sms_held_until_turn_floor_frees(qt_app, tmp_path: Path) -> None:
    from arelis.core.events import Event, EventType
    from arelis.memory import MemoryStore
    from arelis.ui.app import ArelisWindow, BusBridge

    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    window = ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
        store=store,
    )
    try:
        window._set_busy(True)
        window._on_event(
            Event(
                EventType.SMS_RECEIVED,
                {
                    "id": "a",
                    "from": "+1555",
                    "body": "Bro that man is SSG",
                    "contact_name": "Robin Hale",
                },
            )
        )
        window._on_event(
            Event(
                EventType.SMS_RECEIVED,
                {
                    "id": "b",
                    "from": "+1555",
                    "body": "But his title is very very important",
                    "contact_name": "Robin Hale",
                },
            )
        )
        chat = window.chat.view.toPlainText()
        think = window.thinking.view.toPlainText()
        assert "Bro that man is SSG" not in chat
        assert "Bro that man is SSG" not in think
        head = window.notify_center.head()
        assert head is not None
        assert head.kind == "sms"
        assert head.count == 2
        assert "Robin" in head.title
        assert window.notify_center.unread_count() == 1
        window._set_busy(False)
        chat = window.chat.view.toPlainText()
        think = window.thinking.view.toPlainText()
        assert "2 texts from Robin Hale" not in chat
        assert "Bro that man is SSG" not in chat
        assert "2 texts from Robin Hale" not in think
        rows = store.get_messages(store.session_id or "")
        assert not any(r["role"] == "notice" for r in rows)
    finally:
        window.hide()
        window.loop.close()
        store.close()


def test_esc_does_not_kill_a_turn_that_has_painted_nothing(qt_app) -> None:
    """A tool round holds the answer back, so the thread is blank until the
    tools finish. The orbit says "esc to clear", and clearing a blank thread is
    how three spoken SMS turns were cancelled before their Allow card existed.
    The stop control is the thing that cancels, and it still does."""
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    try:
        stops: list[int] = []
        declined: list[int] = []
        stage.stop_requested.connect(lambda: stops.append(1))
        stage.stop_declined.connect(lambda: declined.append(1))

        stage.set_busy(True)
        assert not stage.turn_visible()
        stage._escape()
        assert stops == [], "Esc must not cancel an invisible turn"
        assert declined == [1], "and must say why instead of doing nothing"

        # The stop control has no ladder.
        stage._stop()
        assert stops == [1]

        # Once tokens or a tool line are on screen, Esc means stop again.
        stage.set_turn_visible(True)
        stage._escape()
        assert stops == [1, 1]

        # A new turn starts invisible again.
        stage.set_busy(True)
        assert not stage.turn_visible()
    finally:
        stage.deleteLater()


def test_a_confirm_card_is_something_to_stop(qt_app) -> None:
    """Esc on an open card is deny (wire: skip), not cancel, and not silent."""
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    try:
        declined: list[int] = []
        decided: list[str] = []
        stage.stop_declined.connect(lambda: declined.append(1))
        stage.confirm_decided.connect(
            lambda _id, decision, _batch: decided.append(decision)
        )
        stage.set_busy(True)
        stage.ask_confirm("c1", "send_sms", "text wife: I love you.")
        stage._escape()
        assert decided == ["skip"]
        assert declined == []
    finally:
        stage.deleteLater()


def test_esc_skips_confirm_while_busy(qt_app) -> None:
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    decided: list[str] = []
    stage.confirm_decided.connect(lambda _id, decision, _batch: decided.append(decision))
    stage.set_busy(True)
    stage.ask_confirm("c1", "workspace", "write file")
    assert stage.confirm_open()
    assert stage.input.placeholderText().startswith("Enter = allow")
    stage._escape()
    assert decided == ["skip"]
    assert not stage.confirm_open()
    stage.deleteLater()


@pytest.mark.skipif(sys.platform != "win32", reason="WM_NCCALCSIZE is a Windows message")
def test_frameless_resize_asks_windows_to_redraw_the_client(qt_app) -> None:
    """Returning 0 from WM_NCCALCSIZE is what smears the previous frame.

    Windows then treats the old client area as still valid and blits it into the
    new one, invalidating only what the blit could not fill. In an app that
    paints its own background that is a free optimisation. Here nothing between
    the window and the text paints anything — StageBackground is empty on
    purpose, GlassFrame returns at fill 0 — so the copy is a second header or a
    second orbit that no widget can overwrite. WVR_REDRAW invalidates it.
    """
    from ctypes import addressof, wintypes

    from PySide6.QtWidgets import QWidget

    from arelis.ui.window_resize import WM_NCCALCSIZE, WVR_REDRAW, handle_native_resize

    msg = wintypes.MSG()
    msg.message = WM_NCCALCSIZE
    msg.wParam = 1
    widget = QWidget()
    try:
        assert handle_native_resize(widget, b"windows_generic_MSG", addressof(msg)) == (
            True,
            WVR_REDRAW,
        )
    finally:
        widget.deleteLater()


def test_resize_frame_does_not_promote_a_child(qt_app) -> None:
    """winId() on a child is how every docked panel grew a second HWND.

    The child is then composited twice — parent backing store and its own
    window — and the second copy sits at the child's origin. Resize chrome
    is only for a widget that is already a window.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget

    from arelis.ui.window_resize import enable_win32_resize_frame, top_level_hwnd

    parent = QWidget()
    child = QWidget(parent)
    try:
        parent.show()
        assert child.internalWinId() == 0
        assert top_level_hwnd(child) is None
        enable_win32_resize_frame(child)
        assert child.internalWinId() == 0
        assert not child.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
    finally:
        parent.deleteLater()


def test_application_refuses_native_siblings(qt_app) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from arelis.ui.window_resize import configure_native_windows

    configure_native_windows()
    assert QApplication.testAttribute(
        Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings
    )


def test_a_layout_pass_repaints_the_whole_window(arelis_window) -> None:
    """Moving a widget must not leave the old one behind.

    Qt repaints the smallest region it believes changed, which for a transparent
    interior means the vacated area keeps the last frame. The window answers a
    LayoutRequest with a full update so there is no list of callers to remember.
    """
    from PySide6.QtCore import QEvent

    window = arelis_window()
    calls: list[tuple] = []
    window.update = lambda *args, _c=calls: _c.append(args)  # type: ignore[method-assign]
    window.event(QEvent(QEvent.Type.LayoutRequest))
    # No arguments means the whole widget. update(rect) would repaint a region,
    # which is the behaviour that strands pixels in the first place.
    assert calls == [()]


def test_the_main_window_is_not_a_layered_surface(arelis_window) -> None:
    """WA_TranslucentBackground on the glass is a layered HWND.

    Windows keeps that bitmap across a dock resize. That is the offset orbit
    after tray-quit when a float comes back and the column changes width.
    """
    from PySide6.QtCore import Qt

    window = arelis_window()
    assert not window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert window.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)


def test_sanitize_does_not_redock_a_floating_camera(arelis_window, qt_app) -> None:
    """Launch used to slam the camera back into the column after first paint."""
    from PySide6.QtCore import Qt

    window = arelis_window()
    window.show()
    qt_app.processEvents()
    window.camera_dock.show()
    window.camera_dock.setFloating(True)
    qt_app.processEvents()
    assert window.camera_dock.isFloating()
    window._sanitize_floating_docks()
    qt_app.processEvents()
    assert window.camera_dock.isFloating()
    assert not window.camera_dock.testAttribute(
        Qt.WidgetAttribute.WA_TranslucentBackground
    )


def test_history_and_camera_stack_instead_of_tabs(arelis_window, qt_app) -> None:
    """One left column. No history/camera tab bar. Float gives history its height back."""
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QTabBar

    window = arelis_window()
    window.resize(1200, 800)
    window.show()
    qt_app.processEvents()
    window.history_dock.setFloating(False)
    window.camera_dock.setFloating(False)
    window.history_dock.show()
    window.camera_dock.show()
    window._stack_left_instruments()
    qt_app.processEvents()
    QTest.qWait(40)

    for bar in window.findChildren(QTabBar):
        labels = {bar.tabText(i).strip().lower() for i in range(bar.count())}
        assert "history" not in labels or "camera" not in labels

    hist = window.history_dock
    cam = window.camera_dock
    assert abs(cam.x() - hist.x()) < 48
    assert cam.y() >= hist.y() + 20
    stacked_h = hist.height()

    window.camera_dock.setFloating(True)
    qt_app.processEvents()
    QTest.qWait(40)
    window._stack_left_instruments()
    qt_app.processEvents()
    assert hist.height() > stacked_h
