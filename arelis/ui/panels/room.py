"""The banner that says which room owns this conversation.

Entering a room swaps three things at once — the thread, the project folder and
the model role — and every one of them is invisible. Without something on screen
saying so, the only difference between Reality and the general
conversation is that she answers differently, which reads as her being
inconsistent rather than as you being somewhere else.

So the strip is not decoration; it is the answer to "why did she just say that".
It sits above the transcript as type in the void, not a second title bar.
Leave is never optional chrome.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolButton, QWidget

from arelis.ui.theme import METRICS
from arelis.ui.world_host import should_offer_world


class _ElideLabel(QLabel):
    """Purpose yields. Leave does not."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)

    def set_full(self, text: str) -> None:
        self._full = text or ""
        self._elide()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        if self.width() <= 8:
            self.setText(self._full)
            return
        metrics = self.fontMetrics()
        self.setText(
            metrics.elidedText(self._full, Qt.TextElideMode.ElideRight, self.width())
        )


class RoomStrip(QWidget):
    """Quiet line above the transcript. Hidden whenever no room is open."""

    leave_requested = Signal()
    world_requested = Signal()
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("RoomStrip")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setFixedHeight(METRICS["row"])
        self._room_id = ""

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        self.name = QLabel("")
        self.name.setObjectName("RoomName")
        self.name.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        row.addWidget(self.name)

        self.detail = _ElideLabel()
        self.detail.setObjectName("RoomDetail")
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        row.addWidget(self.detail, stretch=1)

        self.world_btn = _chip("RoomWorldButton", "open", "open Reality")
        self.world_btn.clicked.connect(self.world_requested.emit)
        self.world_btn.hide()
        row.addWidget(self.world_btn, 0, Qt.AlignmentFlag.AlignRight)

        self.leave_btn = _chip("RoomLeaveButton", "leave", "back to the general conversation")
        self.leave_btn.clicked.connect(self.leave_requested.emit)
        row.addWidget(self.leave_btn, 0, Qt.AlignmentFlag.AlignRight)

        self.hide()

    @property
    def room_id(self) -> str:
        return self._room_id

    def set_room(
        self, room_id: str, name: str = "", purpose: str = "", root: str = ""
    ) -> None:
        """Paint the open room, or hide when room_id is empty."""
        self._room_id = room_id or ""
        if not self._room_id:
            self.name.setText("")
            self.detail.set_full("")
            self.detail.setToolTip("")
            self.world_btn.hide()
            self.hide()
            self.changed.emit()
            return
        self.world_btn.setVisible(should_offer_world(self._room_id))
        self.name.setText(name or self._room_id)
        purpose_line = _one_line(purpose) if purpose else ""
        self.detail.set_full(purpose_line)
        tip_bits = [purpose] if purpose else []
        if root:
            tip_bits.append(root)
        self.detail.setToolTip(" · ".join(tip_bits))
        self.show()
        self.changed.emit()


def _chip(obj: str, text: str, tooltip: str) -> QToolButton:
    btn = QToolButton()
    btn.setObjectName(obj)
    btn.setText(text)
    btn.setFixedHeight(METRICS["row"])
    btn.setMinimumWidth(44)
    btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    btn.setToolTip(tooltip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setAutoRaise(True)
    return btn


def _one_line(text: str, limit: int = 96) -> str:
    """Purpose is a paragraph by design; the strip has one line for it."""
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rstrip() + "…"
