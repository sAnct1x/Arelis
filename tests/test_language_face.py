"""Switching to Chinese changes the app font, not the app stylesheet."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QFontDatabase, QFontInfo, QTextLayout
from PySide6.QtWidgets import QApplication, QLabel

from arelis import i18n

CJK = "Noto Sans CJK SC"
SAMPLE = "明天天气怎么样？设置日历"


def test_chinese_face_reaches_every_label_without_a_new_app_sheet(
    arelis_window, monkeypatch
) -> None:
    if CJK not in QFontDatabase.families():
        pytest.skip(f"{CJK} is not installed")
    monkeypatch.setattr(i18n, "cjk_family", lambda: CJK)
    app = QApplication.instance()
    window = arelis_window()
    window.show()
    i18n.apply_language(window, "en")
    sheet = app.styleSheet()
    try:
        i18n.apply_language(window, "zh")
        # The full sheet re-apply was the 300 ms of the switch.
        assert app.styleSheet() == sheet
        labels = [w for w in window.findChildren(QLabel) if w.isVisible()]
        assert labels
        for label in labels:
            font = label.font()
            assert QFontInfo(font).family() == CJK, label.objectName()
            layout = QTextLayout(SAMPLE, font)
            layout.beginLayout()
            layout.createLine()
            layout.endLayout()
            runs = layout.glyphRuns()
            assert {run.rawFont().familyName() for run in runs} == {CJK}
            assert all(0 not in run.glyphIndexes() for run in runs)
    finally:
        i18n.apply_language(window, "en")
