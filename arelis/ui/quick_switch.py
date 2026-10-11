"""Jump to a conversation without leaving the keyboard.

A small list, pinned chats first, filtered the same way History is.
Enter opens the one that is highlighted. Escape closes the list.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyleFactory,
    QWidget,
)

from arelis.attachments import display_session_title
from arelis.ui.dialog import GlassDialog
from arelis.ui.panels.history import PIN_MARK, _pinned_first, filter_history_sessions


class QuickSwitch(GlassDialog):
    """Type a few words, then press Enter to open that conversation."""

    def __init__(self, window) -> None:
        # The base dialog installs this object as an event filter before
        # the search box exists. Leave a placeholder so that filter is safe.
        self.search: QLineEdit | None = None
        self.chosen_id = ""
        parent = window if isinstance(window, QWidget) else None
        super().__init__("Jump to a conversation", parent=parent, width=440)
        self.setObjectName("QuickSwitch")
        history = getattr(window, "history", None)
        sessions = list(getattr(history, "_sessions", None) or [])
        self._sessions = _pinned_first(sessions)
        self._store = getattr(history, "_store", None) if history is not None else None

        self.search = QLineEdit()
        self.search.setObjectName("InstrumentSearch")
        self.search.setPlaceholderText("Find a conversation")
        self.search.setToolTip("Type a few words, then press Enter")
        self.search.textChanged.connect(self._refill)
        self.search.returnPressed.connect(self._choose_current)
        self.search.installEventFilter(self)
        self.body.addWidget(self.search)

        self.empty = self.add_text("nothing here yet", role="HistoryEmpty")

        self.list = QListWidget()
        self.list.setObjectName("HistoryList")
        self.list.setFrameShape(QListWidget.Shape.NoFrame)
        self.list.setMinimumHeight(220)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemActivated.connect(lambda _item: self._choose_current())
        fusion = QStyleFactory.create("Fusion")
        if fusion is not None:
            fusion.setParent(self)
            self.list.setStyle(fusion)
        self.body.addWidget(self.list)
        self._refill("")

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        parent = self.parentWidget()
        if parent is not None:
            center = parent.frameGeometry().center()
            geo = self.frameGeometry()
            geo.moveCenter(center)
            self.move(geo.topLeft())
        self.search.setFocus()
        self.search.selectAll()

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if (
            self.search is not None
            and obj is self.search
            and event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
        ):
            if event.key() == Qt.Key.Key_Down:
                self._move(1)
                return True
            if event.key() == Qt.Key.Key_Up:
                self._move(-1)
                return True
        return super().eventFilter(obj, event)

    def _move(self, step: int) -> None:
        count = self.list.count()
        if count <= 0:
            return
        row = self.list.currentRow()
        if row < 0:
            row = 0
        else:
            row = max(0, min(count - 1, row + step))
        self.list.setCurrentRow(row)

    def _refill(self, text: str) -> None:
        rows = _pinned_first(
            filter_history_sessions(self._sessions, text, store=self._store)
        )
        self.list.clear()
        for session in rows:
            title = display_session_title(str(session.get("title") or ""))
            pinned = bool(session.get("pinned"))
            label = f"{PIN_MARK} {title}" if pinned else title
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, str(session.get("id") or ""))
            item.setToolTip(f"{title}\npinned" if pinned else title)
            self.list.addItem(item)
        self.empty.setVisible(self.list.count() == 0)
        self.empty.setText("nothing matches" if text.strip() else "nothing here yet")
        if self.list.count():
            self.list.setCurrentRow(0)

    def _choose_current(self) -> None:
        item = self.list.currentItem()
        if item is None and self.list.count():
            item = self.list.item(0)
        if item is None:
            return
        sid = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not sid:
            return
        self.chosen_id = sid
        self.accept()


def open_quick_switch(window) -> None:
    """Show the jump list and open the conversation that was chosen."""
    from arelis.ui.history_host import on_history_selected, refresh_history

    if getattr(window, "history", None) is not None:
        refresh_history(window)
    dialog = QuickSwitch(window)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    if dialog.chosen_id:
        on_history_selected(window, dialog.chosen_id)
