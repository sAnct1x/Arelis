"""Live notification pill + expand card. Child of the conversation stage."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from arelis.notify.center import Notice
from arelis.ui.glass import GlassFrame
from arelis.ui.theme import GLASS

_NARROW_STAGE = 720


class NotifyOverlay(QWidget):
    """Top-right (or bottom-right when narrow) glass pill that blooms a card."""

    pill_clicked = Signal()
    dismiss_requested = Signal(str)
    snooze_requested = Signal(str)
    reply_requested = Signal(str)
    open_requested = Signal(str)
    collapsed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NotifyOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAutoFillBackground(False)
        self._notice: Notice | None = None
        self._extra = 0
        self._expanded = False
        self._maximized = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        root.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        self.pill = QToolButton(self)
        self.pill.setObjectName("NotifyPill")
        self.pill.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pill.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pill.setAutoRaise(True)
        self.pill.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.pill.clicked.connect(self._on_pill)
        root.addWidget(self.pill, alignment=Qt.AlignmentFlag.AlignRight)

        self.card = GlassFrame(
            self,
            object_name="NotifyCard",
            fill_alpha=int(GLASS.get("fill_float", 255)),
            radius=float(GLASS["radius"]),
            pulse_rim=False,
        )
        self.card.setFixedWidth(280)
        self.card.hide()
        card_l = QVBoxLayout(self.card)
        card_l.setContentsMargins(14, 12, 14, 12)
        card_l.setSpacing(8)

        self.card_title = QLabel("")
        self.card_title.setObjectName("NotifyCardTitle")
        self.card_title.setWordWrap(True)
        self.card_title.setCursor(Qt.CursorShape.PointingHandCursor)
        self.card_body = QLabel("")
        self.card_body.setObjectName("NotifyCardBody")
        self.card_body.setWordWrap(True)
        self.card_body.setCursor(Qt.CursorShape.PointingHandCursor)
        self.card_body.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        card_l.addWidget(self.card_title)
        card_l.addWidget(self.card_body)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.dismiss_btn = QPushButton("dismiss")
        self.snooze_btn = QPushButton("snooze")
        self.reply_btn = QPushButton("chat")
        self.open_btn = QPushButton("open")
        for btn in (
            self.dismiss_btn,
            self.snooze_btn,
            self.reply_btn,
            self.open_btn,
        ):
            btn.setObjectName("InstrumentAction")
            btn.setFixedHeight(28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            actions.addWidget(btn)
        card_l.addLayout(actions)
        root.addWidget(self.card, alignment=Qt.AlignmentFlag.AlignRight)

        self.dismiss_btn.clicked.connect(self._on_dismiss)
        self.snooze_btn.clicked.connect(self._on_snooze)
        self.reply_btn.clicked.connect(self._on_reply)
        self.open_btn.clicked.connect(self._on_open)
        self.card_title.installEventFilter(self)
        self.card_body.installEventFilter(self)

        self.hide()

    @property
    def expanded(self) -> bool:
        return self._expanded

    def show_notice(
        self,
        notice: Notice | None,
        *,
        extra: int = 0,
        maximized: bool = False,
        mailbox_open: bool = False,
    ) -> None:
        self._notice = notice
        self._extra = max(0, int(extra))
        self._maximized = bool(maximized)
        if notice is None or mailbox_open:
            self.collapse()
            self.hide()
            return
        label = notice.pill_label()
        if self._extra:
            label = f"{label} · +{self._extra}"
        self.pill.setText(label)
        self.pill.setToolTip(notice.body or notice.title)
        self.card_title.setText(notice.title)
        bodies = notice.data.get("bodies") or []
        if isinstance(bodies, list) and len(bodies) > 1:
            preview = "\n".join(str(b) for b in bodies[-3:] if str(b).strip())
            self.card_body.setText(preview or notice.body)
        else:
            self.card_body.setText(notice.body)
        kind = notice.kind
        self.reply_btn.setVisible(kind == "sms")
        self.snooze_btn.setVisible(kind in {"sms", "calendar", "email", "task"})
        self.open_btn.setVisible(kind != "allow")
        show_pill = not self._maximized
        self.pill.setVisible(show_pill)
        if self._expanded:
            self.card.show()
        else:
            self.card.hide()
        if show_pill or self._expanded:
            self.show()
            self.raise_()
            self.reposition()
        else:
            self.hide()

    def collapse(self) -> None:
        was = self._expanded
        self._expanded = False
        self.card.hide()
        if self._notice is None:
            self.hide()
        elif self._maximized:
            self.hide()
        else:
            self.pill.show()
            self.reposition()
        if was:
            self.collapsed.emit()

    def expand(self) -> None:
        if self._notice is None:
            return
        self._expanded = True
        self.card.show()
        self.show()
        self.raise_()
        self.reposition()

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None or self.isHidden():
            return
        hint = self.sizeHint()
        w = max(hint.width(), self.pill.sizeHint().width() + 4)
        if self._expanded:
            w = max(w, 280)
        h = hint.height()
        margin = 12
        narrow = parent.width() < _NARROW_STAGE
        if narrow and not self._maximized:
            x = max(margin, parent.width() - w - margin)
            y = max(margin, parent.height() - h - 72)
        else:
            x = max(margin, parent.width() - w - margin)
            y = margin
        self.setGeometry(x, y, w, h)
        self.raise_()

    def sizeHint(self) -> QSize:
        if self._expanded:
            return QSize(280, self.card.sizeHint().height() + (
                0 if self._maximized else self.pill.sizeHint().height() + 8
            ))
        return self.pill.sizeHint().expandedTo(QSize(120, 28))

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        clicked_card = obj in {self.card_title, self.card_body}
        if clicked_card and event.type() == QEvent.Type.MouseButtonRelease:
            if self._notice is not None and self._notice.kind == "sms":
                self._on_reply()
            else:
                self._on_open()
            return True
        return super().eventFilter(obj, event)

    def _on_pill(self) -> None:
        """Click the live pill — open the inbox on that notice."""
        notice_id = self._notice.id if self._notice is not None else ""
        if notice_id:
            self.open_requested.emit(notice_id)
        self.pill_clicked.emit()

    def _on_dismiss(self) -> None:
        if self._notice is not None:
            self.dismiss_requested.emit(self._notice.id)
        self.collapse()

    def _on_snooze(self) -> None:
        if self._notice is not None:
            self.snooze_requested.emit(self._notice.id)
        self.collapse()

    def _on_reply(self) -> None:
        if self._notice is not None:
            self.reply_requested.emit(self._notice.id)

    def _on_open(self) -> None:
        if self._notice is not None:
            self.open_requested.emit(self._notice.id)
