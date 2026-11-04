"""While her scene loads, or when it cannot start, a still theme-tinted veil shows. No head."""

from __future__ import annotations

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QWidget


def test_no_model_shows_only_a_theme_tinted_veil(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARELIS_AVATAR_GLB", str(tmp_path / "missing.glb"))
    QApplication.instance() or QApplication([])
    from arelis.ui.persona_face import PersonaPanel
    from arelis.ui.theme import color

    panel = PersonaPanel()
    panel.resize(370, 520)
    assert panel.is_loading() and panel.web is None
    shown = [w for w in panel.children() if hasattr(w, "isHidden") and not w.isHidden()]
    assert shown == [panel.loading]
    img = QImage(panel.loading.size(), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    panel.loading.render(img, renderFlags=QWidget.RenderFlag.DrawChildren)
    accent = QColor(color("accent"))
    hues = set()
    for y in range(0, img.height(), 9):
        for x in range(0, img.width(), 9):
            c = img.pixelColor(x, y)
            if c.alpha() > 20:
                hues.add(c.hsvHue())
    # One calm wash in the accent hue: a face would add skin, hair and eye colours.
    assert hues and all(abs(h - accent.hsvHue()) <= 8 for h in hues)
