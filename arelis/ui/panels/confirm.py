from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from arelis.tools.confirm_copy import confirm_headline

# Enough to read a short email in full without the card taking over the window.
_DETAIL_MAX_HEIGHT = 220


class ConfirmCard(QWidget):
    """Inline glass confirm for write, image, and send tool calls."""

    decided = Signal(str, str, bool)  # id, decision allow|skip, allow_turn

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ConfirmCard")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._confirm_id = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        self.summary = QLabel("confirm tool")
        self.summary.setObjectName("ConfirmSummary")
        self.summary.setWordWrap(True)

        # Read-only rather than a label: an email body needs to scroll, and it
        # must never be interpreted as markup. Plain text is the whole point.
        self.detail = QTextEdit()
        self.detail.setObjectName("ConfirmDetail")
        self.detail.setReadOnly(True)
        self.detail.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.detail.setMaximumHeight(_DETAIL_MAX_HEIGHT)
        self.detail.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.detail.hide()

        self.note = QLabel("")
        self.note.setObjectName("ConfirmNote")
        self.note.setWordWrap(True)
        self.note.hide()

        self.allow_turn = QCheckBox("rest of this ask")
        self.allow_turn.setObjectName("ConfirmAllowTurn")

        row = QHBoxLayout()
        row.setSpacing(8)
        self.allow_btn = QPushButton("allow")
        self.skip_btn = QPushButton("deny")
        self.allow_btn.setObjectName("ConfirmAllow")
        self.skip_btn.setObjectName("ConfirmSkip")
        self.allow_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addStretch(1)
        row.addWidget(self.skip_btn)
        row.addWidget(self.allow_btn)

        layout.addWidget(self.summary)
        layout.addWidget(self.detail)
        layout.addWidget(self.note)
        layout.addWidget(self.allow_turn)
        layout.addLayout(row)

        self.allow_btn.clicked.connect(self._allow)
        self.skip_btn.clicked.connect(self._skip)
        self.hide()

    def ask(
        self,
        confirm_id: str,
        tool: str,
        summary: str,
        *,
        detail: str = "",
        note: str = "",
        batch_ok: bool = True,
        headline: str = "",
    ) -> None:
        self._confirm_id = confirm_id
        title = (headline or "").strip() or confirm_headline(tool, {})
        self.summary.setText(title)

        body = (detail or "").strip()
        summary_line = (summary or "").strip()
        # Detail pane when it adds more than the headline. Never dump the
        # tool(arg=…) trace onto the card — that lives in Thinking.
        show_detail = bool(body) and body != title and body != summary_line
        self.detail.setPlainText(body)
        self.detail.setVisible(show_detail)

        self.note.setText(note.strip())
        self.note.setVisible(bool(note.strip()))

        # Reset every time. A checkbox left ticked from a previous card would
        # silently widen the next approval to the whole turn.
        self.allow_turn.setChecked(False)
        self.allow_turn.setVisible(batch_ok)
        self.allow_turn.setText("rest of this ask")
        self.allow_turn.setToolTip("further steps in this reply, not forever")
        self.show()
        self.allow_btn.setFocus()

    def dismiss(self) -> None:
        """Hide without emitting a decision, for turns that ended elsewhere."""
        self._confirm_id = ""
        self.hide()

    def _allow(self) -> None:
        if not self._confirm_id:
            return
        # isVisible() guards the batch flag as well as the tick: a hidden
        # checkbox must never report True, whatever it was left holding.
        batch = self.allow_turn.isVisible() and self.allow_turn.isChecked()
        confirm_id = self._confirm_id
        self.dismiss()
        self.decided.emit(confirm_id, "allow", batch)

    def _skip(self) -> None:
        if not self._confirm_id:
            return
        confirm_id = self._confirm_id
        self.dismiss()
        self.decided.emit(confirm_id, "skip", False)
