"""The banner that says which room owns this conversation.

Entering a room swaps three things at once — the thread, the project folder and
the model role — and every one of them is invisible. Without something on screen
saying so, the only difference between the physics room and the general
conversation is that she answers differently, which reads as her being
inconsistent rather than as you being somewhere else.

So the strip is not decoration; it is the answer to "why did she just say that".
It sits above the transcript, holds the name, a short purpose that may elide,
and the way back out. Leave is never optional chrome.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolButton

from arelis.spatial import PHYSICS_ROOM_ID
from arelis.ui.glass import GlassFrame
from arelis.ui.theme import GLASS


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

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
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


class RoomStrip(GlassFrame):
    """Thin plate above the transcript. Hidden whenever no room is open."""

    leave_requested = Signal()
    world_requested = Signal()
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(
            parent,
            object_name="RoomStrip",
            fill_alpha=int(GLASS.get("fill_strip", 120)),
            radius=float(GLASS["radius"]),
            pulse_rim=False,
        )
        self.setFixedHeight(38)
        self._room_id = ""

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 4, 8, 4)
        row.setSpacing(10)

        self.name = QLabel("")
        self.name.setObjectName("RoomName")
        self.name.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        row.addWidget(self.name)

        self.detail = _ElideLabel()
        self.detail.setObjectName("RoomDetail")
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        row.addWidget(self.detail, stretch=1)

        self.world_btn = _chip("RoomWorldButton", "world", "open the physics world")
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
        self.world_btn.setVisible(self._room_id == PHYSICS_ROOM_ID)
        self.name.setText(name or self._room_id)
        bits = []
        if purpose:
            bits.append(_one_line(purpose))
        if root:
            bits.append(f"· {root}")
        full = "  ".join(bits)
        self.detail.set_full(full)
        self.detail.setToolTip(purpose or full)
        self.show()
        self.changed.emit()


def _chip(obj: str, text: str, tooltip: str) -> QToolButton:
    btn = QToolButton()
    btn.setObjectName(obj)
    btn.setText(text)
    btn.setFixedHeight(26)
    btn.setMinimumWidth(52)
    btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    btn.setToolTip(tooltip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setAutoRaise(True)
    return btn


def _one_line(text: str, limit: int = 96) -> str:
    """Purpose is a paragraph by design; the strip has one line for it.

    The full text is on the tooltip, and she is reading all of it either way.
    """
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rstrip() + "…"
