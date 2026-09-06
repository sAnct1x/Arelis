"""Clipboard must not block the glass from a worker thread."""

from __future__ import annotations

import asyncio
import time

from arelis.tools.clipboard import ClipboardTool, _qt_clipboard_on_gui_thread


def test_clipboard_times_out_instead_of_hanging() -> None:
    def stuck() -> str:
        time.sleep(6)
        return "never"

    tool = ClipboardTool(reader=stuck)
    result = asyncio.run(tool.run())
    assert not result.ok
    assert "timed out" in result.output.lower()


def test_qt_clipboard_skipped_off_gui_thread() -> None:
    assert _qt_clipboard_on_gui_thread() in (None, "")
