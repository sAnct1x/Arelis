"""Fail-first (#401): the window interior must not hit-test as a resize edge.

At 150% scale WM_NCHITTEST lParam is physical. Read as logical, a point in
the middle of a window away from the origin maps past the right edge.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QWidget

import arelis.ui.window_resize as wr


def test_interior_hit_test_is_client_under_dpi_scaling(qapp, monkeypatch) -> None:
    w = QWidget()
    w.setGeometry(1000, 100, 800, 600)
    w.show()
    qapp.processEvents()
    centre = w.mapToGlobal(QPoint(400, 300))
    scale = 1.5
    msg = wintypes.MSG()
    msg.message = wr.WM_NCHITTEST
    px, py = round(centre.x() * scale), round(centre.y() * scale)
    msg.lParam = (py << 16) | px
    monkeypatch.setattr(wr.sys, "platform", "win32")
    monkeypatch.setattr(wr.QCursor, "pos", staticmethod(lambda: centre))
    try:
        got = wr.handle_native_resize(
            w, b"windows_generic_MSG", ctypes.addressof(msg)
        )
    finally:
        w.close()
    assert got is None, f"window centre hit-tested as {got}, not client"
