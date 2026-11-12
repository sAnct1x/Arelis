"""Active facts manager: see, edit, and forget durable memory."""

from __future__ import annotations

import re
from collections.abc import Callable

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

from arelis.ui.theme import SPACE, space_box

_ISO_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_FACT_TEXT_ROLE = Qt.ItemDataRole.UserRole + 1


def _date_only(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    match = _ISO_DATE.match(raw)
    return match.group(1) if match else raw


def _format_fact_dates(fact: dict[str, object]) -> str:
    created = _date_only(fact.get("created_at"))
    updated = _date_only(fact.get("updated_at"))
    if created and updated and created != updated:
        return f"created {created}, updated {updated}"
    stamp = created or updated
    return f"created {stamp}" if stamp else ""


def _format_fact_item(fact: dict[str, object]) -> str:
    text = str(fact.get("text") or "").strip()
    dates = _format_fact_dates(fact)
    if dates:
        return f"{text}\n{dates}"
    return text


class _FactList(QListWidget):
    """Enter edits the current fact and Delete forgets the selected ones."""

    edit_requested = Signal()
    forget_requested = Signal()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        key = event.key()
        picked = bool(self.selectedItems()) or self.currentItem() is not None
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and picked:
            self.edit_requested.emit()
            return
        if key == Qt.Key.Key_Delete and picked:
            self.forget_requested.emit()
            return
        super().keyPressEvent(event)


class ActiveFactsPanel(QWidget):
    """List durable facts, edit their wording, or forget ones that should stop.

    Forget deactivates selected rows (status=rejected). Edit rewrites the
    selected fact in place. This panel is for durable memory only.
    """

    fact_decided = Signal(object, str)
    fact_edited = Signal(int, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._facts: list[dict[str, object]] = []
        self._ask_text: Callable[..., str] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*space_box("inset", "plate", "inset", "inset"))
        layout.setSpacing(SPACE["gap"])

        hint = QLabel(
            "Facts Arelis keeps about you and your work, each with the dates "
            "they were first saved and last changed. Edit fixes the wording. "
            "Forget stops her using a fact."
        )
        hint.setObjectName("SettingsHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.search = QLineEdit()
        self.search.setObjectName("InstrumentSearch")
        self.search.setAccessibleName("Filter facts")
        self.search.setPlaceholderText("filter active facts…")
        self.search.setFixedHeight(28)
        self.search.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search)

        self.active_label = QLabel("active facts")
        self.active_label.setObjectName("InstrumentHint")
        layout.addWidget(self.active_label)

        self.active_list = _FactList()
        self.active_list.setObjectName("ActiveFactsList")
        self.active_list.setAccessibleName("Active facts")
        self.active_list.edit_requested.connect(self._edit_selected)
        self.active_list.forget_requested.connect(self._forget_selected)
        self.active_list.setFrameShape(QListWidget.Shape.NoFrame)
        self.active_list.setMinimumHeight(120)
        self.active_list.setWordWrap(True)
        self.active_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.active_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.active_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.active_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.active_list.itemSelectionChanged.connect(self._sync_buttons)
        layout.addWidget(self.active_list, stretch=1)

        self.empty_label = QLabel("No active facts.")
        self.empty_label.setObjectName("SettingsHint")
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.edit_btn = QPushButton("edit")
        self.edit_btn.setObjectName("FactEdit")
        self.edit_btn.setAccessibleName("Edit fact")
        self.edit_btn.setFixedHeight(28)
        self.edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit_btn.setToolTip("Change the wording of the selected fact (Enter).")
        self.edit_btn.clicked.connect(self._edit_selected)
        row.addWidget(self.edit_btn)
        self.forget_btn = QPushButton("forget")
        self.forget_btn.setObjectName("FactForget")
        self.forget_btn.setAccessibleName("Forget fact")
        self.forget_btn.setFixedHeight(28)
        self.forget_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.forget_btn.setToolTip(
            "Stop injecting selected fact(s) (Delete). Shift/Ctrl-click to select several."
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
            item = QListWidgetItem(_format_fact_item(fact))
            item.setData(Qt.ItemDataRole.UserRole, int(fact["id"]))  # type: ignore[arg-type]
            item.setData(_FACT_TEXT_ROLE, fact_text)
            # UIA names the row by the fact alone, not the dates line under it.
            item.setData(Qt.ItemDataRole.AccessibleTextRole, fact_text)
            dates = _format_fact_dates(fact)
            item.setToolTip(f"{fact_text}\n{dates}" if dates else fact_text)
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
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        has_rows = self.active_list.count() > 0
        self.edit_btn.setEnabled(has_rows)
        self.forget_btn.setEnabled(has_rows)

    def _selected_items(self) -> list[QListWidgetItem]:
        items = self.active_list.selectedItems()
        if not items and self.active_list.currentItem() is not None:
            items = [self.active_list.currentItem()]
        return [item for item in items if item is not None]

    def _prompt_edit(self, current: str) -> str:
        ask = self._ask_text
        if ask is None:
            from arelis.ui.dialog import ask_text

            ask = ask_text
        return ask(
            self,
            "Edit fact",
            "Change what Arelis remembers. Leave it blank to cancel.",
            initial=current,
            accept_text="Save",
            field_name="Fact text",
        )

    def _edit_selected(self) -> None:
        items = self._selected_items()
        if not items:
            return
        item = items[0]
        fact_id = item.data(Qt.ItemDataRole.UserRole)
        if fact_id is None:
            return
        current = str(item.data(_FACT_TEXT_ROLE) or "").strip()
        updated = self._prompt_edit(current)
        if not updated or updated == current:
            return
        self.fact_edited.emit(int(fact_id), updated)

    def _forget_selected(self) -> None:
        ids: list[int] = []
        for item in self._selected_items():
            fact_id = item.data(Qt.ItemDataRole.UserRole)
            if fact_id is None:
                continue
            ids.append(int(fact_id))
        if ids:
            self.fact_decided.emit(ids, "rejected")
