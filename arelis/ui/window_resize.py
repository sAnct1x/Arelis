"""Edge/corner resize for frameless windows on Windows.

Uses WM_NCHITTEST so the OS owns the drag — same feel as a normal title-bar
window, without fighting child widgets for mouse events. On show we add
WS_THICKFRAME and zero out WM_NCCALCSIZE so Windows treats the window as
resizable while it still paints frameless.
"""
from __future__ import annotations

import sys
from ctypes import c_short
from typing import Any

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QWidget

# windll and wintypes exist only on Windows. Importing them here used to make
# `import arelis.ui.window_resize` fail on Linux before any function ran, which
# aborted pytest collection on every Ubuntu CI leg. The portable ctypes names
# stay; the Win32 ones are imported inside the functions that already return
# on anything other than win32.

WM_NCHITTEST = 0x0084
WM_NCCALCSIZE = 0x0083
WM_GETMINMAXINFO = 0x0024

# What WM_NCCALCSIZE hands back when wParam is TRUE.
#
# Returning 0 accepts the default valid-rects behaviour: Windows treats the old
# client area as still good and blits it into the new one, then invalidates only
# what the blit could not fill. That is a copy of the previous frame, placed at
# the new client origin, and nothing in this window can paint over it — the
# interior is transparent from StageBackground down, and the only widget that
# lays down pixels is ArelisWindow itself, which Qt only repaints where it
# believes something changed. So the smear stays, offset by however far the
# content moved. That is the ghost.
#
# WVR_REDRAW says "none of the old client is valid", so the whole thing is
# invalidated and Qt is asked to repaint it instead.
WVR_HREDRAW = 0x0100
WVR_VREDRAW = 0x0200
WVR_REDRAW = WVR_HREDRAW | WVR_VREDRAW

HTTRANSPARENT = -1
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
SWP_NOACTIVATE = 0x0010
SWP_NOSENDCHANGING = 0x0400

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

# Logical pixels; scaled by devicePixelRatio at hit-test time.
_BORDER = 10

# Qt's QWIDGETSIZE_MAX. PySide6 6.11 does not export the name.
_WIDGET_SIZE_MAX = 16777215


def configure_native_windows() -> None:
    """Stop Qt promoting every sibling when one widget goes native.

    Must run before QApplication is constructed. A native child under this
    window is composited twice — once in the parent backing store, once as its
    own HWND, offset by the child's origin. That is the ghost. This attribute
    keeps a single winId() from cascading to the toolbar, the docks, the stage
    and the splitters.
    """
    QApplication.setAttribute(
        Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings, True
    )


def _is_top_level(widget: QWidget) -> bool:
    """True only for a widget that already is its own window.

    A QDockWidget that is floating qualifies. A docked one does not — its
    window() is the main glass, and calling winId() on it would create a child
    HWND.
    """
    try:
        return widget.window() is widget
    except Exception:
        return False


def top_level_hwnd(widget: QWidget) -> int | None:
    """HWND of a top-level window, or None.

    winId() on a child creates a native window and is how the ghost starts.
    Callers that need an HWND for DWM, FlashWindow or WS_THICKFRAME go through
    here so a docked panel can never be the one that is asked.
    """
    if not _is_top_level(widget):
        return None
    try:
        hwnd = int(widget.winId())
    except Exception:
        return None
    return hwnd or None


def release_child_hwnd(widget: QWidget) -> None:
    """Drop a child HWND so the parent paints this widget once."""
    if _is_top_level(widget):
        return
    widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, False)
    if not widget.internalWinId():
        return
    handle = widget.windowHandle()
    if handle is not None:
        handle.destroy()


def release_native_children(root: QWidget) -> None:
    """Destroy every native child under root; leave top-level windows alone."""
    release_child_hwnd(root)
    for child in root.findChildren(QWidget):
        release_child_hwnd(child)


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
    hwnd = top_level_hwnd(widget)
    if hwnd is None:
        return
    from ctypes import windll

    windll.user32.RedrawWindow(
        hwnd,
        None,
        None,
        RDW_INVALIDATE | RDW_ERASE | RDW_FRAME | RDW_ALLCHILDREN,
    )


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


def win32_msg(event_type: Any, message: Any) -> Any:
    if _event_type_bytes(event_type) != b"windows_generic_MSG":
        return None
    return _msg_from_message(message)


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


def _geo_matches(got: QRect, want: QRect) -> bool:
    return (
        abs(got.x() - want.x()) <= 8
        and abs(got.y() - want.y()) <= 8
        and abs(got.width() - want.width()) <= 24
        and abs(got.height() - want.height()) <= 24
    )


def _virtual_desktop_native() -> tuple[int, int, int, int]:
    """Virtual desktop x, y, w, h in physical pixels."""
    from ctypes import windll

    user32 = windll.user32
    return (
        int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN)),
        int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN)),
        int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)),
        int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)),
    )


def _fill_minmax_info(info: Any) -> None:
    """Let a frameless HWND span the whole row. Default max track is one desk."""
    vx, vy, vw, vh = _virtual_desktop_native()
    info.ptMaxPosition.x = vx
    info.ptMaxPosition.y = vy
    info.ptMaxSize.x = vw
    info.ptMaxSize.y = vh
    info.ptMaxTrackSize.x = vw
    info.ptMaxTrackSize.y = vh
    info.ptMinTrackSize.x = 1
    info.ptMinTrackSize.y = 1


def _native_place_rect(rect: QRect, dpr: float) -> tuple[int, int, int, int]:
    scale = max(0.25, float(dpr))
    return (
        round(rect.x() * scale),
        round(rect.y() * scale),
        round(rect.width() * scale),
        round(rect.height() * scale),
    )


def _place_scale(handle: Any) -> float:
    """Physical / logical. Virtual desktop, not the HWND's current monitor."""
    try:
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        virt = screen.virtualGeometry() if screen is not None else None
        if virt is not None and virt.width() > 0:
            _vx, _vy, vw, _vh = _virtual_desktop_native()
            if vw > 0:
                sx = vw / float(virt.width())
                if 0.5 <= sx <= 4.0:
                    return sx
    except Exception:
        pass
    if handle is not None:
        try:
            return max(1.0, float(handle.devicePixelRatio()))
        except Exception:
            pass
    return 1.0


def _set_hwnd_rect(hwnd: int, rect: QRect, scale: float) -> None:
    from ctypes import windll

    nx, ny, nw, nh = _native_place_rect(rect, scale)
    windll.user32.SetWindowPos(
        hwnd,
        0,
        nx,
        ny,
        nw,
        nh,
        SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOSENDCHANGING,
    )


def _hwnd_logical_rect(hwnd: int, scale: float) -> QRect | None:
    from ctypes import byref, windll, wintypes

    rc = wintypes.RECT()
    if not windll.user32.GetWindowRect(hwnd, byref(rc)):
        return None
    s = max(0.25, float(scale))
    return QRect(
        round(rc.left / s),
        round(rc.top / s),
        round((rc.right - rc.left) / s),
        round((rc.bottom - rc.top) / s),
    )


def _qt_set_rect(widget: QWidget, handle: Any, rect: QRect) -> None:
    if handle is not None:
        handle.setGeometry(rect)
    widget.setGeometry(rect)


def _step_rects(current: QRect, want: QRect) -> list[QRect]:
    """Origin jump: land first, then grow/shrink along +x. One shot otherwise.

    Windows treats a leftward origin change as a move onto that monitor, then
    clamps width to that desk. Growing right from the new origin is allowed.
    """
    if not current.isValid():
        return [want]
    dx = want.x() - current.x()
    if dx < -8:
        return [
            QRect(want.x(), want.y(), max(1, current.width()), want.height()),
            want,
        ]
    if dx > 8:
        return [
            QRect(current.x(), want.y(), want.width(), want.height()),
            want,
        ]
    return [want]


def place_frameless_rect(widget: QWidget, rect: QRect) -> bool:
    """Put a frameless HWND on a multi-desk rect. Qt setGeometry often only moves."""
    if not rect.isValid():
        return False
    from PySide6.QtGui import QGuiApplication

    try:
        widget.setMinimumSize(1, 1)
        widget.setMaximumSize(_WIDGET_SIZE_MAX, _WIDGET_SIZE_MAX)
        if widget.isMaximized() or widget.isFullScreen():
            widget.showNormal()
        handle = widget.windowHandle()
        if handle is not None:
            handle.setMinimumSize(QSize(1, 1))
            handle.setMaximumSize(QSize(_WIDGET_SIZE_MAX, _WIDGET_SIZE_MAX))
        if QGuiApplication.platformName() != "windows":
            for step in _step_rects(widget.geometry(), rect):
                _qt_set_rect(widget, handle, step)
            _qt_set_rect(widget, handle, rect)
            return _geo_matches(widget.geometry(), rect)
        hwnd = top_level_hwnd(widget)
        if hwnd is None:
            for step in _step_rects(widget.geometry(), rect):
                _qt_set_rect(widget, handle, step)
            return _geo_matches(widget.geometry(), rect)
        scale = _place_scale(handle)
        current = _hwnd_logical_rect(hwnd, scale) or widget.geometry()
        for step in _step_rects(current, rect):
            _set_hwnd_rect(hwnd, step, scale)
        _set_hwnd_rect(hwnd, rect, scale)
        # HWND first. Qt setGeometry *before* that is the grow-left clamp.
        QGuiApplication.processEvents()
        if not _geo_matches(widget.geometry(), rect):
            # Cache sync only. If the native rect already matches, this is a
            # no-op at Win32; if Qt then clamps, put the HWND back.
            _qt_set_rect(widget, handle, rect)
            native = _hwnd_logical_rect(hwnd, scale)
            if native is not None and not _geo_matches(native, rect):
                _set_hwnd_rect(hwnd, rect, scale)
                QGuiApplication.processEvents()
        native = _hwnd_logical_rect(hwnd, scale)
        if native is not None and _geo_matches(native, rect):
            return True
        return _geo_matches(widget.geometry(), rect)
    except Exception:
        return _geo_matches(widget.geometry(), rect)


def enable_win32_resize_frame(widget: QWidget) -> None:
    """Add WS_THICKFRAME so Windows will deliver resize hit-tests / snap."""
    if sys.platform != "win32":
        return
    hwnd = top_level_hwnd(widget)
    if hwnd is None:
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

    if msg.message == WM_GETMINMAXINFO and msg.lParam:
        from ctypes import Structure, c_long

        class _Point(Structure):
            _fields_ = [("x", c_long), ("y", c_long)]

        class _MinMaxInfo(Structure):
            _fields_ = [
                ("ptReserved", _Point),
                ("ptMaxSize", _Point),
                ("ptMaxPosition", _Point),
                ("ptMinTrackSize", _Point),
                ("ptMaxTrackSize", _Point),
            ]

        try:
            info = _MinMaxInfo.from_address(int(msg.lParam))
            _fill_minmax_info(info)
        except (TypeError, ValueError, OverflowError):
            return None
        return True, 0

    if msg.message == WM_NCCALCSIZE and msg.wParam:
        # Leaving rgrc[0] alone is what makes the client area fill the window:
        # the glass keeps its look with no native caption or border, while
        # WS_THICKFRAME still enables resize and snap. WVR_REDRAW is the part
        # that matters for ghosting — see the constant.
        return True, WVR_REDRAW

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
