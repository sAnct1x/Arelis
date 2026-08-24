"""Whether this process owns the OS foreground window.

Qt's ``isActiveWindow()`` and ``applicationState()`` can stay "active" after
you click into another app — common on Windows with Tool windows. The SMS
tile then skipped its attention rim. ``GetForegroundWindow`` is the actual
"are they looking at us?"
"""

from __future__ import annotations

import os
import sys
from typing import Any

# Flash the taskbar button until the window comes to the foreground.
_FLASHW_TRAY = 0x00000002
_FLASHW_TIMERNOFG = 0x0000000C


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
