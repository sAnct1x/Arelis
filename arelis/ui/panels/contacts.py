"""Address book for the floating contacts window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from arelis.contacts import (
    CONTACTS_PATH,
    Contact,
    load_all_contacts,
    remove_contact,
    upsert_contact_record,
)
from arelis.ui.dialog import confirm, notice


class ContactsPanel(QWidget):
    """List of people, then a card. Nothing is written until Save.

    Every widget here is a plain child of the glass plate: no
    ``WA_OpaquePaintEvent``, no ``WA_TranslucentBackground``, no runtime
    attribute flips. ``WA_OpaquePaintEvent`` on a container is what produced
    the Save-ghost — Qt skips both the palette fill and the stylesheet
    background for such a widget, so a plain ``QWidget`` painted nothing while
    still telling Qt not to repaint the plate underneath. The old frame stayed
    in the backing store and survived even a window drag. Colour comes from
    the stylesheet alone (``theme.py``, ``#Contacts*``).
    """

    def __init__(self, parent=None, *, path: Path | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ContactsPanel")
        self._path = path or CONTACTS_PATH
        self._book: dict[str, Contact] = {}
        self._editing_alias = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.stack = QStackedWidget()
        self.stack.setObjectName("ContactsStack")
        root.addWidget(self.stack)

        self._list_page = QWidget()
        self._list_page.setObjectName("ContactsListPage")
        list_layout = QVBoxLayout(self._list_page)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.search = QLineEdit()
        self.search.setObjectName("InstrumentSearch")
        self.search.setPlaceholderText("search…")
        self.search.setFixedHeight(28)
        self.search.textChanged.connect(self._apply_filter)
        self.add_btn = QPushButton("+")
        self.add_btn.setObjectName("InstrumentAction")
        self.add_btn.setFixedSize(28, 28)
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setToolTip("Add a contact")
        self.add_btn.clicked.connect(self.open_new)
        row.addWidget(self.search, stretch=1)
        row.addWidget(self.add_btn)
        list_layout.addLayout(row)

        self.list = QListWidget()
        self.list.setObjectName("ContactsList")
        self.list.setFrameShape(QListWidget.Shape.NoFrame)
        self.list.setWordWrap(True)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setSpacing(2)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.itemClicked.connect(self._on_item_clicked)
        self.list.customContextMenuRequested.connect(self._on_list_menu)
        list_layout.addWidget(self.list, stretch=1)

        self.empty_hint = QLabel("No contacts yet. Tap + to add someone.")
        self.empty_hint.setObjectName("InstrumentHint")
        self.empty_hint.setWordWrap(True)
        list_layout.addWidget(self.empty_hint)

        self.stack.addWidget(self._list_page)
        self._card_page = self._build_card_page()
        self.stack.addWidget(self._card_page)
        self.reload()
        self._show_stack(0)

    def _build_card_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("ContactsCardPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        nav = QHBoxLayout()
        nav.setSpacing(6)
        self.back_btn = QPushButton("← list")
        self.back_btn.setObjectName("InstrumentAction")
        self.back_btn.setFixedHeight(28)
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_btn.setToolTip("Back without saving")
        self.back_btn.clicked.connect(self.show_list)
        self.delete_btn = QPushButton("remove")
        self.delete_btn.setObjectName("InstrumentAction")
        self.delete_btn.setFixedHeight(28)
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_btn.clicked.connect(self._confirm_remove)
        nav.addWidget(self.back_btn)
        nav.addStretch(1)
        nav.addWidget(self.delete_btn)
        layout.addLayout(nav)

        self.card_heading = QLabel("New contact")
        self.card_heading.setObjectName("InstrumentTitle")
        layout.addWidget(self.card_heading)

        scroll = QScrollArea()
        scroll.setObjectName("ContactsCardScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setObjectName("ContactsCardViewport")
        form_host = QWidget()
        form_host.setObjectName("ContactsFormHost")
        form = QFormLayout(form_host)
        form.setContentsMargins(0, 0, 4, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.name_edit = self._field("name")
        self.title_edit = self._field("relationship or role")
        self.handle_edit = self._field("short name you say")
        self.aliases_edit = self._field("other names, comma-separated")
        self.phone_edit = self._field("mobile")
        self.work_edit = self._field("work")
        self.email_edit = self._field("email")
        self.notes_edit = self._field("notes")

        form.addRow(_form_label("Name"), self.name_edit)
        form.addRow(_form_label("Title"), self.title_edit)
        form.addRow(_form_label("Handle"), self.handle_edit)
        form.addRow(_form_label("Also"), self.aliases_edit)
        form.addRow(_form_label("Mobile"), self.phone_edit)
        form.addRow(_form_label("Work"), self.work_edit)
        form.addRow(_form_label("Email"), self.email_edit)
        form.addRow(_form_label("Notes"), self.notes_edit)
        scroll.setWidget(form_host)
        layout.addWidget(scroll, stretch=1)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.save_btn = QPushButton("save")
        self.save_btn.setObjectName("InstrumentAction")
        self.save_btn.setFixedHeight(28)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.clicked.connect(self.save_card)
        actions.addWidget(self.save_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.card_hint = QLabel(
            "Handle is the short name you say out loud. Nothing is kept until Save."
        )
        self.card_hint.setObjectName("InstrumentHint")
        self.card_hint.setWordWrap(True)
        layout.addWidget(self.card_hint)
        return page

    def _field(self, placeholder: str) -> QLineEdit:
        edit = QLineEdit()
        edit.setObjectName("InstrumentSearch")
        edit.setPlaceholderText(placeholder)
        edit.setFixedHeight(28)
        return edit

    def reload(self) -> None:
        self._book = load_all_contacts(self._path)
        if self.stack.currentIndex() == 0:
            self._apply_filter(self.search.text())

    def _show_stack(self, index: int) -> None:
        """One page is visible, the other is hidden. Hidden widgets do not paint."""
        self.stack.setCurrentIndex(index)

    def show_list(self) -> None:
        self._editing_alias = ""
        self._show_stack(0)
        self.reload()

    def open_new(self) -> None:
        self._load_card(None)

    def open_contact(self, alias: str) -> None:
        contact = self._book.get(alias) or load_all_contacts(self._path).get(alias)
        if contact is None:
            return
        self._load_card(contact)

    def _load_card(self, contact: Contact | None) -> None:
        if contact is None:
            self._editing_alias = ""
            self.card_heading.setText("New contact")
            self.name_edit.clear()
            self.title_edit.clear()
            self.handle_edit.clear()
            self.aliases_edit.clear()
            self.phone_edit.clear()
            self.work_edit.clear()
            self.email_edit.clear()
            self.notes_edit.clear()
            self.delete_btn.setEnabled(False)
        else:
            self._editing_alias = contact.alias
            self.card_heading.setText(contact.display_name)
            self.name_edit.setText(contact.name)
            self.title_edit.setText(contact.title)
            self.handle_edit.setText(contact.alias)
            self.aliases_edit.setText(", ".join(contact.aliases))
            self.phone_edit.setText(contact.phone)
            self.work_edit.setText(contact.work_phone)
            self.email_edit.setText(contact.email)
            self.notes_edit.setText(contact.notes)
            self.delete_btn.setEnabled(True)
        self._refresh_card_hint()
        self._show_stack(1)
        self.name_edit.setFocus()

    def _card_has_content(self) -> bool:
        return any(
            edit.text().strip()
            for edit in (
                self.name_edit,
                self.title_edit,
                self.handle_edit,
                self.aliases_edit,
                self.phone_edit,
                self.work_edit,
                self.email_edit,
                self.notes_edit,
            )
        )

    def _refresh_card_hint(self) -> None:
        if self.phone_edit.text().strip():
            self.card_hint.setText(
                "Handle is the short name you say out loud. Click Save to keep this card."
            )
            return
        self.card_hint.setText(
            "Click Save to keep this card. Add a mobile number when you want "
            "Arelis to text them."
        )

    def save_card(self) -> bool:
        if not self._card_has_content():
            self.card_hint.setText("Fill in a name, title, or handle before saving.")
            return False
        result = upsert_contact_record(
            alias=self.handle_edit.text(),
            name=self.name_edit.text(),
            title=self.title_edit.text(),
            phone=self.phone_edit.text(),
            work_phone=self.work_edit.text(),
            email=self.email_edit.text(),
            aliases=self.aliases_edit.text(),
            notes=self.notes_edit.text(),
            previous_alias=self._editing_alias,
            path=self._path,
        )
        if isinstance(result, str):
            self.card_hint.setText(result)
            return False
        self._editing_alias = result.alias
        self._book[result.alias] = result
        self.delete_btn.setEnabled(True)
        if not self.handle_edit.text().strip():
            self.handle_edit.setText(result.alias)
        self.card_heading.setText(result.display_name)
        self.card_hint.setText("Saved.")
        # Stay on the card; the list is rebuilt on the way back in show_list().
        return True

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        self.list.clear()
        rows = sorted(
            self._book.values(),
            key=lambda c: (c.display_name.lower(), c.alias),
        )
        shown = 0
        for contact in rows:
            subtitle = contact.title or contact.alias
            hay = " ".join(
                [
                    contact.display_name,
                    contact.alias,
                    contact.title,
                    contact.email,
                    " ".join(contact.aliases),
                ]
            ).lower()
            if needle and needle not in hay:
                continue
            line = contact.display_name
            if subtitle and subtitle.lower() != contact.display_name.lower():
                line = f"{contact.display_name}\n{subtitle}"
            item = QListWidgetItem(line)
            item.setData(Qt.ItemDataRole.UserRole, contact.alias)
            item.setToolTip(line)
            item.setSizeHint(QSize(0, 48 if "\n" in line else 36))
            self.list.addItem(item)
            shown += 1
        self.empty_hint.setVisible(shown == 0)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        alias = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if alias:
            self.open_contact(alias)

    def _on_list_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        alias = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not alias:
            return
        contact = self._book.get(alias)
        label = contact.display_name if contact else alias
        menu = QMenu(self)
        open_act = QAction("Open", menu)
        remove_act = QAction("Remove…", menu)
        menu.addAction(open_act)
        menu.addAction(remove_act)
        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen is open_act:
            self.open_contact(alias)
        elif chosen is remove_act:
            self._remove_alias(alias, label)

    def _confirm_remove(self) -> None:
        alias = self._editing_alias
        if not alias:
            return
        contact = self._book.get(alias)
        label = contact.display_name if contact else alias
        self._remove_alias(alias, label)

    def _remove_alias(self, alias: str, label: str) -> None:
        if not confirm(
            self,
            "Remove contact",
            f"Remove {label} from contacts?",
            detail="This cannot be undone.",
            confirm_text="Remove",
            destructive=True,
        ):
            return
        result = remove_contact(alias, path=self._path)
        if isinstance(result, str):
            notice(self, "Contacts", result)
            return
        self._editing_alias = ""
        self._show_stack(0)
        self.reload()


def _form_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("InstrumentHint")
    return label
