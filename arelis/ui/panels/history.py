"""Past sessions and pending facts waiting for a click."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QStyleFactory,
    QVBoxLayout,
    QWidget,
)

from arelis.attachments import display_session_title as _display_session_title
from arelis.ui.dialog import confirm


class HistoryPanel(QWidget):
    """Session list with search, plus a review queue for pending facts.

    Nothing proposed reaches active without a click here. Durable active facts
    are managed in Settings → Memory (forget).
    """

    session_selected = Signal(str)
    session_delete_requested = Signal(str)
    new_requested = Signal()
    # One or many fact ids + status (active|rejected). Batch so multi-select
    # and reject-all refresh History once, not once per row.
    fact_decided = Signal(object, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self._sessions: list[dict[str, str]] = []
        self._active_id = ""
        self._list_fp: tuple[tuple[str, str, str], ...] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.search = QLineEdit()
        self.search.setObjectName("InstrumentSearch")
        self.search.setPlaceholderText("search sessions…")
        self.search.setFixedHeight(28)
        self.search.textChanged.connect(self._apply_filter)
        self.new_btn = QPushButton("new")
        self.new_btn.setObjectName("InstrumentAction")
        self.new_btn.setFixedHeight(28)
        self.new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_btn.setToolTip("Start a fresh conversation")
        self.new_btn.clicked.connect(self.new_requested.emit)
        row.addWidget(self.search, stretch=1)
        row.addWidget(self.new_btn)
        layout.addLayout(row)

        self.empty_hint = QLabel("nothing here yet")
        self.empty_hint.setObjectName("HistoryEmpty")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setWordWrap(True)
        layout.addWidget(self.empty_hint)

        self.list = QListWidget()
        self.list.setObjectName("HistoryList")
        self.list.setFrameShape(QListWidget.Shape.NoFrame)
        self.list.setWordWrap(True)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setSpacing(2)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # Click only — also wiring itemActivated double-fired the session
        # switch / "Finish or stop" toast on Windows (L3 / S10).
        self.list.itemClicked.connect(self._on_activated)
        self.list.customContextMenuRequested.connect(self._on_session_menu)
        # Fusion owns item chrome. Native Windows selection paints a second
        # plate through translucent QSS — the double highlight on a click.
        self._fusion_style = QStyleFactory.create("Fusion")
        if self._fusion_style is not None:
            self._fusion_style.setParent(self)
            self.list.setStyle(self._fusion_style)
        layout.addWidget(self.list, stretch=2)

        self.facts_label = QLabel("pending facts")
        self.facts_label.setObjectName("InstrumentHint")
        layout.addWidget(self.facts_label)

        self.facts_list = QListWidget()
        self.facts_list.setObjectName("FactsList")
        self.facts_list.setFrameShape(QListWidget.Shape.NoFrame)
        self.facts_list.setMinimumHeight(48)
        self.facts_list.setWordWrap(True)
        self.facts_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.facts_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.facts_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.facts_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self.facts_list, stretch=1)

        self.fact_actions = QWidget()
        fact_row = QHBoxLayout(self.fact_actions)
        fact_row.setContentsMargins(0, 0, 0, 0)
        fact_row.setSpacing(6)
        self.approve_btn = QPushButton("approve")
        self.approve_btn.setObjectName("FactApprove")
        self.reject_btn = QPushButton("reject")
        self.reject_btn.setObjectName("FactReject")
        self.reject_all_btn = QPushButton("reject all")
        self.reject_all_btn.setObjectName("FactRejectAll")
        for btn in (self.approve_btn, self.reject_btn, self.reject_all_btn):
            btn.setFixedHeight(28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.approve_btn.setToolTip(
            "Keep selected fact(s) as durable. Shift/Ctrl-click to select several."
        )
        self.reject_btn.setToolTip(
            "Discard selected proposed fact(s). Shift/Ctrl-click to select several."
        )
        self.reject_all_btn.setToolTip("Discard every pending fact in the queue")
        self.approve_btn.clicked.connect(lambda: self._decide_selected(self.facts_list, "active"))
        self.reject_btn.clicked.connect(lambda: self._decide_selected(self.facts_list, "rejected"))
        self.reject_all_btn.clicked.connect(self._reject_all_pending)
        fact_row.addWidget(self.approve_btn)
        fact_row.addWidget(self.reject_btn)
        fact_row.addWidget(self.reject_all_btn)
        fact_row.addStretch(1)
        layout.addWidget(self.fact_actions)

        # Empty queue stays collapsed so History is session-first (Pass A).
        self._set_pending_visible(False)

    def set_sessions(self, sessions: list[dict[str, str]]) -> None:
        self._sessions = list(sessions)
        self._apply_filter(self.search.text())

    def set_active(self, session_id: str) -> None:
        """Keep the seated session marked — bold plus the selected wash."""
        self._active_id = session_id
        current = None
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item is None:
                continue
            sid = str(item.data(Qt.ItemDataRole.UserRole) or "")
            is_active = bool(self._active_id) and sid == self._active_id
            font = item.font()
            font.setBold(is_active)
            item.setFont(font)
            if is_active:
                current = item
        if current is not None:
            if self.list.currentItem() is not current or not current.isSelected():
                self.list.setCurrentItem(current)
        else:
            self.list.clearSelection()
            self.list.setCurrentItem(None)

    def set_switch_enabled(self, enabled: bool) -> None:
        """Disable session switching while a turn is busy (L3)."""
        self.list.setEnabled(enabled)
        self.new_btn.setEnabled(enabled)
        tip = "" if enabled else "Finish or stop the current turn first"
        self.list.setToolTip(tip)
        self.new_btn.setToolTip(
            "Start a fresh conversation" if enabled else tip
        )

    def recent_sessions(self, limit: int = 3) -> list[tuple[str, str]]:
        """Most recent sessions for the Orbit idle ghosts."""
        out: list[tuple[str, str]] = []
        for session in self._sessions[: max(0, int(limit))]:
            sid = str(session.get("id") or "")
            if not sid:
                continue
            title = _display_session_title(str(session.get("title") or ""))
            out.append((sid, title))
        return out

    def set_pending_facts(self, facts: list[dict[str, object]]) -> None:
        self._fill_fact_list(self.facts_list, self.facts_label, "pending facts", facts)
        self._set_pending_visible(self.facts_list.count() > 0)

    def _set_pending_visible(self, visible: bool) -> None:
        self.facts_label.setVisible(visible)
        self.facts_list.setVisible(visible)
        self.fact_actions.setVisible(visible)

    def _fill_fact_list(
        self,
        widget: QListWidget,
        label: QLabel,
        title: str,
        facts: list[dict[str, object]],
    ) -> None:
        widget.clear()
        for fact in facts:
            text = str(fact.get("text") or "").strip()
            if not text:
                continue
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, int(fact["id"]))  # type: ignore[arg-type]
            item.setToolTip(text)
            widget.addItem(item)
        count = widget.count()
        label.setText(title if count == 0 else f"{title} ({count})")

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        rows: list[tuple[str, str, str]] = []
        for session in self._sessions:
            title = _display_session_title(str(session.get("title") or ""))
            started = _format_when(str(session.get("started_at") or ""))
            hay = f"{title} {started}".lower()
            if needle and needle not in hay:
                continue
            rows.append((str(session.get("id") or ""), title, started))
        fingerprint = tuple(rows)
        empty = not rows
        self.empty_hint.setVisible(empty)
        if empty:
            self.empty_hint.setText("nothing matches" if needle else "nothing here yet")
        if fingerprint == self._list_fp and self.list.count() == len(rows):
            self.set_active(self._active_id)
            return
        self._list_fp = fingerprint
        self.list.clear()
        for sid, title, started in rows:
            # Title first (what you scan); date second — no H-scroll dump.
            item = QListWidgetItem(f"{title}\n{started}")
            item.setData(Qt.ItemDataRole.UserRole, sid)
            item.setToolTip(f"{title}\n{started}")
            item.setSizeHint(QSize(0, 48))
            self.list.addItem(item)
        self.set_active(self._active_id)

    def _on_activated(self, item: QListWidgetItem) -> None:
        sid = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not sid:
            return
        already = sid == self._active_id
        self.set_active(sid)
        if already:
            return
        self.session_selected.emit(sid)

    def _on_session_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        sid = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not sid:
            return
        title = ""
        for session in self._sessions:
            if str(session.get("id") or "") == sid:
                title = _display_session_title(str(session.get("title") or ""))
                break
        menu = QMenu(self)
        open_act = QAction("Open", menu)
        delete_act = QAction("Delete…", menu)
        menu.addAction(open_act)
        menu.addAction(delete_act)
        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen is open_act:
            self.session_selected.emit(sid)
        elif chosen is delete_act:
            if confirm(
                self,
                "Delete conversation",
                f"Delete “{title}”?",
                detail="This cannot be undone.",
                confirm_text="Delete",
                destructive=True,
            ):
                self.session_delete_requested.emit(sid)

    def _decide_selected(self, widget: QListWidget, status: str) -> None:
        items = widget.selectedItems()
        if not items and widget.currentItem() is not None:
            items = [widget.currentItem()]
        ids: list[int] = []
        for item in items:
            if item is None:
                continue
            fact_id = item.data(Qt.ItemDataRole.UserRole)
            if fact_id is None:
                continue
            ids.append(int(fact_id))
        if ids:
            self.fact_decided.emit(ids, status)

    def _reject_all_pending(self) -> None:
        ids: list[int] = []
        for i in range(self.facts_list.count()):
            item = self.facts_list.item(i)
            if item is None:
                continue
            fact_id = item.data(Qt.ItemDataRole.UserRole)
            if fact_id is None:
                continue
            ids.append(int(fact_id))
        if ids:
            self.fact_decided.emit(ids, "rejected")


def _format_when(iso: str) -> str:
    if not iso:
        return "no date"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    today = datetime.now(dt.tzinfo).date() if dt.tzinfo is not None else datetime.now().date()
    delta = (today - dt.date()).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "yesterday"
    return dt.strftime("%d %b %Y").lstrip("0")
