"""The banner that says which room owns this conversation.

Entering a room swaps three things at once — the thread, the project folder and
the model role — and every one of them is invisible. Without something on screen
saying so, the only difference between the physics room and the general
conversation is that she answers differently, which reads as her being
inconsistent rather than as you being somewhere else.

So the strip is not decoration; it is the answer to "why did she just say that".
It sits above the transcript, holds the name, the purpose she is being given,
and the folder she is writing to, and it is the way back out.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolButton

from arelis.ui.glass import GlassFrame


class RoomStrip(GlassFrame):
    """Thin plate above the transcript. Hidden whenever no room is open."""

    leave_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(
            parent,
            object_name="RoomStrip",
            fill_alpha=96,
            radius=10.0,
            pulse_rim=False,
        )
        self.setFixedHeight(38)
        self._room_id = ""

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 4, 8, 4)
        row.setSpacing(10)

        self.name = QLabel("")
        self.name.setObjectName("RoomName")
        row.addWidget(self.name)

        self.detail = QLabel("")
        self.detail.setObjectName("RoomDetail")
        self.detail.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        row.addWidget(self.detail, stretch=1)

        self.leave_btn = QToolButton()
        self.leave_btn.setObjectName("RoomLeaveButton")
        self.leave_btn.setText("leave")
        self.leave_btn.setFixedHeight(26)
        self.leave_btn.setMinimumWidth(52)
        self.leave_btn.setToolTip("back to the general conversation")
        self.leave_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.leave_btn.setAutoRaise(True)
        self.leave_btn.clicked.connect(self.leave_requested.emit)
        row.addWidget(self.leave_btn)

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
            self.detail.setText("")
            self.hide()
            return
        self.name.setText(name or self._room_id)
        bits = []
        if purpose:
            bits.append(_one_line(purpose))
        if root:
            bits.append(f"· {root}")
        self.detail.setText("  ".join(bits))
        self.detail.setToolTip(purpose or "")
        self.show()


def _one_line(text: str, limit: int = 96) -> str:
    """Purpose is a paragraph by design; the strip has one line for it.

    The full text is on the tooltip, and she is reading all of it either way.
    """
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rstrip() + "…"
