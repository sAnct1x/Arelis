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


def test_contacts_panel_keeps_a_draft_off_sms(qt_app, tmp_path) -> None:
    path = tmp_path / "contacts.yaml"
    panel = ContactsPanel(path=path)
    try:
        panel.open_new()
        panel.title_edit.setText("Coach")
        assert panel.save_card()
        assert load_contacts(path) == {}
        assert "coach" in load_all_contacts(path)
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


def test_contacts_containers_never_claim_opaque_paint(qt_app, tmp_path) -> None:
    """The Save-ghost was WA_OpaquePaintEvent on containers that paint nothing.

    Qt skips the palette fill *and* the stylesheet background for a widget with
    that attribute, and stops repainting the plate underneath, so the previous
    frame stayed on screen: the list row behind the heading, a second Save
    button, a blurred hint. None of these layers may set it.

    autoFillBackground is deliberately not asserted here: QAbstractScrollArea
    turns it on for its own viewport, and a widget that fills its background is
    the safe direction — the ghost needed a widget that filled nothing while
    claiming it had.
    """
    from PySide6.QtCore import Qt

    path = tmp_path / "contacts.yaml"
    panel = ContactsPanel(path=path)
    try:
        panel.open_new()
        panel.name_edit.setText("Alex Carter")
        panel.title_edit.setText("Coach")
        assert panel.save_card()
        panel.show_list()
        panel.open_contact("coach")
        panel.title_edit.setText("Mentor")
        assert panel.save_card()
        for widget in _contacts_layers(panel):
            assert widget is not None
            assert not widget.testAttribute(
                Qt.WidgetAttribute.WA_OpaquePaintEvent
            ), f"{widget.objectName() or type(widget).__name__} claims opaque paint"
            assert not widget.testAttribute(
                Qt.WidgetAttribute.WA_TranslucentBackground
            ), f"{widget.objectName() or type(widget).__name__} is translucent"
    finally:
        panel.deleteLater()


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


def test_new_card_placeholders_are_not_people(qt_app, tmp_path) -> None:
    panel = ContactsPanel(path=tmp_path / "contacts.yaml")
    try:
        panel.open_new()
        for edit in (
            panel.name_edit,
            panel.title_edit,
            panel.handle_edit,
            panel.aliases_edit,
            panel.phone_edit,
            panel.email_edit,
        ):
            assert edit.text() == ""
            text = edit.placeholderText().lower()
            assert "carter" not in text
            assert "wife" not in text
            assert "@" not in text
    finally:
        panel.deleteLater()
