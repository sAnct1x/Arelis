"""DIAGNOSTIC ONLY (diag/sodium-reseal): Sodium fresh-launch black window.

Re-seals the main HWND after show (Qt drops WA_OpaquePaintEvent and autofill after
show; only Filament re-sealed) and logs every 2 s: qq3d frames read back, paint
events on the window and her widget, and the window attrs.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QWidget

log = logging.getLogger("arelis.avatar")


class _Count(QObject):
    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.n: dict[str, int] = {}

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Paint:
            k = type(obj).__name__
            self.n[k] = self.n.get(k, 0) + 1
        return False


def _attrs(w: QWidget) -> str:
    from arelis.ui.surface_report import _attrs as a

    return a(w)


def _tick(win: QWidget, cnt: _Count) -> None:
    from arelis.ui.persona_face.qq3d_avatar import QQ3DAvatar
    from arelis.ui.theme_tokens import active_theme

    hers = win.findChildren(QQ3DAvatar)
    for av in hers:
        if not getattr(av, "_diag_hooked", False):
            av.installEventFilter(cnt)
            av._diag_hooked = True
    frames = [getattr(getattr(av, "_render", None), "count", 0) for av in hers]
    log.info("[diag] theme=%s qq3d_frames=%s paints=%s attrs=%s visible=%s",
             active_theme(), frames, dict(cnt.n), _attrs(win),
             [av.isVisible() for av in hers])


def on_show(win: QWidget) -> None:
    import os

    from PySide6.QtWidgets import QApplication
    from shiboken6 import isValid

    from arelis.ui.glass import seal_tool_window

    app = QApplication.instance()
    if app is None or (app.platformName() == "offscreen" and not os.environ.get("ARELIS_DIAG")):
        return  # the suite: Windows launches only

    log.info("[diag] show attrs_before=%s", _attrs(win))

    def reseal() -> None:
        if not isValid(win):
            return
        seal_tool_window(win)
        log.info("[diag] resealed attrs_after=%s", _attrs(win))

    QTimer.singleShot(0, reseal)
    QTimer.singleShot(1000, reseal)
    if getattr(win, "_diag_timer", None) is None:
        cnt = _Count(win)
        win.installEventFilter(cnt)
        t = QTimer(win)
        t.setInterval(2000)
        t.timeout.connect(lambda: _tick(win, cnt))
        t.start()
        win._diag_timer = t
