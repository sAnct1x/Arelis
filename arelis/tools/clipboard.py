"""Read or replace the system clipboard text — always behind Allow.

Reading is a privacy question: the clipboard may hold a password. Writing is a
loss question: it calls EmptyClipboard first, so it destroys whatever was
copied. Both need the card.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from arelis.tools.base import ToolResult
from arelis.tools.safety import redact_secrets

_MAX_CHARS = 8000
_READ_TIMEOUT_S = 4.0


def _qt_clipboard_on_gui_thread() -> str | None:
    """Qt clipboard only from the GUI thread. Worker-thread text() deadlocks."""
    try:
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None or QThread.currentThread() is not app.thread():
            return None
        return app.clipboard().text() or ""
    except Exception:
        return None


def read_clipboard_text() -> str:
    """Best-effort plain-text clipboard read for the current platform."""
    qt = _qt_clipboard_on_gui_thread()
    if qt:
        return qt
    # Windows: CF_UNICODETEXT. restype on GlobalLock must be
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
    opened = False
    for _ in range(10):
        if user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.05)
    if not opened:
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


def _qt_write_on_gui_thread(text: str) -> bool:
    """Mirror of the read path: Qt clipboard only from the GUI thread."""
    try:
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None or QThread.currentThread() is not app.thread():
            return False
        app.clipboard().setText(text)
        return True
    except Exception:
        return False


def write_clipboard_text(text: str) -> None:
    """Put plain text on the clipboard, replacing what was there."""
    if _qt_write_on_gui_thread(text):
        return
    try:
        _write_windows_clipboard(text)
    except Exception as exc:
        raise RuntimeError(f"Clipboard unavailable: {exc}") from exc


def _write_windows_clipboard(text: str) -> None:
    """Seed CF_UNICODETEXT. Reached through `write_clipboard_text`."""
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
    """Read or replace the system clipboard.

    The description below used to say "Always asks for Allow first", which was
    true of the card face and false everywhere else. In voice / filament mode
    `evaluate_confirm` pauses for `run_script` and for destructive actions
    only, and a clipboard read is neither, so it ran with no card at all. That
    is a deliberate design — on that face, saying the ask is the grant — but
    "always" was still a promise the gate does not make.

    The wording is what changed, not the gate. `policy.py` stays
    destructive-only on voice by the rule in `.cursor/rules`, and widening it
    from here is exactly the thing that rule forbids.
    """

    name = "clipboard"
    description = (
        "Read the system clipboard as plain text, or write text onto it. "
        "Asks for Allow first on the card face — reading may expose passwords "
        "or private notes, and writing replaces whatever the user had copied. "
        "action=read (default) for what is on the clipboard or to use pasted "
        "text; action=write with text to copy something for them."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["read", "write"],
                "description": ("read the clipboard (default), or write replaces it"),
            },
            "text": {
                "type": "string",
                "description": "The text to copy, for action=write",
            },
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
        writer: Callable[[str], None] | None = None,
        max_chars: int = _MAX_CHARS,
    ) -> None:
        self._reader = reader or read_clipboard_text
        self._writer = writer or write_clipboard_text
        self.max_chars = max(256, int(max_chars))

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "read").strip().lower()
        if action == "write":
            return await self._write(kwargs)
        if action != "read":
            return ToolResult(
                ok=False,
                output=f"Unknown action {action!r}. Use read or write.",
            )
        return await self._read(kwargs)

    async def _write(self, kwargs: dict[str, Any]) -> ToolResult:
        text = str(kwargs.get("text") or "")
        if not text:
            # Writing "" would call EmptyClipboard and wipe what they had,
            # which is never what "copy this" meant.
            return ToolResult(
                ok=False,
                output="write needs text. Nothing was put on the clipboard.",
            )
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._writer, text),
                timeout=_READ_TIMEOUT_S,
            )
        except TimeoutError:
            return ToolResult(
                ok=False,
                output="Clipboard write timed out. Nothing was copied.",
                data={"fail_class": "fail:timeout"},
            )
        except Exception as exc:
            return ToolResult(
                ok=False,
                output=f"[fail:other] Could not write clipboard: {exc}",
                data={"fail_class": "fail:other"},
            )
        # Deliberately not echoed: they just said what it is, and a wall of it
        # coming back is noise in the chat and tokens in the next prompt.
        return ToolResult(
            ok=True,
            output=f"Copied {len(text)} characters to the clipboard.",
            data={"chars": len(text), "action": "write"},
        )

    async def _read(self, kwargs: dict[str, Any]) -> ToolResult:
        try:
            limit = int(kwargs.get("max_chars") or self.max_chars)
        except (TypeError, ValueError):
            limit = self.max_chars
        limit = max(1, min(_MAX_CHARS, limit))
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(self._reader),
                timeout=_READ_TIMEOUT_S,
            )
            raw = raw or ""
        except TimeoutError:
            return ToolResult(
                ok=False,
                output="Clipboard read timed out. Nothing was pasted into chat.",
                data={"fail_class": "fail:timeout"},
            )
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
