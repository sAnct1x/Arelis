"""Float a thinking-like dock under the real theme and save a screenshot.

Run:
  python -m arelis.ui._smoke_floating_dock
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from arelis.ui.app import _apply_floating_dock_chrome, _hide_dock_title
from arelis.ui.chrome import FloatingDockTitleBar
from arelis.ui.glass_dock import GlassDockWidget
from arelis.ui.panels.instrument import InstrumentPanel
from arelis.ui.theme import stylesheet

_OUT = Path(__file__).resolve().parents[2] / "logs" / "floating_dock_smoke.png"


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(stylesheet())

    win = QMainWindow()
    win.setWindowTitle("Arelis dock smoke")
    win.resize(1100, 720)
    central = QLabel("chat stage (behind)\nthis text must NOT ghost through the float")
    central.setAlignment(Qt.AlignmentFlag.AlignCenter)
    central.setStyleSheet("color: #ffb457; font-size: 18px; background: #0a0806;")
    win.setCentralWidget(central)

    body = QPlainTextEdit()
    body.setPlainText(
        "status loaded conversation smoke\n"
        "status Inbound notify ready\n"
        "status Speech model ready."
    )
    body.setReadOnly(True)
    host = InstrumentPanel("thinking", body)

    dock = GlassDockWidget("thinking", win)
    dock.setObjectName("ThinkingDock")
    shell = QWidget()
    shell.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    lay = QVBoxLayout(shell)
    lay.setContentsMargins(6, 12, 12, 14)
    lay.addWidget(host)
    dock.setWidget(shell)
    _hide_dock_title(dock)
    win.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    win.show()
    app.processEvents()

    result: dict[str, object] = {"ok": True}

    def _check_and_quit() -> None:
        ok = True
        if not dock.isVisible():
            print("FAIL: floating dock not visible")
            ok = False
        if not dock.isFloating():
            print("FAIL: dock is not floating")
            ok = False
        if not (dock.windowFlags() & Qt.WindowType.FramelessWindowHint):
            print("FAIL: floating dock missing FramelessWindowHint")
            ok = False
        if dock.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
            print("FAIL: floating dock still translucent (chat can bleed)")
            ok = False
        chrome = [c for c in host.findChildren(FloatingDockTitleBar) if c.isVisible()]
        if not chrome:
            print("FAIL: in-panel FloatingDockTitleBar not visible")
            ok = False
        if host.title_label.isVisible():
            print("FAIL: docked title label still visible while floating")
            ok = False
        if dock.graphicsEffect() is not None:
            print("FAIL: graphics opacity effect on floating dock")
            ok = False

        _OUT.parent.mkdir(parents=True, exist_ok=True)
        pix = dock.grab()
        if pix.isNull() or pix.width() < 100:
            print("FAIL: dock.grab() empty")
            ok = False
        else:
            pix.save(str(_OUT))
            print(f"SHOT: {_OUT} ({pix.width()}x{pix.height()})")

        print(
            f"INFO: floating={dock.isFloating()} visible={dock.isVisible()} "
            f"frameless={bool(dock.windowFlags() & Qt.WindowType.FramelessWindowHint)} "
            f"translucent={dock.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)} "
            f"chrome={len(chrome)} fill_alpha={host._fill_alpha} mode=opaque"
        )
        if int(getattr(host, "_fill_alpha", 0)) < 240:
            print("FAIL: floating fill_alpha too low (chat can bleed through)")
            ok = False
        result["ok"] = ok
        app.quit()

    assert dock.isVisible(), "dock should start visible"
    dock.setFloating(True)
    app.processEvents()
    _apply_floating_dock_chrome(dock, True)
    host.apply_floating_look(True)
    dock.show()
    dock.raise_()
    app.processEvents()
    QTimer.singleShot(150, _check_and_quit)
    app.exec()

    if result["ok"]:
        print("PASS: void floating dock chrome smoke")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
