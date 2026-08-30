"""Read the system clipboard text — Always behind Allow (privacy)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from arelis.tools.base import ToolResult
from arelis.tools.safety import redact_secrets

_MAX_CHARS = 8000


def read_clipboard_text() -> str:
    """Best-effort plain-text clipboard read for the current platform."""
    # Prefer Qt when a GUI app already owns the clipboard (desktop UI).
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            text = app.clipboard().text() or ""
            if text:
                return text
    except Exception:
        pass
    # Windows headless / CLI: CF_UNICODETEXT. restype on GlobalLock must be
    # c_void_p or 64-bit Python truncates the pointer and wstring_at AVs.
    try:
        return _read_windows_clipboard()
    except Exception as exc:
        raise RuntimeError(f"Clipboard unavailable: {exc}") from exc


def _read_windows_clipboard() -> str:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    cf_unicode = 13
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalSize.restype = ctypes.c_size_t

    if not user32.IsClipboardFormatAvailable(cf_unicode):
        return ""
    if not user32.OpenClipboard(None):
        raise OSError(f"OpenClipboard failed ({ctypes.get_last_error()})")
    try:
        handle = user32.GetClipboardData(cf_unicode)
        if not handle:
            return ""
        size = int(kernel32.GlobalSize(handle) or 0)
        if size < 2:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr, size // 2).split("\x00", 1)[0]
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _write_windows_clipboard(text: str) -> None:
    """Seed CF_UNICODETEXT. Used by tests and the live pass, not a tool action."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    cf_unicode = 13
    gmem_moveable = 0x0002
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL

    payload = (str(text) + "\x00").encode("utf-16-le")
    opened = False
    for _ in range(10):
        if user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.05)
    if not opened:
        raise OSError(f"OpenClipboard failed ({ctypes.get_last_error()})")
    try:
        if not user32.EmptyClipboard():
            raise OSError(f"EmptyClipboard failed ({ctypes.get_last_error()})")
        handle = kernel32.GlobalAlloc(gmem_moveable, len(payload))
        if not handle:
            raise OSError(f"GlobalAlloc failed ({ctypes.get_last_error()})")
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            raise OSError("GlobalLock failed")
        try:
            ctypes.memmove(ptr, payload, len(payload))
        finally:
            kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(cf_unicode, handle):
            kernel32.GlobalFree(handle)
            raise OSError(f"SetClipboardData failed ({ctypes.get_last_error()})")
    finally:
        user32.CloseClipboard()


class ClipboardTool:
    name = "clipboard"
    description = (
        "Read the current system clipboard as plain text. Always asks for Allow "
        "first — clipboard may hold passwords or private notes. Use when the "
        "user asks what is on the clipboard or to use pasted text."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "max_chars": {
                "type": "integer",
                "description": f"Max characters to return (default {_MAX_CHARS})",
            },
        },
        "required": [],
    }

    def __init__(
        self,
        *,
        reader: Callable[[], str] | None = None,
        max_chars: int = _MAX_CHARS,
    ) -> None:
        self._reader = reader or read_clipboard_text
        self.max_chars = max(256, int(max_chars))

    async def run(self, **kwargs: Any) -> ToolResult:
        try:
            limit = int(kwargs.get("max_chars") or self.max_chars)
        except (TypeError, ValueError):
            limit = self.max_chars
        limit = max(1, min(_MAX_CHARS, limit))
        try:
            raw = self._reader() or ""
        except Exception as exc:
            return ToolResult(
                ok=False,
                output=f"[fail:other] Could not read clipboard: {exc}",
                data={"fail_class": "fail:other"},
            )
        text = str(raw)
        truncated = len(text) > limit
        body = text[:limit]
        if truncated:
            body = body + f"\n…(truncated, {len(text)} chars total)"
        safe = redact_secrets(body)
        if not safe.strip():
            return ToolResult(
                ok=True,
                output="Clipboard is empty (no plain text).",
                data={"chars": 0, "empty": True},
            )
        return ToolResult(
            ok=True,
            output=f"Clipboard text ({len(text)} chars):\n{safe}",
            data={
                "chars": len(text),
                "truncated": truncated,
                "empty": False,
            },
        )
