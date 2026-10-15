"""One app, not eleven. Guards the things the audit found drifting apart."""

from __future__ import annotations

from PySide6.QtCore import Qt

from arelis.ui.panels.conversation import ConversationStage
from arelis.ui.panels.workspace import (
    WorkspacePanel,
)
from arelis.ui.theme import COLORS, stylesheet


def test_role_popup_fills_the_plate(qt_app) -> None:
    """Windows reserved a scrollbar lane; transparent track showed a black strip."""

    stage = ConversationStage()
    try:
        view = stage.role.view()
        assert view is not None
        assert (
            view.verticalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        assert (
            view.horizontalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        parent = view.parentWidget()
        assert parent is not None
        assert parent.objectName() == "ComboPopup"
        css = stylesheet()
        assert COLORS["menu_fill"] in css
        assert "max-width: 96px" not in css.split("#RoleSelect QAbstractItemView")[1][:120]
    finally:
        stage.deleteLater()


def _browse_names(panel: WorkspacePanel) -> list[str]:
    return [
        panel.browse_list.item(i).text()
        for i in range(panel.browse_list.count())
    ]


