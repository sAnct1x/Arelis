"""Notify rail, job chip, and mail peek. Window methods stay as delegates."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from arelis.core.failure_copy import plain_reason
from arelis.local_open import open_local_file, open_local_file_as, reveal_local_file
from arelis.notify.center import notice_open
from arelis.notify.sources import (
    due_task_notices,
    load_today_events,
    mail_notices,
    peek_contact_mail_sync,
)


def on_notify_unread(window, count: int) -> None:
    if count > 0:
        window.act_notifications.setText(f"notifications ({count})")
    else:
        window.act_notifications.setText("notifications")
    from arelis.ui.theme import active_theme

    if active_theme() != "filament":
        return
    place = getattr(window, "_place_filament_floats", None)
    if callable(place):
        place(reshape=False)


def on_notify_inbox_closed(window) -> None:
    window.act_notifications.setChecked(False)
    sync_notify_surface(window)
    from arelis.ui.idle_host import sync_idle_mode

    sync_idle_mode(window)


def on_inbox_opened(window) -> None:
    sync_notify_surface(window)


def on_notify_mark_all_read(window) -> None:
    window.notify_center.clear_non_sticky()
    sync_notify_surface(window)


def park_notify_inbox(window) -> None:
    """Leave the pile once a click opened the real surface."""
    inbox = getattr(window, "notify_inbox", None)
    if inbox is None or inbox.isHidden():
        return
    inbox.close()


def on_notice_activated(window, notice_id: str) -> None:
    """Click opens the thing the notice is about. Clear drops the rest."""
    notice = window.notify_center.find(notice_id)
    if notice is None:
        return
    window.notifications.show_notice(notice_id)
    plan = notice_open(notice)
    opened = False
    if plan.action == "chat":
        from arelis.ui.sms_host import open_sms_chat

        opened = open_sms_chat(window, notice_id)
        if opened:
            park_notify_inbox(window)
            return
        show_notify_inbox(window, notice_id)
        return
    elif plan.action == "artifact":
        on_artifact_requested(window, notice_id, "open")
        opened = True
        park_notify_inbox(window)
    elif plan.action == "calendar":
        opened = reveal_calendar_notice(window, notice)
        if opened:
            park_notify_inbox(window)
    elif plan.action == "tasks":
        opened = reveal_calendar_notice(window, notice, tab="tasks")
        if opened:
            park_notify_inbox(window)
    elif plan.action == "email":
        opened = open_mail_notice(window, notice)
        if opened:
            park_notify_inbox(window)
    elif plan.action == "allow":
        opened = raise_allow_card(window)
        if opened:
            park_notify_inbox(window)
    if plan.dismiss and opened and not notice.sticky:
        window.notify_center.dismiss(notice_id)
        sync_notify_surface(window)


def reveal_calendar_notice(window, notice, *, tab: str = "calendar") -> bool:
    window.act_calendar.setChecked(True)
    window._toggle_calendar(True)
    cal = window.calendar
    if tab == "tasks":
        cal.show_tasks_tab()
        return True
    event_id = str((notice.data or {}).get("event_id") or "")
    if event_id and cal.show_event(event_id):
        return True
    raw = str((notice.data or {}).get("starts_at") or "")
    if raw:
        try:
            stamp = datetime.fromisoformat(raw)
            cal.show_day(stamp.date())
        except ValueError:
            pass
    return True


def open_mail_notice(window, notice) -> bool:
    """Fetch the message and open a reader. Subject-only notices stay on the pile."""
    uid = str((notice.data or {}).get("uid") or "").strip()
    sender = str((notice.data or {}).get("from") or notice.title or "")
    subject = str((notice.data or {}).get("subject") or notice.body or "")
    body = ""
    if uid:
        body, sender, subject = _fetch_mail_body(window, uid, sender, subject)
    if not body and not subject:
        show_notify_inbox(window, notice.id)
        return False
    from arelis.mail import reply_address
    from arelis.ui.mail_peek import MailPeekWindow

    peek = MailPeekWindow(
        sender=sender,
        subject=subject,
        body=body or subject,
        reply_to=reply_address(sender),
        parent=window,
    )
    peek.reply_requested.connect(
        lambda to, subj, text, w=window, tile=peek: send_mail_reply(w, tile, to, subj, text)
    )
    window._mail_peek = peek
    peek.show()
    peek.raise_()
    peek.activateWindow()
    return True


def _fetch_mail_body(window, uid: str, sender: str, subject: str) -> tuple[str, str, str]:
    try:
        from arelis.mail import load_account
        from arelis.tools.inbox import InboxTool

        account = load_account()
        if account is None:
            return "", sender, subject
        email_cfg = ((window.config or {}).get("tools") or {}).get("email") or {}
        tool = InboxTool(
            account,
            host=str(email_cfg.get("imap_host") or "imap.gmail.com"),
            port=int(email_cfg.get("imap_port") or 993),
            timeout_s=min(20.0, float(email_cfg.get("timeout_s") or 20)),
        )
        result = tool._run_sync("read", {"action": "read", "id": uid})
    except Exception as exc:
        return f"(could not load the message: {plain_reason(exc)})", sender, subject
    data = result.data or {}
    return (
        str(data.get("body") or result.output or ""),
        str(data.get("from") or sender),
        str(data.get("subject") or subject),
    )


def send_mail_reply(window, tile, to: str, subject: str, body: str) -> None:
    try:
        from arelis.mail import Mailer, load_account

        account = load_account()
        if account is None:
            tile.set_status("Mail is not set up. Add it in Settings → notify.")
            return
        Mailer(account).send(to=to, subject=subject, body=body)
        tile.set_status("sent")
    except Exception as exc:
        tile.set_status(plain_reason(exc))


def raise_allow_card(window) -> bool:
    window.raise_()
    window.activateWindow()
    confirm = getattr(window.conversation, "confirm", None)
    if confirm is not None:
        confirm.show()
    return True


def sync_notify_surface(window) -> None:
    # Reachable before the mailbox windows exist: restoring a saved layout
    # that was maximized calls setWindowState from inside __init__, and the
    # WindowStateChange lands here. That raised AttributeError, which run_ui
    # turns into "Arelis window failed to start" — so a maximized glass could
    # be closed one evening and refuse to open at all the next.
    if not hasattr(window, "notify_inbox"):
        return
    head = window.notify_center.head()
    extra = window.notify_center.extra_count()
    maximized = window.isMaximized() or window.isFullScreen()
    mailbox_open = window.notify_inbox.isVisible()
    overlay = window.conversation.notify_overlay
    overlay.show_notice(
        head, extra=extra, maximized=maximized, mailbox_open=mailbox_open
    )
    chip_text = ""
    if head is not None:
        chip_text = head.pill_label()
        if extra:
            chip_text = f"{chip_text} · +{extra}"
    window.readiness_strip.set_notify_chip(
        chip_text, visible=maximized and head is not None and not mailbox_open
    )
    window.notifications.set_notices(
        window.notify_center.visible_items(),
        unread=window.notify_center.unread_count(),
    )
    on_notify_unread(window, window.notify_center.unread_count())
    from arelis.ui.idle_host import idle_eligible, sync_idle_mode

    idle = idle_eligible(window)
    if idle != bool(window.conversation._idle_mode):
        sync_idle_mode(window)


def on_notify_pill_clicked(window) -> None:
    """The pill also emits open_requested; that path opens the thing."""
    return


def on_notify_chip_clicked(window) -> None:
    head = window.notify_center.head()
    if head is None:
        return
    on_notice_open(window, head.id)


def on_notice_dismiss(window, notice_id: str) -> None:
    window.notify_center.dismiss(notice_id)
    sync_notify_surface(window)


def on_notice_snooze(window, notice_id: str, minutes: int = 15) -> None:
    hold = max(1, int(minutes))
    window.notify_center.snooze(
        notice_id, datetime.now().astimezone() + timedelta(minutes=hold)
    )
    sync_notify_surface(window)


def show_notify_inbox(window, notice_id: str) -> None:
    window.act_notifications.setChecked(True)
    window._toggle_notifications(True)
    if notice_id:
        window.notifications.show_notice(notice_id)
    from arelis.ui.foreground import claim_foreground

    claim_foreground(window.notify_inbox)


def on_notice_open(window, notice_id: str) -> None:
    notice = window.notify_center.find(notice_id) if notice_id else None
    if notice is None:
        show_notify_inbox(window, notice_id)
        return
    on_notice_activated(window, notice_id)


def begin_job(window, tool: str) -> None:
    window._job_name = tool
    window._job_t0 = time.monotonic()
    window.notify_center.upsert_job(tool, elapsed_s=0)
    window._job_tick.start()
    sync_notify_surface(window)


def finish_job(
    window, tool: str, *, ok: bool, output: str = "", path: str = ""
) -> None:
    window._job_tick.stop()
    window._job_t0 = None
    window._job_name = ""
    artifact = (path or "").strip()
    if ok:
        window.notify_center.upsert_job(
            tool, done=True, output=output, path=artifact
        )
        from arelis.ui.sms_host import push_mobile_notice

        push_mobile_notice(window, "job", f"{tool} finished", output or f"{tool} is ready.")
    else:
        window.notify_center.upsert_job(
            tool, failed=True, output=output, path=artifact
        )
        from arelis.ui.sms_host import push_mobile_notice

        push_mobile_notice(window, "job", f"{tool} failed", output or f"{tool} failed.")
    sync_notify_surface(window)


def on_artifact_requested(window, notice_id: str, how: str) -> None:
    """Open / Open with… / show in folder for a job that wrote a file."""
    notice = window.notify_center.find(notice_id)
    raw = ""
    if notice is not None:
        raw = str((notice.data or {}).get("path") or "").strip()
    if not raw:
        return
    target = Path(raw).expanduser()
    try:
        if how == "reveal":
            reveal_local_file(target)
        elif how == "openas":
            open_local_file_as(target)
        elif _open_workspace_artifact(window, raw):
            return
        else:
            open_local_file(target)
    except OSError as exc:
        leaf = target.name or "that file"
        window.chat.add_system(f"I could not open {leaf}. {plain_reason(exc)}")


def _open_workspace_artifact(window, raw: str) -> bool:
    """Prefer the desk for text she wrote. Anything else uses the OS."""
    roots = getattr(window, "workspace_roots", None)
    if roots is None:
        return False
    try:
        roots.resolve_read(raw)
    except Exception:
        return False
    from arelis.ui.workspace_host import open_file

    open_file(window, raw)
    return True


def on_job_tick(window) -> None:
    if window._job_t0 is None or not window._job_name:
        window._job_tick.stop()
        return
    window.notify_center.upsert_job(
        window._job_name, elapsed_s=time.monotonic() - window._job_t0
    )
    sync_notify_surface(window)


def report_poll_state(window, key: str, message: str) -> None:
    """Speak poll failure/recovery, but ignore single-shot network blips.

    IMAP peek fails on timeout, DNS, and unreachable-network as often as
    the Wi-Fi hiccups. Reporting every transition taught the rail to be
    ignored. Two consecutive failures (or two consecutive recoveries)
    still surface; a lone blip does not.
    """
    if message:
        window._poll_fail_streak[key] = window._poll_fail_streak.get(key, 0) + 1
        window._poll_ok_streak[key] = 0
        window._poll_state[key] = message
        if (
            window._poll_fail_streak[key] >= 2
            and window._poll_spoken.get(key) != "down"
        ):
            window._poll_spoken[key] = "down"
            window.thinking.append(message, kind="status")
        return
    window._poll_ok_streak[key] = window._poll_ok_streak.get(key, 0) + 1
    window._poll_fail_streak[key] = 0
    window._poll_state[key] = ""
    if (
        window._poll_ok_streak[key] >= 2
        and window._poll_spoken.get(key) == "down"
    ):
        window._poll_spoken[key] = "up"
        window.thinking.append(
            f"{key} notifications are working again.", kind="status"
        )


def on_notify_poll(window) -> None:
    if window._force_quit or window._disposed:
        return
    now = datetime.now().astimezone()
    try:
        events = load_today_events(window.config)
        window.notify_center.apply_calendar(events, now)
    except Exception as exc:
        report_poll_state(
            window, "calendar", f"Calendar notifications stopped: {plain_reason(exc)}"
        )
    else:
        report_poll_state(window, "calendar", "")
    if window.store is not None and window.notify_center.enabled("task"):
        try:
            rows = window.store.list_tasks(status="open", limit=40)
            for notice in due_task_notices(
                rows, today=now.date(), remember=window.notify_center.remember_task
            ):
                window.notify_center.add(notice)
        except Exception as exc:
            report_poll_state(
                window, "task", f"Task due notices stopped: {plain_reason(exc)}"
            )
        else:
            report_poll_state(window, "task", "")
    sync_notify_surface(window)
    mail_cfg = (window.config.get("ui") or {}).get("notifications") or {}
    mail_every = max(45.0, float(mail_cfg.get("mail_poll_s") or 90))
    if (
        window.notify_center.enabled("email")
        and not window._mail_poll_inflight
        and (time.monotonic() - window._mail_poll_at) >= mail_every
    ):
        kick_mail_poll(window)


def kick_mail_poll(window) -> None:
    window._mail_poll_inflight = True
    window._mail_poll_at = time.monotonic()

    def _work() -> None:
        try:
            rows: object = peek_contact_mail_sync(window.config)
        except Exception as exc:
            rows = exc
        window.mail_headers_ready.emit(rows)

    threading.Thread(target=_work, daemon=True, name="arelis-mail-peek").start()


def on_mail_headers(window, rows: object) -> None:
    window._mail_poll_inflight = False
    if isinstance(rows, BaseException):
        # Email notices are switched on and the user is waiting for them.
        # A debug log is not a place anybody is looking.
        report_poll_state(window, "mail", plain_reason(rows))
        return
    if not isinstance(rows, list):
        return
    report_poll_state(window, "mail", "")
    for notice in mail_notices(rows, remember=window.notify_center.remember_mail):
        window.notify_center.add(notice)
    sync_notify_surface(window)


def bind_notify(window) -> None:
    window.notifications.unread_changed.connect(
        lambda count: on_notify_unread(window, count)
    )
    window.notify_inbox.closed.connect(lambda: on_notify_inbox_closed(window))
    overlay = window.conversation.notify_overlay
    overlay.dismiss_requested.connect(lambda nid: on_notice_dismiss(window, nid))
    overlay.snooze_requested.connect(
        lambda nid, mins=15: on_notice_snooze(window, nid, mins)
    )
    overlay.open_requested.connect(lambda nid: on_notice_open(window, nid))
    overlay.artifact_requested.connect(
        lambda nid, how: on_artifact_requested(window, nid, how)
    )
    overlay.pill_clicked.connect(lambda: on_notify_pill_clicked(window))
    window.readiness_strip.notify_chip.clicked.connect(
        lambda: on_notify_chip_clicked(window)
    )
    window.mail_headers_ready.connect(lambda rows: on_mail_headers(window, rows))
    window.notifications.opened.connect(lambda: on_inbox_opened(window))
    window.notifications.notice_activated.connect(
        lambda notice_id: on_notice_activated(window, notice_id)
    )
    window.notifications.artifact_requested.connect(
        lambda notice_id, how: on_artifact_requested(window, notice_id, how)
    )
    window.notifications.mark_read_btn.clicked.connect(
        lambda: on_notify_mark_all_read(window)
    )
    window._notify_timer.timeout.connect(lambda: on_notify_poll(window))
    window._job_tick.timeout.connect(lambda: on_job_tick(window))

