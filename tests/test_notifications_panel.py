"""Notifications panel row layout (UI polish Pass B)."""

from __future__ import annotations

from arelis.ui.panels.notifications import NotificationsPanel


def test_notification_rows_include_time_and_body(qt_app) -> None:
    panel = NotificationsPanel()
    panel.add_message(
        message_id="m1",
        from_label="Wife",
        body="On my way home",
        time_text="21:14",
    )
    assert panel.list.count() == 1
    text = panel.list.item(0).text()
    assert "Wife" in text
    assert "21:14" in text
    assert "On my way home" in text
    assert "●" in text
    assert "\n" in text


def test_mark_read_clears_unread_mark(qt_app) -> None:
    panel = NotificationsPanel()
    panel.add_message(
        message_id="m1", from_label="A", body="hi", time_text="10:00"
    )
    assert panel.unread_count == 1
    panel.mark_all_read()
    assert panel.unread_count == 0
    assert "○" in panel.list.item(0).text()


def test_notify_overlay_pill_and_extra(qt_app) -> None:
    from arelis.notify.center import new_notice
    from arelis.ui.notify_overlay import NotifyOverlay

    overlay = NotifyOverlay()
    notice = new_notice(kind="sms", title="Robin", body="On my way")
    overlay.show_notice(notice, extra=2)
    assert "Robin" in overlay.pill.text()
    assert "+2" in overlay.pill.text()
    overlay.expand()
    assert overlay.expanded
    assert overlay.card.isVisible()
    assert overlay.dismiss_btn.text() == "dismiss"
    assert overlay.reply_btn.text() == "reply"
    overlay.collapse()
    assert not overlay.expanded
    opened: list[str] = []
    overlay.open_requested.connect(opened.append)
    overlay.pill.click()
    assert opened == [notice.id]
    overlay.deleteLater()


def test_short_sender_and_body_are_not_elided(qt_app) -> None:
    panel = NotificationsPanel()
    panel.resize(360, 480)
    panel.show()
    qt_app.processEvents()
    panel.add_message(
        message_id="m-robin",
        from_label="Robin",
        body="on my way — 10 min",
        time_text="now",
    )
    item = panel.list.item(0)
    text = item.text()
    assert "Robin" in text
    assert "Robin…" not in text
    assert "Robin..." not in text
    assert "on my way" in text
    assert "10 min" in text
    hint = item.sizeHint()
    assert hint.width() >= 240
    assert hint.height() >= 36
    panel.close()
