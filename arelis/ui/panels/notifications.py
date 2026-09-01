"""Inbox list for the floating notifications window."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from arelis.notify.center import Notice

_HINT_LIVE = "while Arelis is open — texts, calendar, mail, jobs"
_HINT_CAUGHT_UP = "caught up"


class NotificationsPanel(QWidget):
    """Grouped inbox rows with unread tracking for the View-menu badge."""

    unread_changed = Signal(int)
    opened = Signal()
    notice_activated = Signal(str)
    chat_requested = Signal(str)
    artifact_requested = Signal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self._items: list[dict[str, object]] = []
        self._unread = 0
        self._open_id = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.hint = QLabel(_HINT_CAUGHT_UP)
        self.hint.setObjectName("InstrumentHint")
        layout.addWidget(self.hint)

        self.list = QListWidget()
        self.list.setObjectName("NotificationsList")
        self.list.setFrameShape(QListWidget.Shape.NoFrame)
        self.list.setSpacing(2)
        self.list.setUniformItemSizes(False)
        self.list.setWordWrap(True)
        # Width-0 size hints + ElideRight collapsed a contact name to "Robin…".
        self.list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.itemClicked.connect(self._on_item)
        self.list.itemActivated.connect(self._on_item)
        self.list.itemDoubleClicked.connect(self._on_double)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_menu)
        layout.addWidget(self.list, stretch=1)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.mark_read_btn = QPushButton("clear")
        self.mark_read_btn.setObjectName("InstrumentAction")
        self.mark_read_btn.setFixedHeight(28)
        self.mark_read_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(self.mark_read_btn)
        row.addStretch(1)
        layout.addLayout(row)

    @property
    def unread_count(self) -> int:
        return self._unread

    def add_message(
        self,
        *,
        message_id: str,
        from_label: str,
        body: str,
        time_text: str = "",
        kind: str = "sms",
        sticky: bool = False,
    ) -> None:
        entry = {
            "id": message_id,
            "from": from_label,
            "body": body,
            "time": time_text,
            "kind": kind,
            "unread": True,
            "sticky": sticky,
        }
        self._items.insert(0, entry)
        self._unread += 1
        self._rebuild()
        self.unread_changed.emit(self._unread)

    def set_notices(self, notices: list[Notice], *, unread: int | None = None) -> None:
        self._items = [
            {
                "id": n.id,
                "from": n.title,
                "body": n.body,
                "time": n.pill_label(),
                "kind": n.kind,
                "unread": n.unread,
                "sticky": n.sticky,
                "path": str((n.data or {}).get("path") or ""),
            }
            for n in notices
        ]
        self._unread = (
            int(unread)
            if unread is not None
            else sum(1 for e in self._items if e.get("unread"))
        )
        self._rebuild()
        self.unread_changed.emit(self._unread)

    def clear(self) -> None:
        """Drop every row the operator can dismiss. Sticky Allow/job stay."""
        self._items = [e for e in self._items if e.get("sticky")]
        self._unread = sum(1 for e in self._items if e.get("unread"))
        self._open_id = ""
        self._rebuild()
        self.unread_changed.emit(self._unread)

    def show_notice(self, notice_id: str) -> None:
        """Select the row. The body already lives on the row — do not clone it."""
        self._open_id = notice_id
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item is not None and str(item.data(Qt.ItemDataRole.UserRole) or "") == notice_id:
                self.list.setCurrentItem(item)
                break

    def _on_item(self, item: QListWidgetItem) -> None:
        mid = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not mid:
            return
        changed = False
        for entry in self._items:
            if str(entry.get("id")) == mid and entry.get("unread"):
                entry["unread"] = False
                changed = True
        self.show_notice(mid)
        if changed:
            self._unread = sum(1 for e in self._items if e.get("unread"))
            self._rebuild()
            self.unread_changed.emit(self._unread)
        self.notice_activated.emit(mid)
        if self._kind_for(mid) == "sms":
            self.chat_requested.emit(mid)

    def _kind_for(self, notice_id: str) -> str:
        for entry in self._items:
            if str(entry.get("id")) == notice_id:
                return str(entry.get("kind") or "")
        return ""

    def _path_for(self, notice_id: str) -> str:
        for entry in self._items:
            if str(entry.get("id")) == notice_id:
                return str(entry.get("path") or "").strip()
        return ""

    def _on_double(self, item: QListWidgetItem) -> None:
        mid = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not mid:
            return
        if self._kind_for(mid) == "sms":
            self.chat_requested.emit(mid)
            return
        if self._path_for(mid):
            self.artifact_requested.emit(mid, "open")

    def _on_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        mid = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not mid:
            return
        menu = QMenu(self)
        if self._kind_for(mid) == "sms":
            open_act = QAction("Open as chat", menu)
            menu.addAction(open_act)
            chosen = menu.exec(self.list.mapToGlobal(pos))
            if chosen is open_act:
                self.chat_requested.emit(mid)
            return
        if not self._path_for(mid):
            return
        open_act = QAction("Open", menu)
        with_act = QAction("Open with…", menu)
        reveal_act = QAction("Show in folder", menu)
        menu.addAction(open_act)
        menu.addAction(with_act)
        menu.addAction(reveal_act)
        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen is open_act:
            self.artifact_requested.emit(mid, "open")
        elif chosen is with_act:
            self.artifact_requested.emit(mid, "openas")
        elif chosen is reveal_act:
            self.artifact_requested.emit(mid, "reveal")

    def _rebuild(self) -> None:
        self.list.clear()
        self.hint.setText(_HINT_LIVE if self._items else _HINT_CAUGHT_UP)
        for entry in self._items:
            from_label = str(entry.get("from") or "").strip() or "unknown"
            body = str(entry.get("body") or "").replace("\n", " ").strip()
            time_text = str(entry.get("time") or "").strip()
            unread = bool(entry.get("unread"))
            mark = "●" if unread else "○"
            head = f"{mark}  {from_label}"
            preview = body or "(no body)"
            if time_text and time_text != from_label:
                item_text = f"{head}\n{time_text}  ·  {preview}"
            else:
                item_text = f"{head}\n{preview}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, str(entry.get("id") or ""))
            tip = str(entry.get("body") or "")
            if time_text:
                tip = f"{time_text}\n{tip}".strip()
            item.setToolTip(tip)
            font = item.font()
            font.setBold(unread)
            item.setFont(font)
            item.setSizeHint(self._row_size(item_text))
            self.list.addItem(item)
        if self._open_id:
            self.show_notice(self._open_id)

    def _row_size(self, text: str) -> QSize:
        fm = self.list.fontMetrics()
        width = max(self.list.viewport().width(), 240)
        inner = max(width - 16, 160)
        height = 10
        for line in (text or "").split("\n"):
            bounds = fm.boundingRect(
                0,
                0,
                inner,
                4000,
                Qt.TextFlag.TextWordWrap,
                line,
            )
            height += max(bounds.height(), fm.lineSpacing())
        return QSize(width, max(height, fm.lineSpacing() * 2 + 12))
