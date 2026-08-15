"""Read calendar cache, local tasks, and contact-only mail headers for the pill."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from arelis.briefing.calendar import load_agenda, resolve_calendar_path
from arelis.calendar.store import DEFAULT_DB, CalendarStore
from arelis.contacts import load_contacts, match_mail_sender
from arelis.mail import load_account
from arelis.notify.center import new_notice

log = logging.getLogger(__name__)


def load_today_events(config: dict[str, Any] | None = None) -> list[Any]:
    """Google/Outlook cache first, then ICS. Never syncs providers on this path."""
    now = datetime.now().astimezone()
    today = now.date()
    events: list[Any] = []
    if DEFAULT_DB.is_file():
        try:
            store = CalendarStore()
            try:
                events = list(store.list_range(today, today))
            finally:
                store.close()
        except Exception as exc:
            log.debug("calendar cache unread: %s", exc)
            events = []
    if events:
        return events
    try:
        ics = load_agenda(
            resolve_calendar_path(config),
            now=now,
            start_day=today,
            end_day=today,
        )
    except Exception as exc:
        log.debug("ics unread: %s", exc)
        return []
    return list(ics)


def due_task_notices(
    rows: list[dict[str, Any]],
    *,
    today: date | None = None,
    remember,
) -> list:
    """Open tasks due today or overdue. ``remember(id) -> bool`` filters repeats."""
    day = today or datetime.now().astimezone().date()
    out = []
    for row in rows:
        due_raw = str(row.get("due") or "").strip()
        if not due_raw:
            continue
        try:
            due = date.fromisoformat(due_raw[:10])
        except ValueError:
            continue
        if due > day:
            continue
        task_id = str(row.get("id") or "")
        if not remember(task_id):
            continue
        title = str(row.get("title") or "task").strip() or "task"
        if due < day:
            body = f"{title} was due {due.isoformat()}."
            pill = f"{title} · overdue"
        else:
            body = f"{title} is due today."
            pill = f"{title} · due"
        out.append(
            new_notice(
                kind="task",
                title=title,
                body=body,
                group_key=f"task:{task_id}",
                data={"pill": pill, "task_id": task_id},
            )
        )
    return out


def peek_contact_mail_sync(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Header-only unread mail from contacts.yaml. Empty if mail is not set up."""
    account = load_account()
    if account is None:
        return []
    email_cfg = ((config or {}).get("tools") or {}).get("email") or {}
    try:
        from arelis.tools.inbox import InboxTool
    except Exception:
        return []
    tool = InboxTool(
        account,
        host=str(email_cfg.get("imap_host") or "imap.gmail.com"),
        port=int(email_cfg.get("imap_port") or 993),
        timeout_s=min(20.0, float(email_cfg.get("timeout_s") or 20)),
        max_messages=8,
    )
    try:
        result = tool._run_sync("list", {"action": "list", "unread_only": True, "limit": 8})
    except Exception as exc:
        log.debug("mail peek failed: %s", exc)
        return []
    if not result.ok:
        return []
    book = load_contacts()
    rows: list[dict[str, Any]] = []
    for item in (result.data or {}).get("messages") or []:
        if not isinstance(item, dict):
            continue
        sender = str(item.get("from") or "")
        contact = match_mail_sender(sender, book)
        if contact is None:
            continue
        rows.append(
            {
                "id": str(item.get("id") or ""),
                "from": sender,
                "subject": str(item.get("subject") or ""),
                "contact_alias": contact.alias,
                "contact_name": contact.name,
            }
        )
    return rows


def mail_notices(rows: list[dict[str, Any]], *, remember) -> list:
    out = []
    for row in rows:
        uid = str(row.get("id") or "")
        if not remember(uid):
            continue
        name = str(row.get("contact_name") or row.get("contact_alias") or "mail")
        subject = str(row.get("subject") or "(no subject)").strip()
        out.append(
            new_notice(
                kind="email",
                title=name,
                body=subject,
                group_key=f"email:{uid}",
                data={
                    "pill": f"{name} · mail",
                    "uid": uid,
                    "alias": row.get("contact_alias") or "",
                },
            )
        )
    return out
