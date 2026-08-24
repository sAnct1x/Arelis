from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QSettings, QSize
from PySide6.QtWidgets import QMainWindow

from arelis.paths import state_dir
from arelis.spatial.scene import REACH_DEFAULT, clamp_reach

_DEFAULT_CHAT_FONT_SCALE = 1.0
_RECENT_WORKSPACE_LIMIT = 12
_AWAY_REST_MINUTES = (30, 45, 60)
_DEFAULT_AWAY_REST_MIN = 45


def _settings_path() -> Path:
    path = state_dir() / "ui_layout.ini"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def settings() -> QSettings:
    return QSettings(str(_settings_path()), QSettings.Format.IniFormat)


def load_recent_workspace_files() -> list[str]:
    """Qualified or relative paths recently opened/saved in the workspace dock."""
    s = settings()
    raw = s.value("recent_workspace_files", [])
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
        if len(out) >= _RECENT_WORKSPACE_LIMIT:
            break
    return out


def push_recent_workspace_file(path: str) -> list[str]:
    text = (path or "").strip()
    if not text:
        return load_recent_workspace_files()
    recent = [text] + [p for p in load_recent_workspace_files() if p != text]
    recent = recent[:_RECENT_WORKSPACE_LIMIT]
    s = settings()
    s.setValue("recent_workspace_files", recent)
    s.sync()
    return recent


def save_window_layout(window: QMainWindow) -> None:
    s = settings()
    s.setValue("geometry", window.saveGeometry())
    s.setValue("state", window.saveState())
    s.setValue("size", window.size())
    always_on_top = bool(getattr(window, "_always_on_top", False))
    s.setValue("always_on_top", always_on_top)
    scale = float(getattr(window, "_chat_font_scale", _DEFAULT_CHAT_FONT_SCALE))
    s.setValue("chat_font_scale", scale)
    reach = float(getattr(window, "_world_reach", REACH_DEFAULT))
    s.setValue("world_reach", clamp_reach(reach))
    s.sync()


def restore_window_layout(window: QMainWindow, default_size: QSize) -> bool:
    s = settings()
    geo = s.value("geometry")
    state = s.value("state")
    size = s.value("size")
    restored = False
    if isinstance(size, QSize) and size.isValid():
        window.resize(size)
    elif size is not None:
        try:
            window.resize(size)
        except Exception:
            window.resize(default_size)
    else:
        window.resize(default_size)
    if isinstance(geo, QByteArray) and not geo.isEmpty():
        window.restoreGeometry(geo)
        restored = True
    if isinstance(state, QByteArray) and not state.isEmpty():
        window.restoreState(state)
        restored = True
    return restored


def _as_bool(raw: Any, default: bool = False) -> bool:
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes"}
    if raw is None:
        return default
    return bool(raw)


def clamp_away_rest_min(raw: Any) -> int:
    """Only 30 / 45 / 60 minutes. Anything else snaps to the nearest."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_AWAY_REST_MIN
    if value in _AWAY_REST_MINUTES:
        return value
    return min(_AWAY_REST_MINUTES, key=lambda m: abs(m - value))


def load_ui_prefs() -> dict[str, Any]:
    s = settings()
    raw_scale = s.value("chat_font_scale", _DEFAULT_CHAT_FONT_SCALE)
    try:
        scale = float(raw_scale)
    except (TypeError, ValueError):
        scale = _DEFAULT_CHAT_FONT_SCALE
    scale = max(0.75, min(1.75, scale))
    raw_reach = s.value("world_reach", REACH_DEFAULT)
    try:
        reach = float(raw_reach)
    except (TypeError, ValueError):
        reach = REACH_DEFAULT
    return {
        "always_on_top": _as_bool(s.value("always_on_top", False)),
        "chat_font_scale": scale,
        "world_reach": clamp_reach(reach),
        "away_rest": _as_bool(s.value("away_rest", False)),
        "away_rest_min": clamp_away_rest_min(
            s.value("away_rest_min", _DEFAULT_AWAY_REST_MIN)
        ),
    }


def save_ui_prefs(
    *,
    always_on_top: bool | None = None,
    chat_font_scale: float | None = None,
    world_reach: float | None = None,
    away_rest: bool | None = None,
    away_rest_min: int | None = None,
) -> None:
    s = settings()
    if always_on_top is not None:
        s.setValue("always_on_top", bool(always_on_top))
    if chat_font_scale is not None:
        s.setValue("chat_font_scale", float(chat_font_scale))
    if world_reach is not None:
        s.setValue("world_reach", clamp_reach(world_reach))
    if away_rest is not None:
        s.setValue("away_rest", bool(away_rest))
    if away_rest_min is not None:
        s.setValue("away_rest_min", clamp_away_rest_min(away_rest_min))
    s.sync()
