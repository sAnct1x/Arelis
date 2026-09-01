"""Dock stack and View-menu toggles. ArelisWindow methods stay as delegates.

The integrator deletes the matching methods from ``app.py`` and calls these
instead. Filament present/dress/place stay on the window until Wave 3.
``_animate_dock``, ``_sync_view_checks``, ``_place_filament_floats``, and
``_flush_glass_surface`` stay on the window.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDockWidget, QTabBar, QWidget

from arelis.ui.dock_surface import apply_dock_chrome, chrome_applying
from arelis.ui.filament_tile import flush_tile_geom
from arelis.ui.theme import active_theme

# Copied from app.py so this module never imports ArelisWindow (cycle).
# Each neighbor contributes _PANEL_HALF so the visible gap is 2 * HALF = OUTER.
_PANEL_OUTER = 12
_PANEL_HALF = 6
_PANEL_TOP = 12
_PANEL_BOTTOM = 14


def _set_shell_margins(shell: QWidget | None, margins: tuple[int, int, int, int]) -> None:
    if shell is None:
        return
    layout = shell.layout()
    if layout is not None:
        layout.setContentsMargins(*margins)


def bind_docks(window) -> None:
    """Wire think/work/history/camera docks to the extracted layout slots."""
    window.think_dock.visibilityChanged.connect(
        lambda visible, d=window.think_dock: on_dock_visibility(
            window, visible, sender=d
        )
    )
    window.work_dock.visibilityChanged.connect(
        lambda visible, d=window.work_dock: on_dock_visibility(
            window, visible, sender=d
        )
    )
    window.history_dock.visibilityChanged.connect(
        lambda visible, d=window.history_dock: on_dock_visibility(
            window, visible, sender=d
        )
    )
    window.camera_dock.visibilityChanged.connect(
        lambda visible, d=window.camera_dock: on_dock_visibility(
            window, visible, sender=d
        )
    )
    for dock in (
        window.think_dock,
        window.work_dock,
        window.history_dock,
        window.camera_dock,
    ):
        dock.dockLocationChanged.connect(lambda _area: sync_panel_margins(window))
        dock.topLevelChanged.connect(lambda _floating: sync_panel_margins(window))
        dock.topLevelChanged.connect(lambda _floating: window._flush_glass_surface())
    window.history_dock.topLevelChanged.connect(
        lambda _f: stack_left_instruments(window)
    )
    window.camera_dock.topLevelChanged.connect(
        lambda _f: stack_left_instruments(window)
    )
    window.history_dock.dockLocationChanged.connect(
        lambda _a: stack_left_instruments(window)
    )
    window.camera_dock.dockLocationChanged.connect(
        lambda _a: stack_left_instruments(window)
    )


def reveal_dock(
    window,
    dock: QDockWidget,
    action: QAction | None = None,
    *,
    asked: bool = False,
) -> None:
    """Show an instrument once, with the same fade used by the View menu.

    Filament plates open from the bead, not from a turn. Auto-show is
    sodium stacked glass. asked=True is View / click. Thinking still
    breathes on the current.
    """
    if active_theme() == "filament" and not asked:
        return
    if getattr(window, "_away_resting", False):
        return
    if dock.isVisible():
        return
    dock.show()
    if action is not None:
        action.setChecked(True)
    window._animate_dock(dock)
    if active_theme() == "filament":
        names = {
            window.think_dock: "thinking",
            window.work_dock: "files",
            window.history_dock: "history",
            window.camera_dock: "camera",
        }
        window._filament_present_tile(dock, names.get(dock, "files"))


def toggle_thinking(window, checked: bool) -> None:
    from arelis.ui.idle_host import note_engagement

    note_engagement(window)
    window.think_dock.setVisible(checked)
    if checked:
        window._animate_dock(window.think_dock)
        window._filament_present_tile(window.think_dock, "thinking")


def toggle_workspace(window, checked: bool) -> None:
    from arelis.ui.idle_host import note_engagement

    note_engagement(window)
    window.work_dock.setVisible(checked)
    if checked:
        window._animate_dock(window.work_dock)
        window._filament_present_tile(window.work_dock, "files")


def toggle_history(window, checked: bool) -> None:
    from arelis.ui.history_host import refresh_history
    from arelis.ui.idle_host import note_engagement

    note_engagement(window)
    window.history_dock.setVisible(checked)
    if checked:
        refresh_history(window)
        window._animate_dock(window.history_dock)
        window._filament_present_tile(window.history_dock, "history")
    stack_left_instruments(window)


def toggle_notifications(window, checked: bool) -> None:
    from arelis.ui.idle_host import note_engagement, sync_idle_mode
    from arelis.ui.notify_host import on_notify_poll, sync_notify_surface

    note_engagement(window)
    if checked:
        on_notify_poll(window)
        window.notify_inbox.show()
        window.notify_inbox.raise_()
        window.notifications.opened.emit()
        if active_theme() == "filament":
            window._filament_dress_tile(window.notify_inbox, "notify")
            window._filament_place_near_title(window.notify_inbox, "notify")
    else:
        if active_theme() == "filament":
            flush_tile_geom(window.notify_inbox)
        window.notify_inbox.hide()

    sync_notify_surface(window)
    sync_idle_mode(window)


def toggle_camera(window, checked: bool) -> None:
    from arelis.ui.idle_host import note_engagement

    note_engagement(window)
    window.camera_dock.setVisible(checked)
    if checked:
        window.camera.start()
        window._animate_dock(window.camera_dock)
        window._filament_present_tile(window.camera_dock, "camera")
    else:
        window.camera.stop()
    stack_left_instruments(window)


def toggle_contacts(window, checked: bool) -> None:
    from arelis.ui.idle_host import note_engagement, sync_idle_mode

    note_engagement(window)
    if checked:
        window.contacts.show_list()
        window.contacts_inbox.show()
        window.contacts_inbox.raise_()
        if active_theme() == "filament":
            window._filament_dress_tile(window.contacts_inbox, "contacts")
            window._filament_place_near_title(window.contacts_inbox, "contacts")
    else:
        if active_theme() == "filament":
            flush_tile_geom(window.contacts_inbox)
        window.contacts_inbox.hide()
    sync_idle_mode(window)


def toggle_calendar(window, checked: bool) -> None:
    from arelis.ui.calendar_host import kick_calendar_sync
    from arelis.ui.idle_host import note_engagement, sync_idle_mode

    note_engagement(window)
    if checked:
        if not getattr(window, "_calendar_placed", False):
            geo = window.frameGeometry()
            window.calendar_window.move(geo.x() + 40, geo.y() + 40)
            window._calendar_placed = True
        window.calendar_window.show()
        window.calendar_window.raise_()
        window.calendar.reload()
        kick_calendar_sync(window)
        window._calendar_sync_timer.start()
        if active_theme() == "filament":
            window._filament_dress_tile(window.calendar_window, "days")
            window._filament_place_near_title(window.calendar_window, "days")
    else:
        if active_theme() == "filament":
            flush_tile_geom(window.calendar_window)
        window.calendar_window.hide()
        window._calendar_sync_timer.stop()
        window._calendar_sync_watchdog.stop()
    sync_idle_mode(window)


def on_dock_visibility(window, visible: bool, *, sender=None) -> None:
    # Ignore the transient hide that setWindowFlags causes while swapping
    # floating chrome — otherwise View checks flip off and the panel vanishes.
    # _arelis_parked is the same kind of bookkeeping: the glass went to the
    # tray or the taskbar and took its floating panels with it, which is not
    # the user turning an instrument off.
    if sender is None:
        sender = window.sender()
    if getattr(window, "_filament_hiding", False):
        return
    if isinstance(sender, QDockWidget) and (
        chrome_applying(sender) or getattr(sender, "_arelis_parked", False)
    ):
        return
    if (
        not visible
        and active_theme() == "filament"
        and isinstance(sender, QDockWidget)
    ):
        flush_tile_geom(sender)
    window._sync_view_checks()
    window._place_filament_floats()
    sync_panel_margins(window)
    window._flush_glass_surface()
    if visible:
        dock = sender
        if isinstance(dock, QDockWidget) and dock.isFloating():
            window._animate_dock(dock)
    if sender in (window.history_dock, window.camera_dock):
        stack_left_instruments(window)
    from arelis.ui.idle_host import sync_idle_mode

    sync_idle_mode(window)


def docked_in(window, dock: QDockWidget, area: Qt.DockWidgetArea) -> bool:
    return (
        dock.isVisible()
        and not dock.isFloating()
        and window.dockWidgetArea(dock) == area
    )


def left_column_member(window, dock: QDockWidget) -> bool:
    """Same as docked-on-the-left, but isHidden() so tests and tray agree."""
    return (
        not dock.isHidden()
        and not dock.isFloating()
        and window.dockWidgetArea(dock) == Qt.DockWidgetArea.LeftDockWidgetArea
    )


def history_camera_tabbed(window) -> bool:
    for bar in window.findChildren(QTabBar):
        labels = {bar.tabText(i).strip().lower() for i in range(bar.count())}
        if "history" in labels and "camera" in labels:
            return True
    return False


def stack_left_instruments(window) -> None:
    """History above camera on the left. No tabs. Float restores history."""
    if active_theme() == "filament":
        return
    if getattr(window, "_disposed", False) or getattr(window, "_stacking_left", False):
        return
    if chrome_applying(window.history_dock) or chrome_applying(window.camera_dock):
        return
    window._stacking_left = True
    try:
        hist = window.history_dock
        cam = window.camera_dock
        if history_camera_tabbed(window):
            if not hist.isFloating():
                window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, hist)
            if not cam.isFloating():
                window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, cam)
        hist_left = left_column_member(window, hist)
        cam_left = left_column_member(window, cam)
        if hist_left and cam_left:
            already = cam.y() >= hist.y() + 40 and not history_camera_tabbed(window)
            window.splitDockWidget(hist, cam, Qt.Orientation.Vertical)
            if not already:
                column = max(hist.height() + cam.height(), 400)
                cam_h = max(240, column // 2)
                hist_h = max(160, column - cam_h)
                window.resizeDocks([hist, cam], [hist_h, cam_h], Qt.Orientation.Vertical)
        sync_panel_margins(window)
    finally:
        window._stacking_left = False


def sync_panel_margins(window) -> None:
    """Keep outer and inter-panel gutters equal (history | chat | thinking)."""
    left = docked_in(
        window, window.history_dock, Qt.DockWidgetArea.LeftDockWidgetArea
    ) or docked_in(
        window, window.camera_dock, Qt.DockWidgetArea.LeftDockWidgetArea
    )
    # Thinking on the right abuts the chat glass.
    right = docked_in(
        window, window.think_dock, Qt.DockWidgetArea.RightDockWidgetArea
    )
    bottom = docked_in(
        window, window.work_dock, Qt.DockWidgetArea.BottomDockWidgetArea
    )

    # Chat: OUTER against the window when a side is empty; HALF when a dock
    # shares that edge (dock contributes the other HALF → gap == OUTER).
    chat_l = _PANEL_HALF if left else _PANEL_OUTER
    chat_r = _PANEL_HALF if right else _PANEL_OUTER
    chat_b = _PANEL_HALF if bottom else _PANEL_BOTTOM
    if active_theme() == "filament" and not left and not right and not bottom:
        window._stage_layout.setContentsMargins(0, 0, 0, 0)
    else:
        window._stage_layout.setContentsMargins(chat_l, _PANEL_TOP, chat_r, chat_b)

    # Floating shells must stay margin-0 / opaque — docked gutters punch holes.
    hist_left = left_column_member(window, window.history_dock)
    cam_left = left_column_member(window, window.camera_dock)
    stacked = hist_left and cam_left

    if window.history_dock.isFloating():
        _set_shell_margins(window._history_shell, (0, 0, 0, 0))
    elif stacked:
        _set_shell_margins(
            window._history_shell,
            (_PANEL_OUTER, _PANEL_TOP, _PANEL_HALF, _PANEL_HALF),
        )
    else:
        _set_shell_margins(
            window._history_shell,
            (_PANEL_OUTER, _PANEL_TOP, _PANEL_HALF, _PANEL_BOTTOM),
        )
    if window.think_dock.isFloating():
        _set_shell_margins(window._think_shell, (0, 0, 0, 0))
    else:
        _set_shell_margins(
            window._think_shell,
            (_PANEL_HALF, _PANEL_TOP, _PANEL_OUTER, _PANEL_BOTTOM),
        )
    if window.work_dock.isFloating():
        _set_shell_margins(window._work_shell, (0, 0, 0, 0))
    else:
        _set_shell_margins(
            window._work_shell,
            (_PANEL_OUTER, _PANEL_HALF, _PANEL_OUTER, _PANEL_BOTTOM),
        )
    if window.camera_dock.isFloating():
        _set_shell_margins(window._camera_shell, (0, 0, 0, 0))
    elif stacked:
        _set_shell_margins(
            window._camera_shell,
            (_PANEL_OUTER, _PANEL_HALF, _PANEL_HALF, _PANEL_BOTTOM),
        )
    else:
        _set_shell_margins(
            window._camera_shell,
            (_PANEL_OUTER, _PANEL_TOP, _PANEL_HALF, _PANEL_BOTTOM),
        )


def sanitize_floating_docks(window) -> None:
    """Seal restored floats. Never slam them back into the column.

    A floating camera on the other monitor is a saved layout, not a ghost.
    Ghosts came from a translucent main HWND plus redocking after first
    paint (wide stage, then shrink, leftover orbit on the right). Floats
    stay their own opaque HWNDs; calendar and world are not docks.
    """
    for dock in (
        window.think_dock,
        window.work_dock,
        window.history_dock,
        window.camera_dock,
    ):
        apply_dock_chrome(dock, dock.isFloating())
    stack_left_instruments(window)
    sync_panel_margins(window)
    window._flush_glass_surface()
