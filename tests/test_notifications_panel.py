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
    assert "●" not in text
    assert "○" not in text
    assert "\n" in text


def test_clear_removes_the_rows(qt_app) -> None:
    """Mark-all-read used to grey the dots and leave the texts sitting there."""
    panel = NotificationsPanel()
    panel.add_message(
        message_id="m1", from_label="A", body="hi", time_text="10:00"
    )
    assert panel.unread_count == 1
    panel.clear()
    assert panel.unread_count == 0
    assert panel.list.count() == 0
    assert "caught up" in panel.hint.text()
    panel.deleteLater()


def test_clear_keeps_a_sticky_row(qt_app) -> None:
    panel = NotificationsPanel()
    panel.add_message(
        message_id="allow",
        from_label="Allow",
        body="send email",
        kind="allow",
        sticky=True,
    )
    panel.add_message(message_id="sms", from_label="A", body="hi")
    panel.clear()
    assert panel.list.count() == 1
    assert "Allow" in panel.list.item(0).text()
    panel.deleteLater()


def test_click_does_not_clone_the_body_underneath(qt_app) -> None:
    """The inbox row already has the text. A second pane reprinted it."""
    from PySide6.QtWidgets import QLabel

    from arelis.notify.center import new_notice

    panel = NotificationsPanel()
    notice = new_notice(kind="email", title="Robin", body="On my way")
    panel.set_notices([notice])
    panel._on_item(panel.list.item(0))
    qt_app.processEvents()
    assert panel.findChild(QLabel, "NotificationDetail") is None
    assert panel.list.item(0).text().count("On my way") == 1
    panel.deleteLater()


def test_research_job_double_click_requests_open(qt_app) -> None:
    from arelis.notify.center import new_notice

    panel = NotificationsPanel()
    notice = new_notice(
        kind="job",
        title="research_report",
        body="ready",
        data={"path": "C:/tmp/report.md", "done": True, "tool": "research_report"},
    )
    panel.set_notices([notice])
    opened: list[tuple[str, str]] = []
    panel.artifact_requested.connect(lambda nid, how: opened.append((nid, how)))
    panel._on_double(panel.list.item(0))
    assert opened == [(notice.id, "open")]
    panel.deleteLater()


def test_sms_row_click_activates_the_notice(qt_app) -> None:
    from arelis.notify.center import new_notice

    panel = NotificationsPanel()
    notice = new_notice(
        kind="sms",
        title="Robin",
        body="hi",
        data={"from": "+15550100", "alias": "wife"},
    )
    panel.set_notices([notice])
    opened: list[str] = []
    chats: list[str] = []
    panel.notice_activated.connect(opened.append)
    panel.chat_requested.connect(chats.append)
    panel._on_item(panel.list.item(0))
    assert opened == [notice.id]
    assert chats == []
    assert "●" not in panel.list.item(0).text()
    panel.deleteLater()


def test_snooze_choices_cover_short_and_tomorrow() -> None:
    from arelis.ui.notify_overlay import SNOOZE_CHOICES

    minutes = [hold for _, hold in SNOOZE_CHOICES]
    assert minutes == [5, 15, 60, 24 * 60]


def test_snooze_minutes_reach_the_center(qt_app, monkeypatch) -> None:
    from datetime import datetime, timedelta

    from arelis.notify.center import NotificationCenter, new_notice
    from arelis.ui import notify_host

    notice = new_notice(kind="sms", title="Robin", body="later")
    center = NotificationCenter()
    center.add(notice)
    window = type("W", (), {"notify_center": center})()
    monkeypatch.setattr(notify_host, "sync_notify_surface", lambda _w: None)
    now = datetime.now().astimezone()
    notify_host.on_notice_snooze(window, notice.id, 60)
    assert not any(
        n.id == notice.id
        for n in center.visible_items(now=now + timedelta(minutes=30))
    )
    later = [
        n
        for n in center.visible_items(now=now + timedelta(minutes=61))
        if n.id == notice.id
    ]
    assert later


def test_mail_peek_reply_prefixes_subject(qt_app) -> None:
    from arelis.ui.mail_peek import MailPeekWindow

    peek = MailPeekWindow(
        sender="Robin <robin@example.com>",
        subject="Thursday",
        body="Are we still on?",
        reply_to="robin@example.com",
    )
    sent: list[tuple[str, str, str]] = []
    peek.reply_requested.connect(lambda to, subj, body: sent.append((to, subj, body)))
    try:
        assert peek.body.toPlainText() == "Are we still on?"
        peek.reply_edit.setText("yes")
        peek._reply()
        assert sent == [("robin@example.com", "Re: Thursday", "yes")]
        assert peek.reply_edit.text() == ""
    finally:
        peek.close()
        peek.deleteLater()


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
    assert overlay.reply_btn.text() == "chat"
    overlay.collapse()
    assert not overlay.expanded
    opened: list[str] = []
    overlay.open_requested.connect(opened.append)
    overlay.pill.click()
    assert opened == [notice.id]
    overlay.deleteLater()


def test_research_overlay_open_file(qt_app) -> None:
    from arelis.notify.center import new_notice
    from arelis.ui.notify_overlay import NotifyOverlay

    overlay = NotifyOverlay()
    notice = new_notice(
        kind="job",
        title="research_report",
        body="ready",
        data={"path": "C:/tmp/report.md", "pill": "research_report · ready"},
    )
    overlay.show_notice(notice)
    overlay.expand()
    assert overlay.open_btn.text() == "open file"
    hits: list[tuple[str, str]] = []
    overlay.artifact_requested.connect(lambda nid, how: hits.append((nid, how)))
    overlay.open_btn.click()
    assert hits == [(notice.id, "open")]
    overlay.deleteLater()


def test_mailbox_open_hides_the_pill(qt_app) -> None:
    from arelis.notify.center import new_notice
    from arelis.ui.notify_overlay import NotifyOverlay

    overlay = NotifyOverlay()
    notice = new_notice(kind="sms", title="Robin", body="On my way")
    overlay.show_notice(notice, mailbox_open=True)
    assert overlay.isHidden()
    overlay.show_notice(notice, mailbox_open=False)
    assert overlay.pill.isVisible()
    assert not overlay.isHidden()
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


def test_notifications_inbox_is_opaque_and_rounded(qt_app) -> None:
    """Opaque HWND + mask: no see-through plate, no black corner square."""
    from PySide6.QtCore import Qt

    from arelis.ui.glass import GlassFrame
    from arelis.ui.notify_inbox import NotificationsInboxWindow

    panel = NotificationsPanel()
    inbox = NotificationsInboxWindow(panel)
    try:
        inbox.show()
        qt_app.processEvents()
        assert not inbox.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        assert not inbox.mask().isEmpty()
        plates = inbox.findChildren(GlassFrame)
        assert plates and plates[0]._round_cutout
    finally:
        inbox.hide()
        inbox.deleteLater()
        panel.deleteLater()


def test_notify_pill_sits_above_the_room_strip(qt_app) -> None:
    """The live pill used to land on the room plate and cover world / leave."""
    from PySide6.QtCore import QRect

    from arelis.notify.center import new_notice
    from arelis.spatial import PHYSICS_ROOM_ID
    from arelis.ui.panels.conversation import ConversationStage
    from arelis.ui.theme import SPACE

    stage = ConversationStage()
    try:
        stage.resize(960, 640)
        stage.show()
        qt_app.processEvents()
        stage.room.set_room(
            PHYSICS_ROOM_ID,
            name="Reality",
            purpose="Spatial stage. Hands and voice drive a live simulation.",
        )
        qt_app.processEvents()
        notice = new_notice(kind="sms", title="Norma", body="2")
        stage.notify_overlay.show_notice(notice, extra=2)
        qt_app.processEvents()

        overlay = stage.notify_overlay
        room = stage.room
        assert overlay.isVisible()
        assert room.isVisible()
        assert overlay.y() + overlay.height() <= room.y()
        assert not overlay.geometry().intersects(room.geometry())

        world = room.world_btn
        assert world.isVisible()
        world_on_stage = QRect(
            room.mapTo(stage, world.geometry().topLeft()),
            world.size(),
        )
        leave = room.leave_btn
        leave_on_stage = QRect(
            room.mapTo(stage, leave.geometry().topLeft()),
            leave.size(),
        )
        assert not overlay.geometry().intersects(world_on_stage)
        assert not overlay.geometry().intersects(leave_on_stage)

        stage.room.set_room("")
        qt_app.processEvents()
        assert stage.layout().contentsMargins().top() == SPACE["inset"]
    finally:
        stage.hide()
        stage.deleteLater()
