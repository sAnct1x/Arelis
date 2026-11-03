"""place_frameless_rect must not spin the event loop (#520h: a placement during launch ran
her whole QML load reentrantly, a 19.6 s freeze). Qt's clamp is still undone, a turn later."""

from __future__ import annotations

from PySide6.QtCore import QRect, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget


def test_placing_runs_nothing_else_and_still_undoes_the_clamp(qt_app, monkeypatch) -> None:
    from arelis.ui import window_resize as wr

    native = {"rect": QRect(0, 0, 100, 100)}
    sets: list[QRect] = []

    def set_hwnd(_hwnd, rect, _scale) -> None:
        sets.append(QRect(rect))
        native["rect"] = QRect(rect)

    monkeypatch.setattr(QGuiApplication, "platformName", staticmethod(lambda: "windows"))
    monkeypatch.setattr(wr, "top_level_hwnd", lambda _w: 1)
    monkeypatch.setattr(wr, "_place_scale", lambda _h: 1.0)
    monkeypatch.setattr(wr, "_set_hwnd_rect", set_hwnd)
    monkeypatch.setattr(wr, "_hwnd_logical_rect", lambda _h, _s: QRect(native["rect"]))
    ran = []
    w = QWidget()
    want = QRect(40, 30, 900, 600)
    # Something queued that must not run inside the placement (her load, a timer).
    QTimer.singleShot(0, lambda: ran.append("queued"))

    def clamp(rect, handle=None) -> None:  # Qt clamps to one desk: the HWND gets narrower
        native["rect"] = QRect(rect.x(), rect.y(), 500, rect.height())

    monkeypatch.setattr(wr, "_qt_set_rect", lambda _w, _h, r: clamp(r))
    assert wr.place_frameless_rect(w, want) is True
    assert ran == []  # nothing else ran during the placement
    qt_app.processEvents()
    assert ran == ["queued"]
    assert native["rect"] == want  # the clamp was put back after Qt's turn
    w.deleteLater()
