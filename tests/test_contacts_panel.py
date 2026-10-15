"""Contacts window: list → card → Save → data/contacts.yaml."""

from __future__ import annotations

from arelis.contacts import load_all_contacts, load_contacts
from arelis.ui.panels.contacts import ContactsPanel


def test_contacts_panel_saves_only_on_save(qt_app, tmp_path) -> None:
    path = tmp_path / "contacts.yaml"
    panel = ContactsPanel(path=path)
    try:
        panel.open_new()
        panel.name_edit.setText("Alex Carter")
        panel.title_edit.setText("Coach")
        panel.phone_edit.setText("5551112222")
        assert load_all_contacts(path) == {}
        assert panel.save_card()
        book = load_contacts(path)
        assert book["coach"].name == "Alex Carter"
        assert book["coach"].title == "Coach"
        panel.show_list()
        assert panel.list.count() == 1
    finally:
        panel.deleteLater()


def _contacts_layers(panel: ContactsPanel) -> tuple:
    """Every container we own between the glass plate and the form."""
    from PySide6.QtWidgets import QScrollArea

    scroll = panel._card_page.findChild(QScrollArea)
    return (
        panel,
        panel.stack,
        panel._list_page,
        panel._card_page,
        panel.list,
        panel.list.viewport(),
        scroll,
        scroll.viewport(),
    )


def test_save_keeps_one_page_on_screen(qt_app, tmp_path) -> None:
    """Only one page is in the tree. Save must not bring the list back under it."""
    path = tmp_path / "contacts.yaml"
    panel = ContactsPanel(path=path)
    try:
        assert panel.stack.currentWidget() is panel._list_page
        panel.open_new()
        panel.name_edit.setText("Alex Carter")
        panel.title_edit.setText("Coach")
        assert panel.stack.currentWidget() is panel._card_page
        assert panel._list_page.isHidden()
        assert panel.save_card()
        assert panel.stack.currentWidget() is panel._card_page
        assert panel._list_page.isHidden()
        panel.title_edit.setText("Mentor")
        assert panel.save_card()
        assert panel.stack.currentWidget() is panel._card_page
        assert panel._list_page.isHidden()
        panel.show_list()
        assert panel.stack.currentWidget() is panel._list_page
        assert panel._card_page.isHidden()
        assert panel.list.count() == 1
    finally:
        panel.deleteLater()


def test_contacts_inbox_opens_on_the_list(qt_app, tmp_path) -> None:
    from PySide6.QtCore import Qt

    from arelis.ui.contacts_inbox import ContactsInboxWindow
    from arelis.ui.glass import GlassFrame

    path = tmp_path / "contacts.yaml"
    panel = ContactsPanel(path=path)
    inbox = ContactsInboxWindow(panel)
    try:
        panel.open_new()
        panel.name_edit.setText("Alex Carter")
        assert panel.stack.currentIndex() == 1
        inbox.show()
        qt_app.processEvents()
        assert panel.stack.currentIndex() == 0
        assert panel._list_page.isVisible()
        assert not inbox.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        assert not inbox.mask().isEmpty()
        plates = inbox.findChildren(GlassFrame)
        assert plates and plates[0]._round_cutout
    finally:
        inbox.hide()
        inbox.deleteLater()
        panel.deleteLater()


