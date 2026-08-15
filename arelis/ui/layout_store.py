from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QSettings, QSize
from PySide6.QtWidgets import QMainWindow

from arelis.config import PROJECT_ROOT

_DEFAULT_CHAT_FONT_SCALE = 1.0
_RECENT_WORKSPACE_LIMIT = 12


def _settings_path() -> Path:
    path = PROJECT_ROOT / "data" / "ui_layout.ini"
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


def load_ui_prefs() -> dict[str, Any]:
    s = settings()
    raw_scale = s.value("chat_font_scale", _DEFAULT_CHAT_FONT_SCALE)
    try:
        scale = float(raw_scale)
    except (TypeError, ValueError):
        scale = _DEFAULT_CHAT_FONT_SCALE
    scale = max(0.75, min(1.75, scale))
    always = s.value("always_on_top", False)
    if isinstance(always, str):
        always_on_top = always.strip().lower() in {"1", "true", "yes"}
    else:
        always_on_top = bool(always)
    return {
        "always_on_top": always_on_top,
        "chat_font_scale": scale,
    }


def save_ui_prefs(
    *,
    always_on_top: bool | None = None,
    chat_font_scale: float | None = None,
) -> None:
    s = settings()
    if always_on_top is not None:
        s.setValue("always_on_top", bool(always_on_top))
    if chat_font_scale is not None:
        s.setValue("chat_font_scale", float(chat_font_scale))
    s.sync()
