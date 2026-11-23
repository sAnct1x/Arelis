"""List and focus top-level windows. Windows-only."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

_READER_ALIASES = {
    "book": ("kindle", "kobo", "books", "adobe", "acrobat", "sumatra"),
    "textbook": ("kindle", "adobe", "acrobat", "sumatra"),
    "pdf": ("adobe", "acrobat", "sumatra", "edge"),
    "homework": ("adobe", "acrobat", "kindle", "word", "onenote"),
    "worksheet": ("adobe", "acrobat", "word", "onenote"),
}


@dataclass(frozen=True)
class DeskWindow:
    hwnd: int
    title: str
    pid: int


def list_windows() -> list[DeskWindow]:
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[DeskWindow] = []
    gw_owner = 4
    ws_ex_toolwindow = 0x00000080
    gwl_exstyle = -20

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _each(hwnd: int, _lp: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindow(hwnd, gw_owner):
            return True
        try:
            ex = user32.GetWindowLongW(hwnd, gwl_exstyle)
        except Exception:
            ex = 0
        if ex & ws_ex_toolwindow:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = (buf.value or "").strip()
        if not title:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        found.append(DeskWindow(hwnd=int(hwnd), title=title, pid=int(pid.value)))
        return True

    user32.EnumWindows(_each, 0)
    return found


def format_windows(rows: list[DeskWindow], *, limit: int = 40) -> str:
    if not rows:
        return "No visible windows."
    lines = []
    for i, row in enumerate(rows[:limit], start=1):
        lines.append(f"{i}|{row.title}")
    if len(rows) > limit:
        lines.append(f"… {len(rows) - limit} more")
    return "\n".join(lines)


def match_window(target: str, rows: list[DeskWindow] | None = None) -> DeskWindow | None:
    needle = (target or "").strip().lower()
    if not needle:
        return None
    rows = rows if rows is not None else list_windows()
    exact = [w for w in rows if w.title.lower() == needle]
    if exact:
        return exact[0]
    hits = [w for w in rows if needle in w.title.lower()]
    return hits[0] if hits else None


def match_reader_window(
    target: str, rows: list[DeskWindow] | None = None
) -> DeskWindow | None:
    """Title match, then a small reader alias (book → Kindle / Acrobat)."""
    rows = rows if rows is not None else list_windows()
    hit = match_window(target, rows)
    if hit is not None:
        return hit
    key = re.sub(r"^(?:the|my|this|that)\s+", "", (target or "").strip().lower())
    for alias in _READER_ALIASES.get(key, ()):
        hit = match_window(alias, rows)
        if hit is not None:
            return hit
    return None


def foreground_hwnd() -> int:
    if sys.platform != "win32":
        return 0
    import ctypes

    return int(ctypes.windll.user32.GetForegroundWindow() or 0)


def foreground_title() -> str:
    if sys.platform != "win32":
        return ""
    import ctypes

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return (buf.value or "").strip()


def focus_window(hwnd: int) -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    sw_restore = 9
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, sw_restore)
    fg = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg, None)
    cur_tid = kernel32.GetCurrentThreadId()
    if fg_tid and cur_tid and fg_tid != cur_tid:
        user32.AttachThreadInput(cur_tid, fg_tid, True)
    ok = bool(user32.SetForegroundWindow(wintypes.HWND(hwnd)))
    if fg_tid and cur_tid and fg_tid != cur_tid:
        user32.AttachThreadInput(cur_tid, fg_tid, False)
    return ok


def arrange_window(hwnd: int, layout: str) -> bool:
    """Maximize, minimize, restore, or snap a window to the left/right half of its monitor."""
    if sys.platform != "win32" or not hwnd:
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    mode = (layout or "").strip().lower().replace("-", "_")
    sw_maximize = 3
    sw_minimize = 6
    sw_restore = 9
    if mode == "maximize":
        user32.ShowWindow(wintypes.HWND(hwnd), sw_maximize)
        return True
    if mode == "minimize":
        user32.ShowWindow(wintypes.HWND(hwnd), sw_minimize)
        return True
    if mode == "restore":
        user32.ShowWindow(wintypes.HWND(hwnd), sw_restore)
        return True
    if mode not in {"snap_left", "snap_right", "left", "right"}:
        return False

    class _Rect(ctypes.Structure):
        _fields_ = (
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.Bottom if hasattr(wintypes, "Bottom") else wintypes.LONG),
        )

    class _MonitorInfo(ctypes.Structure):
        _fields_ = (
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", _Rect),
            ("rcWork", _Rect),
            ("dwFlags", wintypes.DWORD),
        )

    user32.ShowWindow(wintypes.HWND(hwnd), sw_restore)
    monitor_default_to_nearest = 2
    hmon = user32.MonitorFromWindow(wintypes.HWND(hwnd), monitor_default_to_nearest)
    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(_MonitorInfo)
    if hmon and user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
        wx = int(info.rcWork.left)
        wy = int(info.rcWork.top)
        ww = int(info.rcWork.right - info.rcWork.left)
        wh = int(info.rcWork.bottom - info.rcWork.top)
    else:
        wx, wy = 0, 0
        ww = int(user32.GetSystemMetrics(0) or 1920)
        wh = int(user32.GetSystemMetrics(1) or 1080)
    if ww <= 0 or wh <= 0:
        return False
    half_w = ww // 2
    x = wx if mode in {"snap_left", "left"} else wx + half_w
    w = half_w if mode in {"snap_left", "left"} else ww - half_w
    return bool(
        user32.MoveWindow(wintypes.HWND(hwnd), x, wy, w, wh, True)
    )
