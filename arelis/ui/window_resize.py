"""Edge/corner resize for frameless windows on Windows.

Uses WM_NCHITTEST so the OS owns the drag — same feel as a normal title-bar
window, without fighting child widgets for mouse events. On show we add
WS_THICKFRAME and zero out WM_NCCALCSIZE so Windows treats the window as
resizable while it still paints frameless.
"""
from __future__ import annotations

import sys
from ctypes import byref, c_int, c_short, sizeof
from typing import Any

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QWidget

# windll and wintypes exist only on Windows. Importing them here used to make
# `import arelis.ui.window_resize` fail on Linux before any function ran, which
# aborted pytest collection on every Ubuntu CI leg. The portable ctypes names
# stay; the Win32 ones are imported inside the functions that already return
# on anything other than win32.

WM_NCHITTEST = 0x0084
WM_NCCALCSIZE = 0x0083
HTCLIENT = 1
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17

GWL_STYLE = -16
# GWLP_HWNDPARENT clears the owner so floating docks don't raise with the main window.
GWLP_HWNDPARENT = -8

RDW_INVALIDATE = 0x0001
RDW_ERASE = 0x0004
RDW_FRAME = 0x0400
RDW_ALLCHILDREN = 0x0080

WS_THICKFRAME = 0x00040000
WS_MAXIMIZEBOX = 0x00010000
WS_MINIMIZEBOX = 0x00020000
WS_SYSMENU = 0x00080000
SWP_FRAMECHANGED = 0x0020
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004

# DWM immersive dark mode (Win10 1903+ uses 20; some builds used 19).
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 = 19

# Logical pixels; scaled by devicePixelRatio at hit-test time.
_BORDER = 10


def detach_owned_window(widget: QWidget) -> None:
    """Deprecated: clearing HWND owner spawned translucent ghost dock windows.

    Kept as a no-op so any stray callers stay safe. Z-order independence needs a
    different approach than SetWindowLongPtr(GWLP_HWNDPARENT, 0).
    """
    return


def invalidate_window_surface(widget: QWidget) -> None:
    """Force Windows to hand this window a paint before it presents it again.

    A frameless widget with WA_TranslucentBackground is a layered window, and Qt
    uploads its pixels with UpdateLayeredWindow. The uploaded bitmap belongs to
    the OS, not to Qt, so it survives ShowWindow(SW_HIDE) and is presented again
    the instant the window comes back — before any paintEvent has run. Whatever
    the glass looked like when it went to the tray is therefore what appears
    first, which is wrong every time something changed while it was away: a text
    arrived, the status line moved, the window is a different size than it was.

    Marking the whole window and every child dirty is the point. Qt flushes only
    the region it believes changed, which on a re-show is nothing, so the parts
    of the layered bitmap Qt has no reason to touch are the parts that keep the
    old picture. This asks for all of it back.

    Deliberately not RDW_UPDATENOW: a synchronous WM_PAINT from inside a show
    means painting re-entrantly into a window Qt is still mapping, and one frame
    of latency is not worth finding out what that does.
    """
    if sys.platform != "win32":
        return
    if not widget.isVisible():
        return
    # winId() is only an HWND under the windows backend. The offscreen platform
    # the widget tests run on hands back an internal id, and passing that to
    # user32 would be a syscall on a number that means nothing.
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.platformName() != "windows":
        return
    try:
        hwnd = int(widget.winId())
    except Exception:
        return
    from ctypes import windll

    windll.user32.RedrawWindow(
        hwnd,
        None,
        None,
        RDW_INVALIDATE | RDW_ERASE | RDW_FRAME | RDW_ALLCHILDREN,
    )


def enable_dark_title_bar(widget: QWidget) -> None:
    """Match floating dock captions to the dark glass shell (Windows DWM)."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
    except Exception:
        return
    from ctypes import windll

    value = c_int(1)
    dwm = windll.dwmapi
    for attr in (
        DWMWA_USE_IMMERSIVE_DARK_MODE,
        DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1,
    ):
        try:
            dwm.DwmSetWindowAttribute(hwnd, attr, byref(value), sizeof(value))
        except Exception:
            continue


def _event_type_bytes(event_type: Any) -> bytes:
    if isinstance(event_type, (bytes, bytearray)):
        return bytes(event_type)
    # QByteArray
    try:
        return bytes(event_type.data())  # type: ignore[attr-defined]
    except Exception:
        return bytes(event_type)


def _msg_from_message(message: Any) -> Any:
    try:
        addr = int(message)
    except (TypeError, ValueError, OverflowError):
        try:
            addr = message.__int__()  # type: ignore[attr-defined]
        except Exception:
            return None
    from ctypes import wintypes

    try:
        return wintypes.MSG.from_address(addr)
    except (TypeError, ValueError, OverflowError):
        return None


def _border_px(widget: QWidget, border: int) -> int:
    handle = widget.windowHandle()
    dpr = float(handle.devicePixelRatio() if handle is not None else 1.0)
    return max(6, round(border * max(1.0, dpr)))


def hit_test_resize_at(
    widget: QWidget,
    global_x: int,
    global_y: int,
    *,
    border: int = _BORDER,
) -> int | None:
    """Return a Win32 HT* code for a screen point, else None."""
    if widget.isMaximized() or widget.isFullScreen():
        return None
    geo = widget.frameGeometry()
    # frameGeometry is in logical coords; WM_NCHITTEST lParam is physical on
    # per-monitor DPI. Prefer mapping through the window handle when present.
    handle = widget.windowHandle()
    if handle is not None:
        try:
            # Map physical screen point → logical widget coords.
            local = handle.mapFromGlobal(QPoint(global_x, global_y))
            x, y = local.x(), local.y()
            w, h = widget.width(), widget.height()
        except Exception:
            x = global_x - geo.x()
            y = global_y - geo.y()
            w, h = geo.width(), geo.height()
    else:
        x = global_x - geo.x()
        y = global_y - geo.y()
        w, h = geo.width(), geo.height()

    margin = _border_px(widget, border)
    # Use logical border for mapped local coords (already DPR-adjusted by Qt).
    if handle is not None:
        margin = max(6, int(border))

    left = x < margin
    right = x >= w - margin
    top = y < margin
    bottom = y >= h - margin
    if top and left:
        return HTTOPLEFT
    if top and right:
        return HTTOPRIGHT
    if bottom and left:
        return HTBOTTOMLEFT
    if bottom and right:
        return HTBOTTOMRIGHT
    if left:
        return HTLEFT
    if right:
        return HTRIGHT
    if top:
        return HTTOP
    if bottom:
        return HTBOTTOM
    return None


def hit_test_resize(widget: QWidget, *, border: int = _BORDER) -> int | None:
    """Return a Win32 HT* code when the cursor is on a resize edge, else None."""
    pos = QCursor.pos()
    return hit_test_resize_at(widget, pos.x(), pos.y(), border=border)


def enable_win32_resize_frame(widget: QWidget) -> None:
    """Add WS_THICKFRAME so Windows will deliver resize hit-tests / snap."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
    except Exception:
        return
    from ctypes import windll

    user32 = windll.user32
    style = int(user32.GetWindowLongW(hwnd, GWL_STYLE))
    new_style = style | WS_THICKFRAME | WS_MAXIMIZEBOX | WS_MINIMIZEBOX | WS_SYSMENU
    if new_style == style:
        return
    user32.SetWindowLongW(hwnd, GWL_STYLE, new_style)
    user32.SetWindowPos(
        hwnd,
        0,
        0,
        0,
        0,
        0,
        SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER,
    )


def handle_native_resize(
    widget: QWidget,
    event_type: Any,
    message: Any,
    *,
    border: int = _BORDER,
) -> tuple[bool, int] | None:
    """Handle WM_NCCALCSIZE / WM_NCHITTEST for frameless resize.

    Returns (True, result) when handled, else None so the caller can fall
    through to super().
    """
    if sys.platform != "win32":
        return None
    if _event_type_bytes(event_type) != b"windows_generic_MSG":
        return None
    msg = _msg_from_message(message)
    if msg is None:
        return None

    if msg.message == WM_NCCALCSIZE and msg.wParam:
        # Client area fills the window — keep the glass look with no native
        # caption/border chrome, while WS_THICKFRAME still enables resize.
        return True, 0

    if msg.message != WM_NCHITTEST:
        return None

    # Prefer QCursor.pos() (Qt logical / virtual-desktop coords). Raw lParam is
    # physical on some DPI setups and mis-maps against frameGeometry().
    ht = hit_test_resize(widget, border=border)
    if ht is None:
        # Fallback: signed screen coords from lParam (multi-monitor safe).
        screen_x = int(c_short(msg.lParam & 0xFFFF).value)
        screen_y = int(c_short((msg.lParam >> 16) & 0xFFFF).value)
        ht = hit_test_resize_at(widget, screen_x, screen_y, border=border)
    if ht is None:
        return None
    return True, ht


def cursor_for_hit(ht: int | None) -> Qt.CursorShape | None:
    """Qt cursor shape for a resize HT* code (hover feedback)."""
    if ht is None:
        return None
    return {
        HTLEFT: Qt.CursorShape.SizeHorCursor,
        HTRIGHT: Qt.CursorShape.SizeHorCursor,
        HTTOP: Qt.CursorShape.SizeVerCursor,
        HTBOTTOM: Qt.CursorShape.SizeVerCursor,
        HTTOPLEFT: Qt.CursorShape.SizeFDiagCursor,
        HTBOTTOMRIGHT: Qt.CursorShape.SizeFDiagCursor,
        HTTOPRIGHT: Qt.CursorShape.SizeBDiagCursor,
        HTBOTTOMLEFT: Qt.CursorShape.SizeBDiagCursor,
    }.get(ht)


def try_system_resize(widget: QWidget, global_pos: QPoint, *, border: int = _BORDER) -> bool:
    """Fallback: startSystemResize when pressing near an edge."""
    if widget.isMaximized() or widget.isFullScreen():
        return False
    handle = widget.windowHandle()
    if handle is None:
        return False
    ht = hit_test_resize_at(widget, global_pos.x(), global_pos.y(), border=border)
    if ht is None:
        return False
    edges = Qt.Edge(0)
    if ht in {HTLEFT, HTTOPLEFT, HTBOTTOMLEFT}:
        edges |= Qt.Edge.LeftEdge
    if ht in {HTRIGHT, HTTOPRIGHT, HTBOTTOMRIGHT}:
        edges |= Qt.Edge.RightEdge
    if ht in {HTTOP, HTTOPLEFT, HTTOPRIGHT}:
        edges |= Qt.Edge.TopEdge
    if ht in {HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT}:
        edges |= Qt.Edge.BottomEdge
    if edges == Qt.Edge(0):
        return False
    try:
        return bool(handle.startSystemResize(edges))
    except Exception:
        return False
