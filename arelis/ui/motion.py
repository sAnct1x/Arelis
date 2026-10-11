"""Shared timing for chrome and chat.

Motion stays on unless this machine asks for it off. On Windows that is the
system setting for animation inside a window. Everywhere else, and also as a
quiet override, an environment value or a saved preference can turn it off.
Floating windows stay opaque. Dock motion slides the widget.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable

import yaml
from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    QVariantAnimation,
)
from PySide6.QtGui import QBrush, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QWidget

from arelis.config import LOCAL_CONFIG_PATH
from arelis.ui.theme_tokens import MOTION

# SystemParametersInfo: are animations enabled in the client area.
SPI_GETCLIENTAREAANIMATION = 0x1042

_OFF = frozenset({"0", "false", "off", "no"})
_CONFIG_CACHE: tuple[str, int, int, bool] | None = None


def motion_enabled() -> bool:
    """Whether chrome and chat should animate.

    An explicit off switch wins everywhere. On Windows the system animation
    setting is checked after that. Other systems default to on.
    """
    if _env_off() or _config_off():
        return False
    if sys.platform == "win32":
        return _windows_animations_enabled()
    return True


def easing_curve() -> QEasingCurve:
    """The one curve the rest of the interface shares."""
    name = str(MOTION.get("easing") or "OutCubic")
    kind = getattr(QEasingCurve.Type, name, QEasingCurve.Type.OutCubic)
    if not isinstance(kind, QEasingCurve.Type):
        kind = QEasingCurve.Type.OutCubic
    return QEasingCurve(kind)


def motion_ms(name: str) -> int:
    """A named duration, or zero when motion is off."""
    if not motion_enabled():
        return 0
    try:
        return max(0, int(MOTION[name]))
    except (KeyError, TypeError, ValueError):
        return 0


def _env_off() -> bool:
    raw = os.environ.get("ARELIS_MOTION", "").strip().lower()
    return raw in _OFF


def _is_off_value(value: object) -> bool:
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value == 0
    if isinstance(value, str):
        return value.strip().lower() in _OFF
    return False


def _config_off() -> bool:
    """True when the saved preference turns motion off. Missing means on."""
    global _CONFIG_CACHE
    path = LOCAL_CONFIG_PATH
    try:
        stat = path.stat()
    except OSError:
        return False
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if _CONFIG_CACHE is not None and _CONFIG_CACHE[:3] == key:
        return _CONFIG_CACHE[3]
    off = False
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        ui = data.get("ui") if isinstance(data, dict) else None
        if isinstance(ui, dict) and "motion" in ui:
            off = _is_off_value(ui.get("motion"))
    except (OSError, yaml.YAMLError, AttributeError, UnicodeError):
        off = False
    _CONFIG_CACHE = (*key, off)
    return off


def _system_parameters_info():
    """The Windows call that reads system animation flags, or None."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    proto = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.POINTER(wintypes.BOOL),
        wintypes.UINT,
    )
    try:
        return proto(("SystemParametersInfoW", ctypes.windll.user32))
    except (AttributeError, OSError, ValueError):
        return None


def _query_client_area_animation(spi: Callable) -> bool:
    """Read SPI_GETCLIENTAREAANIMATION. A failed call stays on."""
    import ctypes
    from ctypes import wintypes

    value = wintypes.BOOL(1)
    ok = spi(SPI_GETCLIENTAREAANIMATION, 0, ctypes.pointer(value), 0)
    if not ok:
        return True
    return bool(value.value)


def _windows_animations_enabled() -> bool:
    if sys.platform != "win32":
        return True
    spi = _system_parameters_info()
    if spi is None:
        return True
    try:
        return _query_client_area_animation(spi)
    except (AttributeError, OSError, TypeError, ValueError):
        return True


def clear_dock_opacity(dock: QWidget) -> None:
    """Drop a cached opacity pixmap. That pixmap is what ghosted on glass."""
    if dock.graphicsEffect() is not None:
        dock.setGraphicsEffect(None)
    child = dock.widget() if hasattr(dock, "widget") else None
    if child is not None and child.graphicsEffect() is not None:
        child.setGraphicsEffect(None)


def _hold_opaque(dock: QWidget) -> None:
    """A floating dock is its own window. Keep that window solid."""
    dock.setWindowOpacity(1.0)
    floating = getattr(dock, "isFloating", None)
    if not callable(floating) or not floating():
        return
    from arelis.ui.dock_surface import apply_dock_surface

    apply_dock_surface(dock, True)
    dock.setWindowOpacity(1.0)


def _stop_slide(dock: QWidget) -> None:
    prior = getattr(dock, "_arelis_dock_slide", None)
    dock._arelis_dock_slide = None  # type: ignore[attr-defined]
    if prior is None:
        return
    try:
        prior.finished.disconnect()
    except (RuntimeError, TypeError):
        pass
    prior.stop()


def slide_dock(dock: QWidget, *, show: bool = True) -> QPropertyAnimation | None:
    """Slide a dock in or out. Never fades it.

    When motion is off the dock jumps to the end, and a hide closes at once.
    """
    clear_dock_opacity(dock)
    _hold_opaque(dock)
    _stop_slide(dock)
    if not show and dock.isHidden():
        return None
    rest = QRect(dock.geometry())
    if not motion_enabled() or rest.width() < 2 or rest.height() < 2:
        if rest.width() >= 2 and rest.height() >= 2:
            dock.setGeometry(rest)
        _hold_opaque(dock)
        if not show:
            dock.hide()
        return None
    travel = min(36, max(16, rest.width() // 8))
    if show:
        start = QRect(rest)
        start.translate(travel, 0)
        end = QRect(rest)
        dock.setGeometry(start)
    else:
        start = QRect(rest)
        end = QRect(rest)
        end.translate(travel, 0)
    anim = QPropertyAnimation(dock, b"geometry", dock)
    anim.setDuration(max(0, int(MOTION["base"])))
    anim.setEasingCurve(easing_curve())
    anim.setStartValue(start)
    anim.setEndValue(end)

    def _done() -> None:
        if getattr(dock, "_arelis_dock_slide", None) is not anim:
            return
        dock._arelis_dock_slide = None  # type: ignore[attr-defined]
        _hold_opaque(dock)
        if show:
            dock.setGeometry(rest)
            return
        dock.hide()
        dock.setGeometry(rest)

    anim.finished.connect(_done)
    dock._arelis_dock_slide = anim  # type: ignore[attr-defined]
    anim.start()
    return anim


def cancel_transcript_fade(view: QWidget, *, restore: bool = True) -> None:
    """Stop a message fade and put the text back to full strength."""
    anim = getattr(view, "_message_fade", None)
    spans = getattr(view, "_message_spans", None)
    view._message_fade = None  # type: ignore[attr-defined]
    view._message_spans = None  # type: ignore[attr-defined]
    if anim is not None:
        try:
            anim.valueChanged.disconnect()
            anim.finished.disconnect()
        except (RuntimeError, TypeError):
            pass
        anim.stop()
    if restore and spans:
        _paint_spans(view, spans, 1.0)


def fade_new_transcript(view: QWidget, start: int) -> QVariantAnimation | None:
    """Fade text inserted at or after start. Images are left alone.

    With motion off the new text stays at full strength and nothing runs.
    """
    cancel_transcript_fade(view, restore=True)
    if not motion_enabled():
        return None
    document = view.document()
    end = document.characterCount()
    origin = max(0, min(int(start), end))
    spans = _text_spans(document, origin, end)
    if not spans:
        return None
    anim = QVariantAnimation(view)
    anim.setDuration(max(0, int(MOTION["slow"])))
    anim.setEasingCurve(easing_curve())
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    view._message_spans = spans  # type: ignore[attr-defined]
    view._message_fade = anim  # type: ignore[attr-defined]

    def _apply(value: object) -> None:
        if getattr(view, "_message_spans", None) is not spans:
            return
        try:
            strength = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return
        _paint_spans(view, spans, strength)

    def _done() -> None:
        if getattr(view, "_message_fade", None) is not anim:
            return
        view._message_fade = None  # type: ignore[attr-defined]
        view._message_spans = None  # type: ignore[attr-defined]
        _paint_spans(view, spans, 1.0)

    anim.valueChanged.connect(_apply)
    anim.finished.connect(_done)
    _paint_spans(view, spans, 0.0)
    anim.start()
    return anim


def _text_spans(document, start: int, end: int) -> list[tuple[int, int, QTextCharFormat]]:
    spans: list[tuple[int, int, QTextCharFormat]] = []
    block = document.findBlock(start)
    while block.isValid() and block.position() < end:
        iterator = block.begin()
        while not iterator.atEnd():
            frag = iterator.fragment()
            iterator += 1
            if not frag.isValid():
                continue
            frag_start = frag.position()
            frag_end = frag_start + frag.length()
            if frag_end <= start or frag_start >= end:
                continue
            fmt = frag.charFormat()
            if fmt.isImageFormat() or "\ufffc" in frag.text():
                continue
            lo = max(frag_start, start)
            hi = min(frag_end, end)
            if hi <= lo:
                continue
            spans.append((lo, hi, QTextCharFormat(fmt)))
        block = block.next()
    return spans


def _paint_spans(view: QWidget, spans, strength: float) -> None:
    document = view.document()
    cursor = QTextCursor(document)
    full = strength >= 0.999
    for lo, hi, original in reversed(spans):
        if lo >= document.characterCount():
            continue
        fmt = QTextCharFormat(original)
        if not full:
            color = fmt.foreground().color()
            color.setAlpha(max(0, min(255, round(color.alpha() * strength))))
            fmt.setForeground(QBrush(color))
        cursor.setPosition(min(lo, document.characterCount()))
        cursor.setPosition(min(hi, document.characterCount()), QTextCursor.MoveMode.KeepAnchor)
        if cursor.position() == cursor.anchor():
            continue
        cursor.setCharFormat(fmt)
