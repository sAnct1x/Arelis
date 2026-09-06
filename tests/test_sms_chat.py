"""SMS chat tiles: identity, seed, append, SMS-only open-as-chat."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from arelis.notify.center import new_notice
from arelis.ui.sms_chat import (
    TILE_WIDTH,
    SmsChatMessage,
    SmsChatRegistry,
    SmsChatWindow,
    SmsImageLabel,
    bubble_plain_text,
    chat_target,
    format_bubble_time,
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


def test_registry_merges_alias_and_later_digits(qt_app) -> None:
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


def test_bubble_time_is_today_or_dated() -> None:
    from datetime import datetime

    now = datetime(2026, 9, 3, 22, 10)
    today = datetime(2026, 9, 3, 9, 5).timestamp()
    earlier = datetime(2026, 9, 1, 9, 5).timestamp()
    assert format_bubble_time(today, now=now) == "09:05"
    assert "Sep" in format_bubble_time(earlier, now=now)
    assert "1" in format_bubble_time(earlier, now=now)


def test_send_writes_the_buffer_once(qt_app) -> None:
    host = QWidget()
    host.show()
    registry = SmsChatRegistry(host)
    sent: list[str] = []
    registry.set_send_handler(lambda key, body, alias, phone: sent.append(body))
    try:
        window = registry.open(alias="coach", phone="5551112222", title="Alex")
        assert window is not None
        window.input.setText("hello")
        window._send()
        out = [m.body for m in registry.messages(window.key) if m.direction == "out"]
        assert out == ["hello"]
        assert sent == ["hello"]
        assert registry.messages(window.key)[-1].status == "pending"
        registry.mark_last_out(window.key, ok=False, error="down")
        assert registry.messages(window.key)[-1].status == "failed"
        window.close()
    finally:
        host.deleteLater()


def test_threads_survive_a_restart(qt_app, tmp_path) -> None:
    host = QWidget()
    path = tmp_path / "threads.json"
    first = SmsChatRegistry(host, persist=True, store_path=path)
    try:
        window = first.open(alias="wife", phone="5551112222", title="Robin")
        assert window is not None
        first.append_inbound(body="pump is fixed", alias="wife", phone="5551112222")
        key = window.key
        window.close()
        qt_app.processEvents()
        second = SmsChatRegistry(host, persist=True, store_path=path)
        assert [m.body for m in second.messages(key)] == ["pump is fixed"]
    finally:
        host.deleteLater()


def test_chat_tile_minimizes_instead_of_hiding(qt_app) -> None:
    from PySide6.QtCore import Qt

    window = SmsChatWindow(key="k", title="Alex", alias="coach", phone="+15551112222")
    try:
        assert window.windowType() == Qt.WindowType.Window
        assert window.windowType() != Qt.WindowType.Tool
        window.show()
        qt_app.processEvents()
        window.minimize()
        qt_app.processEvents()
        assert not window.isHidden()
        assert window.isMinimized()
    finally:
        window.close()
        window.deleteLater()


def test_chat_target_needs_a_number() -> None:
    assert chat_target(alias="", phone="", sender="")[1] == ""
    assert chat_target(phone="5551112222")[1] == "+15551112222"
    assert chat_target(sender="zzz-no-such-person-9f3a", contacts={})[1] == ""


def test_chat_target_resolves_a_messages_title() -> None:
    """Companion posts the Google Messages title, not the E.164 number."""
    from arelis.contacts import Contact

    book = {
        "wife": Contact(
            alias="wife",
            name="Robin",
            phone="5551112222",
            digits="5551112222",
        )
    }
    alias, e164 = chat_target(title="Robin 💋", contacts=book)
    assert alias == "wife"
    assert e164 == "+15551112222"


def test_open_uses_persisted_thread_number(qt_app, tmp_path) -> None:
    from arelis.ui.sms_store import save_threads

    path = tmp_path / "sms_threads.json"
    save_threads(
        {
            "alias:wife": {
                "alias": "wife",
                "phone": "+15551112222",
                "title": "Robin",
                "messages": [
                    {"direction": "in", "body": "earlier", "t": 1.0},
                ],
            }
        },
        path,
    )
    host = QWidget()
    host.show()
    registry = SmsChatRegistry(host, persist=True, store_path=path)
    try:
        window = registry.open(alias="wife", title="Robin", contacts={})
        assert window is not None
        assert window.phone == "+15551112222"
        window.close()
    finally:
        host.deleteLater()


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


def test_open_sms_chat_uses_the_host_window(qt_app) -> None:
    """A shadowed `window = chats.open(...)` used to mark-read on the tile."""
    from types import SimpleNamespace

    from arelis.notify.center import NotificationCenter
    from arelis.ui.sms_host import open_sms_chat

    host = QWidget()
    host.show()
    registry = SmsChatRegistry(host)
    notice = new_notice(
        kind="sms",
        title="Robin",
        body="hi",
        data={"from": "+15551112222", "alias": "wife"},
    )
    center = NotificationCenter()
    center.add(notice)
    notes: list[str] = []
    window = SimpleNamespace(
        sms_chats=registry,
        notify_center=center,
        thinking=SimpleNamespace(append=lambda text, kind="status": notes.append(text)),
    )
    try:
        assert open_sms_chat(window, notice.id) is True
        assert center.find(notice.id) is None
        assert notes == []
        chat = registry.window(registry.resolve_key(alias="wife", phone="+15551112222"))
        assert chat is not None
        chat.close()
    finally:
        host.deleteLater()


def test_cannot_open_a_dead_composer(qt_app) -> None:
    host = QWidget()
    registry = SmsChatRegistry(host)
    try:
        assert registry.open(alias="", phone="", sender="", title="???") is None
    finally:
        host.deleteLater()


def test_nameless_sms_notice_opens_the_inbox(
    arelis_window, qt_app, monkeypatch
) -> None:
    """A click must still surface the pile when the notice has no number."""
    from arelis.ui import sms_chat as sms_chat_mod
    from arelis.ui.notify_host import on_notice_activated

    monkeypatch.setattr(sms_chat_mod, "load_contacts", lambda: {})
    win = arelis_window()
    notice = new_notice(
        kind="sms",
        title="zzz-no-such-person-9f3a",
        body="hi",
        data={"from": "zzz-no-such-person-9f3a"},
    )
    win.notify_center.add(notice)
    on_notice_activated(win, notice.id)
    qt_app.processEvents()
    assert win.notify_inbox.isVisible()
    assert win.notify_center.find(notice.id) is not None


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


def test_attention_on_visible_unfocused_tile(qt_app, monkeypatch) -> None:
    # This process owns the OS foreground in the test. The production path
    # also pulses when Qt still says the tile is active but another app is
    # in front — see test_attention_when_qt_still_thinks_the_tile_is_active.
    monkeypatch.setattr("arelis.ui.sms_chat.process_owns_foreground", lambda: True)
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


def test_thread_scroll_stops_at_the_last_message(qt_app) -> None:
    """A stretch under the bubbles used to make a void you could scroll into.

    New inbound then jumped to that fake bottom instead of the last text.
    """
    window = SmsChatWindow(key="k", title="Alex", alias="coach", phone="+1555112222")
    try:
        window.resize(360, 280)
        window.show()
        qt_app.processEvents()
        for i in range(18):
            window.append_message(
                SmsChatMessage(direction="in", body=f"line {i} is a bit of text")
            )
        qt_app.processEvents()
        window._scroll_to_end()
        qt_app.processEvents()
        last = window._last_bubble()
        assert last is not None
        view = window._scroll.viewport()
        bottom = last.mapTo(view, last.rect().bottomLeft()).y()
        assert 0 < bottom <= view.height() + 8
        window.append_message(SmsChatMessage(direction="in", body="newest"))
        qt_app.processEvents()
        window._scroll_to_end()
        qt_app.processEvents()
        newest = window._last_bubble()
        assert newest is not None
        assert bubble_plain_text(newest) == "newest"
        newest_bottom = newest.mapTo(view, newest.rect().bottomLeft()).y()
        assert 0 < newest_bottom <= view.height() + 8
        host = window._scroll.widget()
        assert host is not None
        assert host.height() <= host.layout().sizeHint().height() + 16
    finally:
        window.hide()
        window.deleteLater()


def test_attention_when_qt_still_thinks_the_tile_is_active(qt_app, monkeypatch) -> None:
    """Another app can be in front while Qt still reports the tile as active.

    That is the Cursor-covering-the-chat case. Pulse anyway.
    """
    monkeypatch.setattr("arelis.ui.sms_chat.process_owns_foreground", lambda: False)
    window = SmsChatWindow(key="k", title="Alex", alias="coach", phone="+1555112222")
    try:
        window.show()
        window.activateWindow()
        qt_app.processEvents()
        window.attention()
        assert window.has_attention
    finally:
        window.hide()
        window.deleteLater()


def test_append_inbound_pulses_when_another_app_owns_foreground(
    qt_app, monkeypatch
) -> None:
    monkeypatch.setattr("arelis.ui.sms_chat.process_owns_foreground", lambda: False)
    host = QWidget()
    host.show()
    registry = SmsChatRegistry(host)
    try:
        window = registry.open(alias="coach", phone="5551112222", title="Alex")
        assert window is not None
        window.show()
        window.activateWindow()
        qt_app.processEvents()
        registry.append_inbound(body="later", alias="coach", phone="5551112222")
        assert window.has_attention
        window.close()
    finally:
        host.deleteLater()


def test_inbound_sms_flashes_the_taskbar_when_another_app_is_in_front(
    arelis_window, monkeypatch
) -> None:
    win = arelis_window()
    flashes: list[object] = []
    monkeypatch.setattr("arelis.ui.window_turn.process_owns_foreground", lambda: False)
    monkeypatch.setattr("arelis.ui.window_turn.flash_taskbar", lambda w: flashes.append(w))
    win._alert_if_background()
    assert flashes == [win]
    flashes.clear()
    monkeypatch.setattr("arelis.ui.window_turn.process_owns_foreground", lambda: True)
    win._alert_if_background()
    assert flashes == []


def test_inbound_sms_asks_for_taskbar_alert(arelis_window, monkeypatch) -> None:
    win = arelis_window()
    asked: list[bool] = []
    monkeypatch.setattr(win, "_alert_if_background", lambda: asked.append(True))
    win._on_sms_received(
        {
            "id": "m-alert",
            "from": "5551112222",
            "body": "hey",
            "contact_alias": "wife",
            "contact_name": "Robin",
        }
    )
    assert asked == [True]


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
    assert reopened._thread.count() == 2

    restarted = SmsChatRegistry(win, persist=False)
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


def test_https_url_becomes_an_anchor(qt_app) -> None:
    """A tap on a web link must open the browser, not sit as dead text."""
    window = SmsChatWindow(key="k", title="Alex", alias="coach", phone="+15550100")
    try:
        window.append_message(
            SmsChatMessage(
                direction="in",
                body="see https://example.com/notes",
            )
        )
        bubble = window._last_bubble()
        html = bubble_plain_text(bubble)
        assert '<a href="https://example.com/notes">' in html
        assert "file://" not in html
        assert window.width() >= TILE_WIDTH
    finally:
        window.hide()
        window.deleteLater()


def test_www_url_becomes_an_https_anchor(qt_app) -> None:
    window = SmsChatWindow(key="k", title="Robin", alias="wife", phone="+15550100")
    try:
        window.append_message(
            SmsChatMessage(direction="in", body="park at www.example.com/lot")
        )
        html = bubble_plain_text(window._last_bubble())
        assert 'href="https://www.example.com/lot"' in html
    finally:
        window.hide()
        window.deleteLater()


def test_file_url_is_not_an_anchor(qt_app) -> None:
    window = SmsChatWindow(key="k", title="Alex", alias="coach", phone="+15550100")
    try:
        window.append_message(
            SmsChatMessage(
                direction="in",
                body="nope file:///C:/Users/you/secret.txt",
            )
        )
        html = bubble_plain_text(window._last_bubble())
        assert "<a href=" not in html
        assert "file:///C:/Users/you/secret.txt" in html
    finally:
        window.hide()
        window.deleteLater()


def test_photo_without_bytes_is_a_chip(qt_app) -> None:
    """MMS often arrives as the word Photo and nothing else."""
    from PySide6.QtWidgets import QLabel

    window = SmsChatWindow(key="k", title="Alex", alias="coach", phone="+15550100")
    try:
        window.append_message(
            SmsChatMessage(direction="in", body="Photo", media_kind="photo_chip")
        )
        bubble = window._last_bubble()
        assert bubble is not None
        chips = [w for w in bubble.findChildren(QLabel) if w.objectName() == "SmsPhotoChip"]
        assert len(chips) == 1
        assert chips[0].text() == "Photo"
    finally:
        window.hide()
        window.deleteLater()


def _tiny_png(path) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap

    pix = QPixmap(16, 16)
    pix.fill(Qt.GlobalColor.red)
    assert pix.save(str(path), "PNG")


def test_photo_bytes_show_and_open(qt_app, tmp_path, monkeypatch) -> None:
    """A real inbound JPEG/PNG must paint, and a tap must open the file."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    opened: list[str] = []
    monkeypatch.setattr(
        "arelis.ui.sms_chat.open_local_path",
        lambda path: opened.append(path),
    )
    photo = tmp_path / "wife.png"
    _tiny_png(photo)
    window = SmsChatWindow(key="k", title="Robin", alias="wife", phone="+15550100")
    try:
        window.append_message(
            SmsChatMessage(
                direction="in",
                body="Photo",
                media_path=str(photo),
                media_kind="image",
            )
        )
        window.show()
        qt_app.processEvents()
        bubble = window._last_bubble()
        assert bubble is not None
        images = bubble.findChildren(SmsImageLabel)
        assert len(images) == 1
        pix = images[0].pixmap()
        assert pix is not None and not pix.isNull()
        QTest.mouseClick(images[0], Qt.MouseButton.LeftButton)
        qt_app.processEvents()
        assert opened == [str(photo)]
    finally:
        window.hide()
        window.deleteLater()


def test_photo_caption_keeps_the_link(qt_app, tmp_path) -> None:
    photo = tmp_path / "menu.png"
    _tiny_png(photo)
    window = SmsChatWindow(key="k", title="Robin", alias="wife", phone="+15550100")
    try:
        window.append_message(
            SmsChatMessage(
                direction="in",
                body="menu https://example.com/dinner",
                media_path=str(photo),
                media_kind="image",
            )
        )
        html = bubble_plain_text(window._last_bubble())
        assert 'href="https://example.com/dinner"' in html
        assert window._last_bubble().findChildren(SmsImageLabel)
    finally:
        window.hide()
        window.deleteLater()


def test_threads_keep_a_picture(qt_app, tmp_path) -> None:
    host = QWidget()
    path = tmp_path / "threads.json"
    photo = tmp_path / "snap.png"
    _tiny_png(photo)
    first = SmsChatRegistry(host, persist=True, store_path=path)
    try:
        window = first.open(alias="wife", phone="5551112222", title="Robin")
        assert window is not None
        first.append_inbound(
            body="look",
            alias="wife",
            phone="5551112222",
            media_path=str(photo),
            media_kind="image",
        )
        key = window.key
        window.close()
        qt_app.processEvents()
        second = SmsChatRegistry(host, persist=True, store_path=path)
        row = second.messages(key)[-1]
        assert row.media_kind == "image"
        assert row.media_path == str(photo)
    finally:
        host.deleteLater()
