"""Title bar and composer buttons say what they do.

On main the view and rooms buttons had an empty tooltip.
"""

from __future__ import annotations

from PySide6.QtWidgets import QToolButton

from arelis.ui.chrome import TitleBar
from arelis.ui.panels.conversation import ConversationStage


def test_title_bar_buttons_have_tooltips(qt_app) -> None:
    bar = TitleBar()
    assert bar.view_btn.toolTip() == "panels and layout"
    assert bar.rooms_btn.toolTip() == "rooms: places she can work in"
    missing = [
        btn.objectName() or btn.text()
        for btn in bar.findChildren(QToolButton)
        if not btn.toolTip().strip()
    ]
    assert missing == []
    del qt_app


def test_composer_buttons_have_tooltips(qt_app) -> None:
    stage = ConversationStage()
    missing = [
        btn.objectName() or btn.text()
        for btn in stage._composer.findChildren(QToolButton)
        if not btn.toolTip().strip()
    ]
    assert missing == []
    stage.close()
    del qt_app
