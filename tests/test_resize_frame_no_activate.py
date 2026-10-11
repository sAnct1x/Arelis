"""Fail-first: adding the resize frame on first show must not activate the window.

SetWindowPos without SWP_NOACTIVATE activates (Win32 docs). It runs from
ArelisWindow.showEvent, so a show-without-activate still ends up active.
"""
from __future__ import annotations

import ctypes
from types import SimpleNamespace

import arelis.ui.window_resize as wr


def test_resize_frame_setwindowpos_does_not_activate(monkeypatch) -> None:
    calls = []
    user32 = SimpleNamespace(
        GetWindowLongW=lambda hwnd, idx: 0,
        SetWindowLongW=lambda hwnd, idx, val: 0,
        SetWindowPos=lambda *args: calls.append(args) or 1,
    )
    monkeypatch.setattr(wr.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user32), raising=False)
    monkeypatch.setattr(wr, "top_level_hwnd", lambda widget: 4242)
    wr.enable_win32_resize_frame(object())
    assert calls, "frame change was not applied"
    flags = calls[-1][-1]
    assert flags & wr.SWP_NOACTIVATE, f"SetWindowPos flags {flags:#x} lack SWP_NOACTIVATE"
    assert flags & wr.SWP_FRAMECHANGED
