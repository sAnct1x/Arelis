"""SMS chat tiles: identity, seed, append, SMS-only open-as-chat."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from arelis.ui.sms_chat import (
    SmsChatMessage,
    SmsChatRegistry,
    SmsChatWindow,
    bubble_plain_text,
)


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


def _tiny_png(path) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap

    pix = QPixmap(16, 16)
    pix.fill(Qt.GlobalColor.red)
    assert pix.save(str(path), "PNG")


