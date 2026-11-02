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


def _surface(win: QWidget) -> str:
    """Main HWND format alpha and whether Windows made it a layered window."""
    h = win.windowHandle()
    alpha = h.format().alphaBufferSize() if h is not None else "nohandle"
    ex = "n/a"
    try:
        import ctypes

        ex_style = ctypes.windll.user32.GetWindowLongW(int(win.winId()), -20)
        ex = f"0x{ex_style & 0xFFFFFFFF:x} layered={bool(ex_style & 0x80000)}"
    except (AttributeError, OSError):
        ex = "n/a (not windows)"
    return f"alpha={alpha} exstyle={ex}"


def pre_create(win: QWidget) -> None:
    """Create the main HWND with an alpha-free format (her qq3d default format asks for
    alpha 8, which makes a frameless Windows top-level a layered window)."""
    import os

    from PySide6.QtGui import QSurfaceFormat
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None or (app.platformName() == "offscreen" and not os.environ.get("ARELIS_DIAG")):
        return
    if os.environ.get("ARELIS_DIAG_KEEP_ALPHA"):
        return
    keep = QSurfaceFormat.defaultFormat()
    if keep.alphaBufferSize() <= 0:
        return
    opaque = QSurfaceFormat(keep)
    opaque.setAlphaBufferSize(0)
    QSurfaceFormat.setDefaultFormat(opaque)
    try:
        win.winId()
    finally:
        QSurfaceFormat.setDefaultFormat(keep)
    log.info("[diag] pre_create %s", _surface(win))


def _tick(win: QWidget, cnt: _Count) -> None:
    from arelis.ui.persona_face.qq3d_avatar import QQ3DAvatar
    from arelis.ui.theme_tokens import active_theme

    hers = win.findChildren(QQ3DAvatar)
    for av in hers:
        if not getattr(av, "_diag_hooked", False):
            av.installEventFilter(cnt)
            av._diag_hooked = True
    n = getattr(win, "_diag_n", 0) + 1
    win._diag_n = n
    if n in (2, 5, 10):  # about 4, 10 and 20 s after show
        import os
        import tempfile

        out = os.path.join(tempfile.gettempdir(), "arelis_diag")
        os.makedirs(out, exist_ok=True)
        img = win.grab().toImage()
        path = os.path.join(out, f"grab_{active_theme()}_{n * 2:02d}s.png")
        img.save(path)
        dark = sum(1 for y in range(0, img.height(), 16) for x in range(0, img.width(), 16)
                   if img.pixelColor(x, y).value() < 8)
        total = len(range(0, img.height(), 16)) * len(range(0, img.width(), 16))
        log.info("[diag] grab %s black_frac=%.2f", path, dark / max(1, total))
    frames = [getattr(getattr(av, "_render", None), "count", 0) for av in hers]
    log.info("[diag] theme=%s qq3d_frames=%s paints=%s attrs=%s visible=%s %s",
             active_theme(), frames, dict(cnt.n), _attrs(win),
             [av.isVisible() for av in hers], _surface(win))


def on_show(win: QWidget) -> None:
    import os

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None or (app.platformName() == "offscreen" and not os.environ.get("ARELIS_DIAG")):
        return  # the suite: Windows launches only

    log.info("[diag] show attrs_before=%s", _attrs(win))

    log.info("[diag] show %s", _surface(win))
    if getattr(win, "_diag_timer", None) is None:
        cnt = _Count(win)
        win.installEventFilter(cnt)
        t = QTimer(win)
        t.setInterval(2000)
        t.timeout.connect(lambda: _tick(win, cnt))
        t.start()
        win._diag_timer = t
