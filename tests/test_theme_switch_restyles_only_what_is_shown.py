"""A room switch restyles what is on screen and leaves hidden tiles for later.

The app sheet stays put, so Qt does not re-match every widget in every hidden
tile window; a tile takes the new room's colour when it is next shown.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QWidget

from arelis.ui import theme
from arelis.ui.theme_layers import split_sheet, stamp


def test_hidden_tile_waits_for_show_and_app_sheet_never_changes() -> None:
    app = QApplication.instance() or QApplication([])
    before = theme.active_theme()
    hub = QMainWindow()
    hub.setCentralWidget(QLabel("stage"))
    tile = QWidget(hub, Qt.WindowType.Window)
    QLabel("tile", tile)
    try:
        theme.apply_theme("night")
        theme.install_stylesheet(hub)
        hub.show()
        tile.show()
        app.processEvents()
        tile.hide()
        app_sheet = app.styleSheet()

        theme.apply_theme("filament")
        theme.install_stylesheet(hub)
        app.processEvents()
        assert app.styleSheet() == app_sheet
        assert stamp(hub.centralWidget()) == "filament"
        assert stamp(tile) == "night"

        tile.show()
        app.processEvents()
        assert stamp(tile) == "filament"
        assert tile.styleSheet() == split_sheet(theme.stylesheet())[1]
    finally:
        tile.close()
        hub.close()
        hub.deleteLater()
        theme.apply_theme(before)
        theme.install_stylesheet()
        app.processEvents()
