"""Clipboard must not block the glass from a worker thread."""

from __future__ import annotations

import asyncio
import ctypes
import sys
import threading
import time

import pytest
from PySide6.QtCore import QThread
from PySide6.QtGui import QClipboard

from arelis.tools.clipboard import (
    ClipboardTool,
    _qt_clipboard_on_gui_thread,
    read_clipboard_text,
    write_clipboard_text,
)


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


def test_empty_gui_thread_read_returns_blank_and_skips_windows(
    qt_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty Qt read is a result. It must not fall through to WinDLL."""
    clip = qt_app.clipboard()
    previous = clip.text()
    windows_calls: list[str] = []

    def _windows_path() -> str:
        windows_calls.append("read")
        raise AssertionError("windows clipboard path")

    monkeypatch.setattr("arelis.tools.clipboard._read_windows_clipboard", _windows_path)
    try:
        clip.setText("")
        assert read_clipboard_text() == ""
        assert windows_calls == []
    finally:
        clip.setText(previous)


def test_linux_worker_thread_write_then_read_round_trips(
    qt_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Off Windows, a worker must hop to the GUI thread instead of WinDLL."""
    monkeypatch.setattr(sys, "platform", "linux")
    # Linux ctypes has no WinDLL. Hide it here so a Windows machine fails the
    # same way: a fall-through raises, a real Qt hop does not need it.
    monkeypatch.delattr(ctypes, "WinDLL", raising=False)

    gui_thread = qt_app.thread()
    touched: list[QThread] = []
    orig_set = QClipboard.setText
    orig_text = QClipboard.text

    def _set(self, text, mode=QClipboard.Mode.Clipboard):
        touched.append(QThread.currentThread())
        return orig_set(self, text, mode)

    def _text(self, mode=QClipboard.Mode.Clipboard):
        touched.append(QThread.currentThread())
        return orig_text(self, mode)

    monkeypatch.setattr(QClipboard, "setText", _set)
    monkeypatch.setattr(QClipboard, "text", _text)

    clip = qt_app.clipboard()
    previous = clip.text()
    token = "xplat-tray-clip-round-trip"
    outcome: dict[str, object] = {}
    finished = threading.Event()

    def _worker() -> None:
        try:
            write_clipboard_text(token)
            outcome["text"] = read_clipboard_text()
        except Exception as exc:
            outcome["error"] = exc
        finally:
            finished.set()

    thread = threading.Thread(target=_worker, name="clipboard-worker")
    thread.start()
    deadline = time.monotonic() + 3.0
    try:
        while not finished.is_set() and time.monotonic() < deadline:
            qt_app.processEvents()
            finished.wait(0.02)
        thread.join(timeout=1.0)
        err = outcome.get("error")
        assert err is None, err
        assert outcome.get("text") == token
        assert touched
        assert all(thread is gui_thread for thread in touched)
    finally:
        clip.setText(previous)
