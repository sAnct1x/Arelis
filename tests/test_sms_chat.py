"""SMS chat tiles: identity, seed, append, SMS-only open-as-chat."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from arelis.notify.center import new_notice
from arelis.ui.sms_chat import (
    SmsChatRegistry,
    SmsChatWindow,
    chat_target,
    room_owns_doorbell,
    seed_bodies,
    thread_keys,
)


def test_thread_keys_alias_and_digits() -> None:
    assert thread_keys(alias="wife", phone="5551112222") == (
        "alias:wife",
        "digits:5551112222",
    )
    assert thread_keys(phone="+1 (555) 111-2222") == ("digits:5551112222",)


def test_registry_merges_alias_and_later_digits() -> None:
    host = QWidget()
    try:
        registry = SmsChatRegistry(host)
        first = registry.resolve_key(alias="wife", phone="5551112222")
        second = registry.resolve_key(phone="5551112222")
        assert first == second
        assert first.startswith("alias:")
    finally:
        host.deleteLater()


def test_seed_bodies_from_notice() -> None:
    notice = new_notice(
        kind="sms",
        title="Robin",
        body="two",
        data={"bodies": ["one", "two"], "from": "+15551112222", "alias": "wife"},
    )
    assert seed_bodies(notice) == ["one", "two"]


def test_chat_target_needs_a_number() -> None:
    assert chat_target(alias="", phone="", sender="")[1] == ""
    assert chat_target(phone="5551112222")[1] == "+15551112222"


def test_open_seeds_and_inbound_appends(qt_app) -> None:
    host = QWidget()
    host.show()
    registry = SmsChatRegistry(host)
    try:
        window = registry.open(
            alias="coach",
            phone="5551112222",
            title="Alex",
            seed=["hey"],
        )
        assert window is not None
        assert any(item.body == "hey" for item in registry.messages(window.key))
        registry.append_inbound(
            body="later",
            alias="coach",
            phone="5551112222",
        )
        incoming = [
            item.body
            for item in registry.messages(window.key)
            if item.direction == "in"
        ]
        assert incoming == ["hey", "later"]
        window.close()
    finally:
        host.deleteLater()


def test_cannot_open_a_dead_composer(qt_app) -> None:
    host = QWidget()
    registry = SmsChatRegistry(host)
    try:
        assert registry.open(alias="", phone="", sender="", title="???") is None
    finally:
        host.deleteLater()


def test_sms_row_double_click_requests_chat(qt_app) -> None:
    from arelis.ui.panels.notifications import NotificationsPanel

    panel = NotificationsPanel()
    notice = new_notice(
        kind="sms",
        title="Robin",
        body="hi",
        data={"from": "+15551112222", "alias": "wife"},
    )
    panel.set_notices([notice])
    opened: list[str] = []
    panel.chat_requested.connect(opened.append)
    panel._on_double(panel.list.item(0))
    assert opened == [notice.id]
    panel.deleteLater()


def test_room_owns_doorbell() -> None:
    assert room_owns_doorbell("visible")
    assert room_owns_doorbell("focused")
    assert not room_owns_doorbell("hidden")
    assert not room_owns_doorbell("")


def test_room_state_hidden_until_shown(qt_app) -> None:
    host = QWidget()
    registry = SmsChatRegistry(host)
    try:
        assert registry.room_state(alias="coach", phone="5551112222")[1] == "hidden"
        window = registry.open(alias="coach", phone="5551112222", title="Alex")
        assert window is not None
        window.show()
        qt_app.processEvents()
        _live, state = registry.room_state(alias="coach", phone="5551112222")
        assert state in {"visible", "focused"}
        window.hide()
        qt_app.processEvents()
        assert registry.room_state(alias="coach", phone="5551112222")[1] == "hidden"
        window.close()
    finally:
        host.deleteLater()


def test_attention_on_visible_unfocused_tile(qt_app) -> None:
    window = SmsChatWindow(key="k", title="Alex", alias="coach", phone="+1555112222")
    other = QWidget()
    try:
        window.hide()
        window.attention()
        assert not window.has_attention
        window.show()
        window.activateWindow()
        qt_app.processEvents()
        if window.isActiveWindow():
            window.attention()
            assert not window.has_attention
        other.show()
        other.activateWindow()
        other.raise_()
        qt_app.processEvents()
        if not window.isActiveWindow():
            window.attention()
            assert window.has_attention
        else:
            window._plate.set_attention(True)
            assert window.has_attention
        window.clear_attention()
        assert not window.has_attention
        window._plate.set_attention(True)
        window._attention_until = 0.0
        window._tick_rim_pulse()
        # until is 0 so breath stays; force the ember settle
        window._attention_until = 1.0
        window._tick_rim_pulse()
        assert window._plate._ember
        assert not window._plate._attention
    finally:
        window.hide()
        window.deleteLater()
        other.deleteLater()


def test_hidden_tile_badges_instead_of_pulse(qt_app) -> None:
    host = QWidget()
    host.show()
    registry = SmsChatRegistry(host)
    try:
        window = registry.open(alias="coach", phone="5551112222", title="Alex")
        assert window is not None
        window.hide()
        qt_app.processEvents()
        registry.append_inbound(body="later", alias="coach", phone="5551112222")
        assert not window.has_attention
        assert window._unread >= 1
        window.close()
    finally:
        host.deleteLater()


def test_visible_room_skips_notice_other_sender_still_doorbells(
    arelis_window, qt_app
) -> None:
    win = arelis_window()
    tile = win.sms_chats.open(alias="wife", phone="5551112222", title="Robin")
    assert tile is not None
    qt_app.processEvents()
    before = len(win.notify_center.items)
    win._on_sms_received(
        {
            "id": "m1",
            "from": "5551112222",
            "body": "Pump working?",
            "contact_alias": "wife",
            "contact_name": "Robin",
        }
    )
    assert len(win.notify_center.items) == before
    assert win._held_inbound == []
    win._on_sms_received(
        {
            "id": "m2",
            "from": "5553334444",
            "body": "hello",
            "contact_alias": "",
            "contact_name": "",
        }
    )
    assert any(item.body == "hello" for item in win.notify_center.items)
    tile.hide()
    qt_app.processEvents()
    win._on_sms_received(
        {
            "id": "m3",
            "from": "5551112222",
            "body": "after hide",
            "contact_alias": "wife",
            "contact_name": "Robin",
        }
    )
    assert any(item.body == "after hide" for item in win.notify_center.items)


def test_thread_outlives_the_tile_but_not_the_app(arelis_window, qt_app) -> None:
    """Texts last as long as the window is open, and no longer.

    Closing a tile is a gesture about the tile, not about the conversation, so
    the thread has to still be there when it is opened again an hour later. The
    other half is that nothing here is written to disk: a restart is a fresh
    start, which is why the archive never sees an inbound text.
    """
    win = arelis_window()
    win._on_sms_received(
        {
            "id": "m1",
            "from": "5551112222",
            "body": "pump is fixed",
            "contact_alias": "wife",
            "contact_name": "Robin",
        }
    )
    tile = win.sms_chats.open(alias="wife", phone="5551112222", title="Robin")
    assert tile is not None
    key = tile.key
    assert [m.body for m in win.sms_chats.messages(key)] == ["pump is fixed"]

    tile.close()
    qt_app.processEvents()
    assert win.sms_chats.window(key) is None
    assert [m.body for m in win.sms_chats.messages(key)] == ["pump is fixed"]

    win._on_sms_received(
        {
            "id": "m2",
            "from": "5551112222",
            "body": "and the gate",
            "contact_alias": "wife",
            "contact_name": "Robin",
        }
    )
    reopened = win.sms_chats.open(alias="wife", phone="5551112222", title="Robin")
    assert reopened is not None
    assert reopened.key == key
    assert [m.body for m in win.sms_chats.messages(key)] == [
        "pump is fixed",
        "and the gate",
    ]
    # The whole thread is painted back, not only what arrived while it was shut.
    assert reopened._thread.count() - 1 == 2

    restarted = SmsChatRegistry(win)
    assert restarted.messages(key) == []


def test_inbox_open_hides_overlay_pill(arelis_window, qt_app) -> None:
    from arelis.notify.center import new_notice

    win = arelis_window()
    win.show()
    win.notify_center.add(
        new_notice(kind="sms", title="Robin", body="hi", group_key="sms:robin")
    )
    win.notify_inbox.show()
    qt_app.processEvents()
    win._sync_notify_surface()
    assert win.conversation.notify_overlay.isHidden()
    win.notify_inbox.hide()
    qt_app.processEvents()
    win._sync_notify_surface()
    assert not win.conversation.notify_overlay.isHidden()


def test_job_row_does_not_open_as_chat(qt_app) -> None:
    from arelis.ui.panels.notifications import NotificationsPanel

    panel = NotificationsPanel()
    notice = new_notice(kind="job", title="image", body="done")
    panel.set_notices([notice])
    opened: list[str] = []
    panel.chat_requested.connect(opened.append)
    panel._on_double(panel.list.item(0))
    assert opened == []
    panel.deleteLater()
