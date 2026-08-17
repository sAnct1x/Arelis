"""Active facts manager — durable memory audit + forget."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ActiveFactsPanel(QWidget):
    """List approved facts and forget ones that should stop being injected.

    Forget deactivates selected rows (status=rejected). Pending approve/reject
    stays on History; this panel is for durable memory only.
    """

    fact_decided = Signal(object, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._facts: list[dict[str, object]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 16, 14, 12)
        layout.setSpacing(8)

        hint = QLabel(
            "Approved facts Arelis injects as durable knowledge. "
            "Forget stops using a fact. New facts appear after you approve them "
            "under History → pending facts."
        )
        hint.setObjectName("SettingsHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.search = QLineEdit()
        self.search.setObjectName("InstrumentSearch")
        self.search.setPlaceholderText("filter active facts…")
        self.search.setFixedHeight(28)
        self.search.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search)

        self.active_label = QLabel("active facts")
        self.active_label.setObjectName("InstrumentHint")
        layout.addWidget(self.active_label)

        self.active_list = QListWidget()
        self.active_list.setObjectName("ActiveFactsList")
        self.active_list.setFrameShape(QListWidget.Shape.NoFrame)
        self.active_list.setMinimumHeight(120)
        self.active_list.setWordWrap(True)
        self.active_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.active_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.active_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.active_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self.active_list, stretch=1)

        self.empty_label = QLabel("No active facts.")
        self.empty_label.setObjectName("SettingsHint")
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.forget_btn = QPushButton("forget")
        self.forget_btn.setObjectName("FactForget")
        self.forget_btn.setFixedHeight(28)
        self.forget_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.forget_btn.setToolTip(
            "Stop injecting selected fact(s). Shift/Ctrl-click to select several."
        )
        self.forget_btn.clicked.connect(self._forget_selected)
        row.addWidget(self.forget_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self.set_facts([])

    def set_facts(self, facts: list[dict[str, object]]) -> None:
        self._facts = list(facts)
        self._apply_filter(self.search.text())

    def _apply_filter(self, text: str = "") -> None:
        needle = text.strip().lower()
        self.active_list.clear()
        for fact in self._facts:
            fact_text = str(fact.get("text") or "").strip()
            if not fact_text:
                continue
            if needle and needle not in fact_text.lower():
                continue
            item = QListWidgetItem(fact_text)
            item.setData(Qt.ItemDataRole.UserRole, int(fact["id"]))  # type: ignore[arg-type]
            item.setToolTip(fact_text)
            self.active_list.addItem(item)
        count = self.active_list.count()
        total = sum(1 for f in self._facts if str(f.get("text") or "").strip())
        if total == 0:
            self.active_label.setText("active facts")
        else:
            self.active_label.setText(f"active facts ({total})")
        has_rows = count > 0
        self.active_list.setVisible(has_rows)
        self.empty_label.setVisible(not has_rows and not needle)
        if needle and not has_rows and total > 0:
            self.empty_label.setText("No facts match this filter.")
            self.empty_label.setVisible(True)
        elif not has_rows:
            self.empty_label.setText("No active facts.")
        self.forget_btn.setEnabled(has_rows)

    def _forget_selected(self) -> None:
        items = self.active_list.selectedItems()
        if not items and self.active_list.currentItem() is not None:
            items = [self.active_list.currentItem()]
        ids: list[int] = []
        for item in items:
            if item is None:
                continue
            fact_id = item.data(Qt.ItemDataRole.UserRole)
            if fact_id is None:
                continue
            ids.append(int(fact_id))
        if ids:
            self.fact_decided.emit(ids, "rejected")
