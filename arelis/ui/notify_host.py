"""Notify rail, job chip, and mail peek. Window methods stay as delegates."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

from arelis.core.failure_copy import plain_reason
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
    window._sync_notify_surface()
    window._sync_idle_mode()


def on_inbox_opened(window) -> None:
    window._sync_notify_surface()


def on_notify_mark_all_read(window) -> None:
    window.notify_center.clear_non_sticky()
    window._sync_notify_surface()


def on_notice_activated(window, notice_id: str) -> None:
    notice = window.notify_center.find(notice_id)
    if notice is not None and notice.unread:
        window.notify_center.mark_read(notice_id)
        window._sync_notify_surface()
    window.notifications.show_notice(notice_id)


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
    window._on_notify_unread(window.notify_center.unread_count())
    idle = window._idle_eligible()
    if idle != bool(window.conversation._idle_mode):
        window._sync_idle_mode()


def on_notify_pill_clicked(window) -> None:
    head = window.notify_center.head()
    if head is not None and not head.sticky:
        window.notify_center.mark_read(head.id)
    window._sync_notify_surface()


def on_notify_chip_clicked(window) -> None:
    head = window.notify_center.head()
    if head is None:
        return
    window._on_notice_open(head.id)


def on_notice_dismiss(window, notice_id: str) -> None:
    window.notify_center.dismiss(notice_id)
    window._sync_notify_surface()


def on_notice_snooze(window, notice_id: str) -> None:
    window.notify_center.snooze(
        notice_id, datetime.now().astimezone() + timedelta(minutes=15)
    )
    window._sync_notify_surface()


def on_notice_open(window, notice_id: str) -> None:
    window.act_notifications.setChecked(True)
    window._toggle_notifications(True)
    if notice_id:
        window.notifications.show_notice(notice_id)


def begin_job(window, tool: str) -> None:
    window._job_name = tool
    window._job_t0 = time.monotonic()
    window.notify_center.upsert_job(tool, elapsed_s=0)
    window._job_tick.start()
    window._sync_notify_surface()


def finish_job(window, tool: str, *, ok: bool, output: str = "") -> None:
    window._job_tick.stop()
    window._job_t0 = None
    window._job_name = ""
    if ok:
        window.notify_center.upsert_job(tool, done=True, output=output)
        window._push_mobile_notice("job", f"{tool} finished", output or f"{tool} is ready.")
    else:
        window.notify_center.upsert_job(tool, failed=True, output=output)
        window._push_mobile_notice("job", f"{tool} failed", output or f"{tool} failed.")
    window._sync_notify_surface()


def on_job_tick(window) -> None:
    if window._job_t0 is None or not window._job_name:
        window._job_tick.stop()
        return
    window.notify_center.upsert_job(
        window._job_name, elapsed_s=time.monotonic() - window._job_t0
    )
    window._sync_notify_surface()


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
        window._report_poll_state(
            "calendar", f"Calendar notifications stopped: {plain_reason(exc)}"
        )
    else:
        window._report_poll_state("calendar", "")
    if window.store is not None and window.notify_center.enabled("task"):
        try:
            rows = window.store.list_tasks(status="open", limit=40)
            for notice in due_task_notices(
                rows, today=now.date(), remember=window.notify_center.remember_task
            ):
                window.notify_center.add(notice)
        except Exception as exc:
            window._report_poll_state(
                "task", f"Task due notices stopped: {plain_reason(exc)}"
            )
        else:
            window._report_poll_state("task", "")
    window._sync_notify_surface()
    mail_cfg = (window.config.get("ui") or {}).get("notifications") or {}
    mail_every = max(45.0, float(mail_cfg.get("mail_poll_s") or 90))
    if (
        window.notify_center.enabled("email")
        and not window._mail_poll_inflight
        and (time.monotonic() - window._mail_poll_at) >= mail_every
    ):
        window._kick_mail_poll()


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
        window._report_poll_state("mail", plain_reason(rows))
        return
    if not isinstance(rows, list):
        return
    window._report_poll_state("mail", "")
    for notice in mail_notices(rows, remember=window.notify_center.remember_mail):
        window.notify_center.add(notice)
    window._sync_notify_surface()

