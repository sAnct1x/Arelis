"""The idle Filament orbit tree hides the Reality float (bead, hit, desk title); listening brings it back."""

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from arelis.ui import filament_desk
from arelis.ui.filament_field import FilamentField


class _Floats:
    def __init__(self) -> None:
        self.skipped: dict[str, bool] = {}

    def skip(self, name: str, on: bool) -> None:
        self.skipped[name] = on

    def __getattr__(self, _name):
        return lambda *a, **k: None


def _bead_lit(field: FilamentField, rect: QRect) -> bool:
    img = QImage(rect.size(), QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.black)
    p = QPainter(img)
    field._paint_beads(p, rect)
    p.end()
    c = field.bead_point("reality", rect).toPoint()
    return any(
        img.pixelColor(c.x() + dx, c.y() + dy).lightness() > 40
        for dx in range(-3, 4)
        for dy in range(-3, 4)
    )


def test_idle_tree_hides_reality_until_listening(monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(filament_desk, "active_theme", lambda: "filament")
    monkeypatch.setattr(filament_desk, "world_available", lambda: True)
    w = QWidget()
    w.resize(1280, 696)
    w._filament = FilamentField()
    w._filament_floats = _Floats()
    w._filament_chat_open = False
    field, rect = w._filament, QRect(0, 0, 1280, 696)
    field.gpu_tree = True

    for form, hidden in ((0.0, True), (0.34, True), (0.35, False)):
        field.form = form
        filament_desk.place_filament_floats(w, reshape=False)
        assert w._filament_floats.skipped["reality"] is hidden, form
        assert _bead_lit(field, rect) is not hidden, form
        at = field.bead_point("reality", rect).toPoint()
        assert (field.hit_float(QPoint(at), rect) == "reality") is not hidden, form
