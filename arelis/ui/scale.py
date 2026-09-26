"""Display scale. Follow the OS, then optionally a user zoom.

Major apps (Chrome, VS Code, Slack, Office) do not invent a 4K mode.
They design in logical pixels and let the OS scale factor do the rest:

- 1080p at 100% is 1920×1080 logical.
- 4K at 150% is ~2560×1440 logical — the same layout as a 1440p panel.
- Three screens are three work areas, not one giant canvas.

Qt 6 already applies per-monitor DPI. This module owns the rest:

- PassThrough rounding so 125% / 150% stay sharp (Chrome/Electron).
- Optional ``ui.scale`` — a user zoom on top of the OS, default 1.0.
- First-launch size that fits the current work area (taskbar included).
- Restored geometry that still sits on a connected screen.

Do not multiply layout by pixel count. A 3840-wide panel at 200% is
already 1920 logical; a second 2× here would be a bug.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget

SCALE_MIN = 0.75
SCALE_MAX = 2.0
SCALE_DEFAULT = 1.0
# Discrete steps in Settings. 1.0 means follow the display scale only.
SCALE_PRESETS: tuple[float, ...] = (0.75, 1.0, 1.25, 1.5, 1.75, 2.0)
FIT_FRACTION = 0.92
_SCALE_ENV = "QT_SCALE_FACTOR"


def clamp_scale(value: object) -> float:
    """Keep a user zoom inside the Settings range. Bad input becomes 1.0."""
    try:
        scale = float(value)
    except (TypeError, ValueError):
        return SCALE_DEFAULT
    if scale != scale:  # NaN
        return SCALE_DEFAULT
    return max(SCALE_MIN, min(SCALE_MAX, scale))


def scale_from_config(config: Mapping[str, Any] | None) -> float:
    ui = (config or {}).get("ui") or {}
    return clamp_scale(ui.get("scale", SCALE_DEFAULT))


def scale_preset_label(value: float) -> str:
    if abs(value - 1.0) < 0.001:
        return "follow display"
    return f"{round(value * 100)}%"


def nearest_scale_preset(value: float) -> float:
    clamped = clamp_scale(value)
    return min(SCALE_PRESETS, key=lambda step: abs(step - clamped))


def apply_high_dpi_policy() -> None:
    """Ask Qt to pass the OS scale through instead of rounding to 100/200.

    Must run before QApplication. After that Qt ignores the call.
    """
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )


def configure_display_scale(
    config: Mapping[str, Any] | None,
    env: MutableMapping[str, str] | None = None,
) -> float:
    """Install DPI policy and optional user zoom. Call before QApplication.

    ``ui.scale`` of 1.0 leaves ``QT_SCALE_FACTOR`` alone so per-monitor
    DPI keeps working. An already-set environment value (CI, a debug
    shell) wins.
    """
    apply_high_dpi_policy()
    factor = scale_from_config(config)
    target = os.environ if env is None else env
    if target.get(_SCALE_ENV):
        return factor
    if abs(factor - 1.0) >= 0.001:
        target[_SCALE_ENV] = f"{factor:.4g}"
    return factor


def fit_size(
    width: int,
    height: int,
    work_w: int,
    work_h: int,
    *,
    fraction: float = FIT_FRACTION,
) -> tuple[int, int]:
    """Shrink a wanted size so it fits a work area. Never grows it."""
    want_w = max(1, int(width))
    want_h = max(1, int(height))
    if work_w <= 0 or work_h <= 0:
        return want_w, want_h
    frac = min(1.0, max(0.1, float(fraction)))
    max_w = max(1, min(int(work_w), int(work_w * frac)))
    max_h = max(1, min(int(work_h), int(work_h * frac)))
    return min(want_w, max_w), min(want_h, max_h)


def _overlap_area(
    left: tuple[int, int, int, int],
    right: tuple[int, int, int, int],
) -> int:
    ax, ay, aw, ah = left
    bx, by, bw, bh = right
    ox = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    oy = max(0, min(ay + ah, by + bh) - max(ay, by))
    return ox * oy


def clamp_rect(
    x: int,
    y: int,
    width: int,
    height: int,
    screens: Sequence[tuple[int, int, int, int]],
) -> tuple[int, int, int, int]:
    """Keep a window on a connected screen.

    If the saved rect still overlaps a desk, stay there and shrink if
    that desk is smaller now. If every monitor is gone (laptop lid,
    unplugged row), center on the first work area.
    """
    if not screens:
        return int(x), int(y), max(1, int(width)), max(1, int(height))
    geo = (int(x), int(y), max(1, int(width)), max(1, int(height)))
    home = max(screens, key=lambda screen: _overlap_area(geo, screen))
    if _overlap_area(geo, home) <= 0:
        home = screens[0]
        fitted_w, fitted_h = fit_size(geo[2], geo[3], home[2], home[3])
        cx = home[0] + max(0, (home[2] - fitted_w) // 2)
        cy = home[1] + max(0, (home[3] - fitted_h) // 2)
        return cx, cy, fitted_w, fitted_h
    fitted_w, fitted_h = fit_size(geo[2], geo[3], home[2], home[3])
    nx, ny = geo[0], geo[1]
    if nx + fitted_w > home[0] + home[2]:
        nx = home[0] + home[2] - fitted_w
    if ny + fitted_h > home[1] + home[3]:
        ny = home[1] + home[3] - fitted_h
    if nx < home[0]:
        nx = home[0]
    if ny < home[1]:
        ny = home[1]
    return nx, ny, fitted_w, fitted_h


def available_work_area(widget: QWidget | None = None) -> QRect:
    """Taskbar-aware rect for the screen this widget is on, or the primary."""
    screen = None
    if widget is not None:
        screen = widget.screen()
    if screen is None:
        app = QApplication.instance()
        if app is not None:
            screen = app.primaryScreen()
    if screen is None:
        return QRect()
    return screen.availableGeometry()


def screen_work_areas() -> list[tuple[int, int, int, int]]:
    app = QApplication.instance()
    if app is None:
        return []
    out: list[tuple[int, int, int, int]] = []
    for screen in app.screens():
        geo = screen.availableGeometry()
        if geo.isValid() and not geo.isEmpty():
            out.append((geo.x(), geo.y(), geo.width(), geo.height()))
    return out


def fit_window_size(width: int, height: int, work: QRect | None = None) -> QSize:
    area = work if work is not None else available_work_area()
    fitted_w, fitted_h = fit_size(
        width, height, area.width(), area.height()
    )
    return QSize(fitted_w, fitted_h)


def default_window_size(config: Mapping[str, Any] | None, work: QRect | None = None) -> QSize:
    ui = (config or {}).get("ui") or {}
    return fit_window_size(
        int(ui.get("default_width", 1440)),
        int(ui.get("default_height", 900)),
        work,
    )


def clamp_widget_to_screens(widget: QWidget) -> None:
    """Move/resize a top-level window so it still sits on a live screen."""
    screens = screen_work_areas()
    if not screens:
        return
    geo = widget.geometry()
    x, y, w, h = clamp_rect(
        geo.x(), geo.y(), geo.width(), geo.height(), screens
    )
    if (x, y, w, h) != (geo.x(), geo.y(), geo.width(), geo.height()):
        widget.setGeometry(x, y, w, h)
