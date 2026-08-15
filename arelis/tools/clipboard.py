"""Read the system clipboard text — Always behind Allow (privacy)."""

from __future__ import annotations

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
    # Windows headless / CLI: CF_UNICODETEXT.
    try:
        import ctypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        cf_unicode = 13
        if not user32.OpenClipboard(None):
            raise OSError("OpenClipboard failed")
        try:
            handle = user32.GetClipboardData(cf_unicode)
            if not handle:
                return ""
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return ""
            try:
                return ctypes.wstring_at(ptr)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    except Exception as exc:
        raise RuntimeError(f"Clipboard unavailable: {exc}") from exc


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
