"""With no worker frame yet, the window paints the void and never the field on the UI thread."""

from __future__ import annotations

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QWidget


def test_paint_event_without_a_worker_frame_never_paints_the_field(monkeypatch):
    QApplication.instance() or QApplication([])
    from arelis.ui import window_chrome
    from arelis.ui.filament_field import FILAMENT_VOID, FilamentField

    monkeypatch.setattr(window_chrome, "active_theme", lambda: "filament")
    painted = []
    monkeypatch.setattr(FilamentField, "_paint", lambda self, p, r: painted.append(r))

    class NoFrameYet:
        def frame_for(self, rect, dpr):
            return None

        def frame(self):
            return None

    class Win(QWidget):
        paintEvent = window_chrome.WindowChrome.paintEvent  # noqa: N815

    win = Win()
    win.resize(320, 200)
    win._filament = FilamentField()
    win._filament_render = NoFrameYet()
    img = QImage(320, 200, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    win.render(img)
    assert painted == []
    assert img.pixelColor(160, 100) == QColor(*FILAMENT_VOID)
