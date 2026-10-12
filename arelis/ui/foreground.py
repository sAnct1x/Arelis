"""Whether this process owns the OS foreground window.

Qt's ``isActiveWindow()`` and ``applicationState()`` can stay "active" after
you click into another app, common on Windows with Tool windows. The SMS
tile then skipped its attention rim. ``GetForegroundWindow`` is the actual
"are they looking at us?"

Tiles are owned / ``Qt.Tool`` HWNDs. Clicking the main glass brings Arelis
forward; clicking a tile did not, because Windows leaves those plates behind
the other app. ``claim_foreground`` is the same raise the glass already gets.
"""

from __future__ import annotations

import os
import sys
from typing import Any

# Flash the taskbar button until the window comes to the foreground.
_FLASHW_TRAY = 0x00000002
_FLASHW_TIMERNOFG = 0x0000000C

_MONITOR_DEFAULTTONEAREST = 2
_GWL_STYLE = -16
_WS_MAXIMIZE = 0x01000000
_SWP_NOZORDER = 0x0004
_SWP_FRAMECHANGED = 0x0020
_SWP_NOOWNERZORDER = 0x0200

# Set on every sealed plate and floating dock so a click on a child still
# raises the tile, not only a click on empty chrome.
_CLICK_TO_FRONT = "_arelis_click_to_front"
_APP_FILTER = "_arelis_click_to_front_filter"
_NATIVE_FILTER = "_arelis_native_front_filter"
# LockSetForegroundWindow. Only the current foreground process can lock;
# a quiet start that is not already in front no-ops, which is fine.
_LSFW_LOCK = 1
_LSFW_UNLOCK = 2
_QUIET_CLEAR = "_arelis_quiet_clear"
_QUIET_FILTER = "_arelis_quiet_filter"


def process_owns_foreground() -> bool:
    """True when a window of this process is the OS foreground window."""
    if sys.platform != "win32":
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QGuiApplication

            return (
                QGuiApplication.applicationState()
                == Qt.ApplicationState.ApplicationActive
            )
        except Exception:
            return True
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        fg = user32.GetForegroundWindow()
        if not fg:
            return False
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
        return int(pid.value) == os.getpid()
    except Exception:
        return True


def accepts_click_to_front(widget: Any) -> bool:
    return bool(getattr(widget, _CLICK_TO_FRONT, False))


def bind_click_to_front(widget: Any) -> None:
    """Mark a plate so a click brings it forward, same as the main glass."""
    if widget is None:
        return
    setattr(widget, _CLICK_TO_FRONT, True)
    _install_app_filter()


def _top_window(widget: Any) -> Any:
    """The top-level that owns ``widget``, or the widget itself."""
    window_fn = getattr(widget, "window", None)
    if not callable(window_fn):
        return widget
    try:
        top = window_fn()
    except RuntimeError:
        # A deleted QWidget raises here. The caller still has the widget.
        return widget
    return widget if top is None else top


def quiet_launch(widget: Any) -> bool:
    """True when this window was opened without the user asking.

    ``_launched_in_background`` is the one flag. It lives on the glass
    (login, tray, updater, ``--background``). A child asks its top-level
    window; there is no second flag.
    """
    if widget is None:
        return False
    if getattr(widget, "_launched_in_background", False):
        return True
    top = _top_window(widget)
    return top is not widget and bool(getattr(top, "_launched_in_background", False))


def focus_if_allowed(widget: Any, reason: Any = None) -> None:
    """``setFocus`` unless this launch is still quiet.

    ``setFocus`` activates the top-level window on Windows. A login or tray
    start must not do that. A click or a second shortcut clears the flag
    first, so a later focus still lands.
    """
    if widget is None or quiet_launch(widget):
        return
    focus = getattr(widget, "setFocus", None)
    if not callable(focus):
        return
    if reason is None:
        focus()
    else:
        focus(reason)


def release_quiet_launch(widget: Any) -> None:
    """The user asked for the window. Drop the quiet flag and the lock.

    Does not show, raise, or activate. Callers that may take the foreground
    do that themselves after this returns.
    """
    if widget is None:
        return
    top = _top_window(widget)
    if top is None or not getattr(top, "_launched_in_background", False):
        return
    top._launched_in_background = False
    _unlock_foreground()
    _set_no_activate_style(top, False)
    _disconnect_quiet_clear(top)


def arm_quiet_launch(window: Any) -> None:
    """Hold a background launch until the person actually uses the window.

    The flag drops on the first ``ApplicationActive``, same as before, and
    on a click in this window, which is the user taking it.
    """
    if window is None:
        return
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    if app is None:
        return

    def _clear_on_active(state: object) -> None:
        if state != Qt.ApplicationState.ApplicationActive:
            return
        release_quiet_launch(window)

    setattr(window, _QUIET_CLEAR, _clear_on_active)
    app.applicationStateChanged.connect(_clear_on_active)
    _install_quiet_click(app, window)


def _disconnect_quiet_clear(window: Any) -> None:
    handler = getattr(window, _QUIET_CLEAR, None)
    if handler is None:
        return
    try:
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance()
        if app is not None:
            app.applicationStateChanged.disconnect(handler)
    except (RuntimeError, TypeError):
        pass
    try:
        delattr(window, _QUIET_CLEAR)
    except (AttributeError, RuntimeError):
        pass
    _remove_quiet_click(window)


def _install_quiet_click(app: Any, window: Any) -> None:
    """A click on this quiet window is the user asking for it."""
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QWidget

    class _QuietClick(QObject):
        def eventFilter(self, obj, event):  # type: ignore[override]
            try:
                if event.type() != QEvent.Type.MouseButtonPress:
                    return False
                if not isinstance(obj, QWidget):
                    return False
                top = obj.window()
                if top is not window and obj is not window:
                    return False
                if not quiet_launch(window):
                    return False
                # Release first so activate is not refused by NOACTIVATE.
                release_quiet_launch(window)
                activate = getattr(window, "activateWindow", None)
                if callable(activate):
                    activate()
            except RuntimeError:
                return False
            return False

    filt = _QuietClick(app)
    app.installEventFilter(filt)
    setattr(window, _QUIET_FILTER, filt)


def _remove_quiet_click(window: Any) -> None:
    filt = getattr(window, _QUIET_FILTER, None)
    if filt is None:
        return
    try:
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance()
        if app is not None:
            app.removeEventFilter(filt)
    except (RuntimeError, TypeError):
        pass
    try:
        delattr(window, _QUIET_FILTER)
    except (AttributeError, RuntimeError):
        pass


def _lock_foreground() -> None:
    _lock_foreground_mode(_LSFW_LOCK)


def _unlock_foreground() -> None:
    _lock_foreground_mode(_LSFW_UNLOCK)


def _lock_foreground_mode(mode: int) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.LockSetForegroundWindow(int(mode))
    except Exception:
        # No user32, or Windows refused the lock. The quiet show still
        # does not call SetForegroundWindow, so a failed lock is not a steal.
        return


def _set_no_activate_style(widget: Any, on: bool) -> None:
    """Toggle the no-activate window bit. Fakes without setWindowFlag stay as they are."""
    setter = getattr(widget, "setWindowFlag", None)
    if not callable(setter):
        return
    from PySide6.QtCore import Qt

    flag = Qt.WindowType.WindowDoesNotAcceptFocus
    try:
        has = bool(widget.windowFlags() & flag)
    except (AttributeError, TypeError, RuntimeError):
        has = False
    if has == bool(on):
        return
    setter(flag, bool(on))


def show_without_activating(widget: Any) -> None:
    """Map the widget without taking keyboard focus or the foreground.

    Sets ``WA_ShowWithoutActivating`` for the ``show()`` call, then restores
    the previous value. Never calls ``raise_``, ``activateWindow``,
    ``SetForegroundWindow``, or ``AllowSetForegroundWindow``.

    A quiet launch also sets ``WindowDoesNotAcceptFocus`` before ``show()``
    and drops the maximized bit. Qt maps a maximized window with
    ``SW_SHOWMAXIMIZED``, which activates and comes to the front. A quiet
    launch does not put that maximized rect back. A user launch still
    maximizes without activating.
    """
    if widget is None:
        return
    from PySide6.QtCore import Qt

    quiet = quiet_launch(widget)
    wants_max = bool(widget.windowState() & Qt.WindowState.WindowMaximized)
    if quiet and wants_max:
        widget.setWindowState(widget.windowState() & ~Qt.WindowState.WindowMaximized)
    if quiet:
        _lock_foreground()
        _set_no_activate_style(widget, True)
    attr = Qt.WidgetAttribute.WA_ShowWithoutActivating
    previous = bool(widget.testAttribute(attr))
    widget.setAttribute(attr, True)
    try:
        widget.show()
    finally:
        widget.setAttribute(attr, previous)
    # Quiet launch must not put the maximized rect back. That restore is
    # what comes to the front. A user launch still maximizes without activate.
    if wants_max and not quiet:
        _win32_maximize_inactive(widget)


def claim_foreground(widget: Any) -> None:
    """Raise this plate (and its owner) in front of other apps."""
    if widget is None:
        return
    window_fn = getattr(widget, "window", None)
    top = window_fn() if callable(window_fn) else widget
    if top is None:
        return
    owner = _owner_window(top)
    # A click is the user asking. Unlock before SetForegroundWindow or the
    # quiet lock keeps the plate behind the other app.
    release_quiet_launch(top)
    if owner is not None:
        release_quiet_launch(owner)
    # Another app in front: raise the glass first so Windows will let the
    # owned tile come forward. Already ours: do not raise the owner — a
    # maximized glass climbs over the inbox and the click looks dead.
    if owner is not None and not process_owns_foreground():
        owner.raise_()
    top.raise_()
    activate = getattr(top, "activateWindow", None)
    if callable(activate):
        activate()
    _win32_foreground(top)


def _owner_window(top: Any) -> Any | None:
    parent_fn = getattr(top, "parentWidget", None)
    if not callable(parent_fn):
        return None
    host = parent_fn()
    if host is None:
        return None
    window_fn = getattr(host, "window", None)
    owner = window_fn() if callable(window_fn) else host
    if owner is None or owner is top:
        return None
    return owner


def _win32_maximize_inactive(widget: Any) -> None:
    """Maximize without ShowWindow(SW_MAXIMIZE), which would activate.

    Style bit plus a no-activate move gives a real maximized window, and
    Windows then reports SIZE_MAXIMIZED so Qt's state follows.
    """
    if sys.platform != "win32":
        return
    try:
        from PySide6.QtGui import QGuiApplication

        if QGuiApplication.platformName() != "windows":
            return
        from arelis.ui.window_resize import top_level_hwnd, with_no_activate

        hwnd = top_level_hwnd(widget)
        if not hwnd:
            return
        import ctypes
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        user32 = ctypes.windll.user32
        if user32.IsZoomed(hwnd):
            return
        hmon = user32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not hmon or not user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return
        style = user32.GetWindowLongW(hwnd, _GWL_STYLE)
        # Style first so Windows keeps the current normal rect as restore.
        # SW_MAXIMIZE activates; this plus a no-activate SetWindowPos does not.
        user32.SetWindowLongW(hwnd, _GWL_STYLE, style | _WS_MAXIMIZE)
        work = info.rcWork
        user32.SetWindowPos(
            hwnd,
            None,
            int(work.left),
            int(work.top),
            int(work.right - work.left),
            int(work.bottom - work.top),
            with_no_activate(
                _SWP_NOZORDER | _SWP_FRAMECHANGED | _SWP_NOOWNERZORDER
            ),
        )
    # Best effort on purpose: if a win32 call fails the window is already
    # shown without focus at its normal size, which is safe, just not maximized.
    except Exception:
        return


def _win32_foreground(widget: Any) -> None:
    if sys.platform != "win32":
        return
    try:
        from PySide6.QtGui import QGuiApplication

        if QGuiApplication.platformName() != "windows":
            return
        from arelis.ui.window_resize import top_level_hwnd

        hwnd = top_level_hwnd(widget)
        if not hwnd:
            return
        import ctypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        if user32.SetForegroundWindow(hwnd):
            user32.BringWindowToTop(hwnd)
            return
        fg = user32.GetForegroundWindow()
        if not fg or int(fg) == hwnd:
            user32.BringWindowToTop(hwnd)
            return
        fg_tid = int(user32.GetWindowThreadProcessId(fg, None))
        cur_tid = int(kernel32.GetCurrentThreadId())
        attached = False
        if fg_tid and fg_tid != cur_tid:
            attached = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(cur_tid, fg_tid, False)
    except Exception:
        return


def _install_app_filter() -> None:
    """One filter: a click on a child still raises the tile behind another app."""
    try:
        from PySide6.QtCore import QEvent, QObject
        from PySide6.QtWidgets import QApplication, QWidget
    except Exception:
        return
    app = QApplication.instance()
    if app is None or getattr(app, _APP_FILTER, None) is not None:
        return

    class _ClickToFront(QObject):
        def eventFilter(self, obj, event):  # type: ignore[override]
            if event.type() != QEvent.Type.MouseButtonPress:
                return False
            if not isinstance(obj, QWidget):
                return False
            top = obj.window()
            if not accepts_click_to_front(top):
                return False
            if process_owns_foreground() and top.isActiveWindow():
                return False
            claim_foreground(top)
            return False

    filt = _ClickToFront(app)
    app.installEventFilter(filt)
    setattr(app, _APP_FILTER, filt)
    _install_native_filter(app)


def _install_native_filter(app: Any) -> None:
    """WM_MOUSEACTIVATE on every marked plate, including those without nativeEvent."""
    if sys.platform != "win32":
        return
    if getattr(app, _NATIVE_FILTER, None) is not None:
        return
    try:
        from PySide6.QtCore import QAbstractNativeEventFilter
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QWidget

        from arelis.ui.window_resize import MA_ACTIVATE, WM_MOUSEACTIVATE, win32_msg
    except Exception:
        return
    if QGuiApplication.platformName() != "windows":
        return

    class _NativeFront(QAbstractNativeEventFilter):
        def nativeEventFilter(self, eventType, message):  # type: ignore[override]
            msg = win32_msg(eventType, message)
            if msg is None or msg.message != WM_MOUSEACTIVATE:
                return False
            hwnd = int(getattr(msg, "hWnd", 0) or getattr(msg, "hwnd", 0) or 0)
            if not hwnd:
                return False
            widget = QWidget.find(hwnd)
            if widget is None:
                return False
            top = widget.window()
            if not accepts_click_to_front(top):
                return False
            if not process_owns_foreground() or not top.isActiveWindow():
                claim_foreground(top)
            return True, MA_ACTIVATE

    filt = _NativeFront()
    app.installNativeEventFilter(filt)
    setattr(app, _NATIVE_FILTER, filt)


def flash_taskbar(widget: Any) -> None:
    """Flash this window's taskbar button until they look at us.

    ``QApplication.alert`` skips when Qt still thinks we are active, which
    is the same lie that hid the SMS pulse. ``FlashWindowEx`` does not.
    """
    if sys.platform != "win32":
        _qt_alert(widget)
        return
    try:
        import ctypes
        from ctypes import wintypes

        window = getattr(widget, "window", None)
        if callable(window) and window() is not widget:
            return
        hwnd = int(widget.winId())
        if not hwnd:
            return

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("hwnd", wintypes.HWND),
                ("dwFlags", wintypes.DWORD),
                ("uCount", wintypes.UINT),
                ("dwTimeout", wintypes.DWORD),
            ]

        info = FLASHWINFO()
        info.cbSize = ctypes.sizeof(FLASHWINFO)
        info.hwnd = hwnd
        info.dwFlags = _FLASHW_TRAY | _FLASHW_TIMERNOFG
        info.uCount = 0
        info.dwTimeout = 0
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
    except Exception:
        _qt_alert(widget)


def _qt_alert(widget: Any) -> None:
    try:
        from PySide6.QtWidgets import QApplication

        QApplication.alert(widget, 0)
    except Exception:
        return
