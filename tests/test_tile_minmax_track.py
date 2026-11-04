"""A Filament tile's edge drag stops at its own min and max, so a title drag never clamps it."""

from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QWidget

from arelis.ui import window_resize


def _info():
    pt = lambda: SimpleNamespace(x=0, y=0)  # noqa: E731
    return SimpleNamespace(
        ptMaxPosition=pt(), ptMaxSize=pt(), ptMinTrackSize=pt(), ptMaxTrackSize=pt()
    )


def test_minmax_track_keeps_the_tile_limits() -> None:
    QApplication.instance() or QApplication([])
    tile = QWidget()
    tile.setMinimumSize(240, 180)
    tile.setMaximumSize(720, 800)
    info = _info()
    window_resize._fill_minmax_info(info, tile, virtual=(0, 0, 3840, 1080))
    assert (info.ptMaxTrackSize.x, info.ptMaxTrackSize.y) == (720, 800)
    assert (info.ptMinTrackSize.x, info.ptMinTrackSize.y) == (240, 180)
    assert (info.ptMaxSize.x, info.ptMaxSize.y) == (3840, 1080)
