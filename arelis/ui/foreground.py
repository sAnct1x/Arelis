"""Whether this process owns the OS foreground window.

Qt's ``isActiveWindow()`` and ``applicationState()`` can stay "active" after
you click into another app — common on Windows with Tool windows. The SMS
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

# Set on every sealed plate and floating dock so a click on a child still
# raises the tile, not only a click on empty chrome.
_CLICK_TO_FRONT = "_arelis_click_to_front"
_APP_FILTER = "_arelis_click_to_front_filter"
_NATIVE_FILTER = "_arelis_native_front_filter"


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


def claim_foreground(widget: Any) -> None:
    """Raise this plate (and its owner) in front of other apps."""
    if widget is None:
        return
    window_fn = getattr(widget, "window", None)
    top = window_fn() if callable(window_fn) else widget
    if top is None:
        return
    owner = _owner_window(top)
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
