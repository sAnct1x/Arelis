"""Screen grab + pixel-click gate. x,y only after screenshot then vision this turn."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from arelis.paths import outputs_dir

_MONITOR_TOKEN = re.compile(
    r"(?i)^\s*("
    r"primary|main|"
    r"left|right|center|middle|"
    r"top|bottom|above|below|upper|lower|vertical|"
    r"other|second|2nd|"
    r"(?:monitor|display|screen)\s*[1-9]|"
    r"[1-9]"
    r")\s*$"
)


def xy_refused() -> str:
    return (
        "x,y needs screenshot then vision this turn. "
        "Prefer a snapshot ref when the window has named controls."
    )


def screenshot_path() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return outputs_dir() / "images" / f"desktop_{stamp}_{uuid4().hex[:8]}.png"


@dataclass(frozen=True)
class DeskScreen:
    index: int
    name: str
    primary: bool
    x: int
    y: int
    width: int
    height: int
    side: str
    handle: Any = None
    dpr: float = 1.0
    device: str = ""


def looks_like_monitor_token(target: str) -> bool:
    return bool(_MONITOR_TOKEN.match((target or "").strip()))


def assign_sides(rows: list[DeskScreen]) -> list[DeskScreen]:
    """Label sides from geometry. Horizontal wins when x-span >= y-span."""
    if not rows:
        return rows
    if len(rows) == 1:
        one = rows[0]
        return [
            DeskScreen(
                index=one.index,
                name=one.name,
                primary=one.primary,
                x=one.x,
                y=one.y,
                width=one.width,
                height=one.height,
                side="only",
                handle=one.handle,
                dpr=one.dpr,
                device=one.device,
            )
        ]
    x_span = max(s.x for s in rows) - min(s.x for s in rows)
    y_span = max(s.y for s in rows) - min(s.y for s in rows)
    if y_span > x_span:
        ordered = sorted(rows, key=lambda s: (s.y, s.index))
        sides: dict[int, str] = {
            ordered[0].index: "top",
            ordered[-1].index: "bottom",
        }
    else:
        ordered = sorted(rows, key=lambda s: (s.x, s.index))
        sides = {ordered[0].index: "left", ordered[-1].index: "right"}
    for mid in ordered[1:-1]:
        sides[mid.index] = "center"
    return [
        DeskScreen(
            index=s.index,
            name=s.name,
            primary=s.primary,
            x=s.x,
            y=s.y,
            width=s.width,
            height=s.height,
            side=sides.get(s.index, "center"),
            handle=s.handle,
            dpr=s.dpr,
            device=s.device,
        )
        for s in rows
    ]


def _win_monitors() -> list[tuple[str, int, int, int, int]]:
    """(device, x, y, w, h) from EnumDisplayMonitors. Empty off Windows."""
    import sys

    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    class _MonitorInfoEx(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    found: list[tuple[str, int, int, int, int]] = []

    @ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )
    def _each(hmon: int, _hdc: int, _rect: object, _lp: int) -> bool:
        info = _MonitorInfoEx()
        info.cbSize = ctypes.sizeof(_MonitorInfoEx)
        if ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            name = (info.szDevice or "").strip()
            if name:
                found.append(
                    (
                        name,
                        int(r.left),
                        int(r.top),
                        int(r.right - r.left),
                        int(r.bottom - r.top),
                    )
                )
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, _each, 0)
    return found


def _attach_win_devices(rows: list[DeskScreen]) -> list[DeskScreen]:
    """Bind unique \\\\.\\DISPLAY* names. Qt model names can collide."""
    mons = _win_monitors()
    if not mons:
        return rows
    used: set[str] = set()
    out: list[DeskScreen] = []
    for row in rows:
        hit = next(
            (
                m
                for m in mons
                if m[0] not in used and m[1] == row.x and m[2] == row.y
            ),
            None,
        )
        device = hit[0] if hit is not None else row.device
        if device:
            used.add(device)
        out.append(
            DeskScreen(
                index=row.index,
                name=row.name,
                primary=row.primary,
                x=row.x,
                y=row.y,
                width=row.width,
                height=row.height,
                side=row.side,
                handle=row.handle,
                dpr=row.dpr,
                device=device,
            )
        )
    return out


def list_screens() -> list[DeskScreen]:
    """Connected monitors, 1-based. Empty when no Qt GUI is up."""
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QGuiApplication.instance()
    if app is None:
        return []
    primary = QGuiApplication.primaryScreen()
    rows: list[DeskScreen] = []
    for i, screen in enumerate(QGuiApplication.screens() or (), start=1):
        geo = screen.geometry()
        name = (screen.name() or "").strip() or f"display-{i}"
        rows.append(
            DeskScreen(
                index=i,
                name=name,
                primary=screen is primary,
                x=int(geo.x()),
                y=int(geo.y()),
                width=int(geo.width()),
                height=int(geo.height()),
                side="center",
                handle=screen,
                dpr=float(screen.devicePixelRatio() or 1.0),
            )
        )
    return assign_sides(_attach_win_devices(rows))


def format_screens(rows: list[DeskScreen]) -> str:
    if not rows:
        return "No monitors visible."
    lines = []
    for row in rows:
        tag = "primary" if row.primary else row.name
        lines.append(f"{row.index}|{tag}|{row.width}x{row.height}|{row.side}")
    return "\n".join(lines)


def resolve_screen(
    target: str, rows: list[DeskScreen] | None = None
) -> DeskScreen | None:
    """Pick a monitor by index, primary, side, or 'other' (only when unique)."""
    needle = (target or "").strip().lower()
    if not needle:
        return None
    rows = rows if rows is not None else list_screens()
    if not rows:
        return None
    needle = re.sub(r"^(?:monitor|display|screen)\s+", "", needle).strip()
    if needle in {"primary", "main"}:
        return next((s for s in rows if s.primary), rows[0])
    if needle in {"other", "second", "2nd"}:
        others = [s for s in rows if not s.primary]
        if len(others) == 1:
            return others[0]
        return None
    if needle in {
        "left",
        "right",
        "center",
        "middle",
        "top",
        "bottom",
        "above",
        "below",
        "upper",
        "lower",
        "vertical",
    }:
        return _resolve_side(needle, rows)
    if needle.isdigit():
        idx = int(needle)
        return next((s for s in rows if s.index == idx), None)
    return None


def _resolve_side(needle: str, rows: list[DeskScreen]) -> DeskScreen | None:
    if not rows:
        return None
    x_span = max(s.x for s in rows) - min(s.x for s in rows)
    y_span = max(s.y for s in rows) - min(s.y for s in rows)
    want = {
        "middle": "center",
        "above": "top",
        "upper": "top",
        "below": "bottom",
        "lower": "bottom",
    }.get(needle, needle)
    if want == "vertical":
        if y_span <= 0:
            return None
        others = [s for s in rows if not s.primary]
        if len(others) == 1:
            return others[0]
        prim = next((s for s in rows if s.primary), rows[0])
        return max(rows, key=lambda s: abs(s.y - prim.y))
    if want == "left":
        return min(rows, key=lambda s: (s.x, s.index)) if x_span > 0 else None
    if want == "right":
        return max(rows, key=lambda s: (s.x, s.index)) if x_span > 0 else None
    if want == "top":
        return min(rows, key=lambda s: (s.y, s.index)) if y_span > 0 else None
    if want == "bottom":
        return max(rows, key=lambda s: (s.y, s.index)) if y_span > 0 else None
    if want == "center":
        if len(rows) < 2:
            return None
        key = (lambda s: (s.x, s.index)) if x_span >= y_span else (lambda s: (s.y, s.index))
        ordered = sorted(rows, key=key)
        return ordered[len(ordered) // 2]
    return None


def screen_covering(
    x: int, y: int, rows: list[DeskScreen]
) -> DeskScreen | None:
    """Screen whose geometry contains (x, y), else the nearest center."""
    if not rows:
        return None
    for row in rows:
        if row.x <= x < row.x + row.width and row.y <= y < row.y + row.height:
            return row
    def _dist(row: DeskScreen) -> float:
        cx = row.x + row.width / 2
        cy = row.y + row.height / 2
        return (cx - x) ** 2 + (cy - y) ** 2

    return min(rows, key=_dist)


def window_center(hwnd: int) -> tuple[int, int] | None:
    """Center of a top-level HWND in virtual-desktop pixels."""
    import sys

    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(int(hwnd), ctypes.byref(rect)):
        return None
    return ((int(rect.left) + int(rect.right)) // 2, (int(rect.top) + int(rect.bottom)) // 2)


def monitor_device_for_hwnd(hwnd: int) -> str | None:
    """Windows monitor device name for a window (``\\\\.\\DISPLAY2``)."""
    import sys

    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class _MonitorInfoEx(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    user32 = ctypes.windll.user32
    nearest = 2
    monitor = user32.MonitorFromWindow(wintypes.HWND(int(hwnd)), nearest)
    if not monitor:
        return None
    info = _MonitorInfoEx()
    info.cbSize = ctypes.sizeof(_MonitorInfoEx)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    name = (info.szDevice or "").strip()
    return name or None


def screen_for_window(
    hwnd: int,
    rows: list[DeskScreen],
    *,
    center: tuple[int, int] | None = None,
    device: str | None = None,
) -> DeskScreen | None:
    """Pick the window's QScreen by OS monitor name, then by center."""
    if not rows:
        return None
    name = (device if device is not None else monitor_device_for_hwnd(hwnd) or "")
    name = name.strip()
    if name:
        want = name.lower()
        hit = next(
            (
                s
                for s in rows
                if (s.device or "").lower() == want or s.name.lower() == want
            ),
            None,
        )
        if hit is not None:
            return hit
    point = center if center is not None else window_center(hwnd)
    if point is not None:
        return screen_covering(point[0], point[1], rows)
    # Tool windows and offscreen pytest QScreens often have no GetWindowRect
    # yet. grab_window already falls back to the primary handle — do the same
    # here so ownership is never None while a grab still works.
    return next((s for s in rows if s.primary), rows[0])


def grab_screen(
    dest: Path | None = None,
    *,
    target: str = "",
    screens: list[DeskScreen] | None = None,
) -> Path:
    """Grab one monitor. Empty target is the primary."""
    rows = screens if screens is not None else list_screens()
    if not rows:
        from arelis.tools.ocr import capture_primary_screen

        path = dest or screenshot_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        return capture_primary_screen(path)
    chosen = (
        resolve_screen(target, rows)
        if (target or "").strip()
        else next((s for s in rows if s.primary), rows[0])
    )
    if chosen is None:
        raise RuntimeError(
            f"No monitor matching {target!r}. "
            f"Connected: {format_screens(rows)}"
        )
    handle = chosen.handle
    if handle is None:
        from arelis.tools.ocr import capture_primary_screen

        path = dest or screenshot_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        return capture_primary_screen(path)
    pix = handle.grabWindow(0)
    return _save_pix(pix, dest, empty="Screen grab returned an empty image.")


def grab_window(
    hwnd: int,
    dest: Path | None = None,
    *,
    screens: list[DeskScreen] | None = None,
    center: tuple[int, int] | None = None,
    device: str | None = None,
) -> Path:
    """Grab one top-level window from the screen that owns it."""
    rows = screens if screens is not None else list_screens()
    chosen = (
        screen_for_window(hwnd, rows, center=center, device=device)
        if rows
        else None
    )
    handle = chosen.handle if chosen is not None else None
    if handle is not None:
        pix = handle.grabWindow(int(hwnd))
        return _save_pix(pix, dest, empty=_EMPTY_WINDOW)
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QGuiApplication.instance()
    if app is None:
        raise RuntimeError(
            "No GUI application is running; cannot capture a window."
        )
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        raise RuntimeError("No primary screen available.")
    pix = screen.grabWindow(int(hwnd))
    return _save_pix(pix, dest, empty=_EMPTY_WINDOW)


_EMPTY_WINDOW = (
    "Window grab returned an empty image. Protected, overlay, or "
    "fullscreen content often cannot be captured. I cannot invent the page."
)


def _save_pix(pix: Any, dest: Path | None, *, empty: str) -> Path:
    if pix is None or pix.isNull():
        raise RuntimeError(empty)
    path = dest or screenshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not pix.save(str(path), "PNG"):
        raise RuntimeError(f"Could not write screenshot to {path}")
    return path
