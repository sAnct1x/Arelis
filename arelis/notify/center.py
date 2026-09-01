"""Unified notices for the glass pill. Pure logic — no Qt, no IMAP."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

ChannelMode = Literal["off", "visual", "voice"]

CHANNELS: tuple[str, ...] = ("sms", "calendar", "email", "job", "task", "allow")

_KIND_RANK = {
    "allow": 0,
    "sms": 1,
    "calendar": 2,
    "email": 3,
    "job": 4,
    "task": 5,
}

_DEFAULT_CHANNELS: dict[str, ChannelMode] = {
    "sms": "voice",
    "calendar": "visual",
    "email": "visual",
    "job": "visual",
    "task": "visual",
    "allow": "visual",
}

_DEFAULT_LEADS = (15, 5, 0)


def load_channels(config: dict[str, Any] | None) -> dict[str, ChannelMode]:
    raw = ((config or {}).get("ui") or {}).get("notifications") or {}
    channels = dict(_DEFAULT_CHANNELS)
    incoming = raw.get("channels") or {}
    if isinstance(incoming, dict):
        for key, value in incoming.items():
            mode = str(value or "").strip().lower()
            if key in CHANNELS and mode in {"off", "visual", "voice"}:
                channels[str(key)] = mode  # type: ignore[assignment]
    return channels


def channel_mode(config: dict[str, Any] | None, kind: str) -> ChannelMode:
    return load_channels(config).get(kind, "off")


def _leads_from_config(config: dict[str, Any] | None) -> tuple[int, ...]:
    raw = ((config or {}).get("ui") or {}).get("notifications") or {}
    leads = raw.get("calendar_leads_min") or list(_DEFAULT_LEADS)
    out: list[int] = []
    for item in leads:
        try:
            out.append(max(0, int(item)))
        except (TypeError, ValueError):
            continue
    return tuple(out) or _DEFAULT_LEADS


@dataclass
class Notice:
    id: str
    kind: str
    title: str
    body: str
    group_key: str
    created_at: datetime
    unread: bool = True
    sticky: bool = False
    lead: str = ""
    voice_cue: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def count(self) -> int:
        try:
            return max(1, int(self.data.get("count") or 1))
        except (TypeError, ValueError):
            return 1

    def pill_label(self) -> str:
        if self.kind == "sms" and self.count > 1:
            return f"{self.title} · {self.count}"
        extra = str(self.data.get("pill") or "").strip()
        if extra:
            return extra
        return self.title


class NotificationCenter:
    """In-process inbox for the open UI session."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.items: list[Notice] = []
        # Calendar lead keys (event_id:lead) already fired or dismissed.
        self._calendar_done: set[str] = set()
        self._snooze_until: dict[str, datetime] = {}
        self._seen_mail: set[str] = set()
        self._seen_tasks: set[str] = set()

    def set_config(self, config: dict[str, Any] | None) -> None:
        self.config = config or {}

    def mode(self, kind: str) -> ChannelMode:
        return channel_mode(self.config, kind)

    def enabled(self, kind: str) -> bool:
        return self.mode(kind) != "off"

    def unread_count(self) -> int:
        now = datetime.now().astimezone()
        return sum(1 for n in self.items if n.unread and not self._is_snoozed(n, now))

    def visible_items(self, *, now: datetime | None = None) -> list[Notice]:
        stamp = now or datetime.now().astimezone()
        live = [n for n in self.items if not self._is_snoozed(n, stamp)]
        live.sort(
            key=lambda n: (
                0 if n.unread else 1,
                _KIND_RANK.get(n.kind, 9),
                -n.created_at.timestamp(),
            )
        )
        return live

    def head(self, *, now: datetime | None = None) -> Notice | None:
        visible = self.visible_items(now=now)
        unread = [n for n in visible if n.unread]
        if unread:
            return unread[0]
        sticky = [n for n in visible if n.sticky]
        return sticky[0] if sticky else None

    def extra_count(self, *, now: datetime | None = None) -> int:
        head = self.head(now=now)
        if head is None:
            return 0
        return max(0, self.unread_count() - (1 if head.unread else 0))

    def add(self, notice: Notice) -> Notice | None:
        if not self.enabled(notice.kind):
            return None
        if notice.kind == "sms":
            return self._merge_sms(notice)
        existing = next((n for n in self.items if n.id == notice.id), None)
        if existing is not None:
            existing.title = notice.title
            existing.body = notice.body
            existing.unread = True
            existing.voice_cue = notice.voice_cue
            existing.data = dict(notice.data)
            existing.sticky = notice.sticky
            existing.lead = notice.lead
            existing.created_at = notice.created_at
            return existing
        self.items.insert(0, notice)
        return notice

    def dismiss(self, notice_id: str) -> None:
        kept: list[Notice] = []
        for item in self.items:
            if item.id != notice_id:
                kept.append(item)
                continue
            if item.kind == "calendar":
                event_id = str(item.data.get("event_id") or "")
                lead = item.lead or ""
                if event_id:
                    self._calendar_done.add(f"{event_id}:{lead}")
                    # Dismissing a later lead should not revive earlier ones;
                    # dismissing any lead quiets remaining leads for the event.
                    for leftover in ("t15", "t5", "start"):
                        self._calendar_done.add(f"{event_id}:{leftover}")
        self.items = kept
        self._snooze_until.pop(notice_id, None)

    def snooze(self, notice_id: str, until: datetime) -> None:
        self._snooze_until[notice_id] = until
        for item in self.items:
            if item.id == notice_id:
                item.unread = False

    def mark_read(self, notice_id: str) -> None:
        for item in self.items:
            if item.id == notice_id:
                item.unread = False

    def mark_all_read(self) -> None:
        for item in self.items:
            item.unread = False

    def clear_non_sticky(self) -> None:
        """Clear means gone. Keep Allow and a running or failed job."""
        kept: list[Notice] = []
        for item in self.items:
            if item.sticky:
                kept.append(item)
                continue
            if item.kind == "calendar":
                event_id = str(item.data.get("event_id") or "")
                lead = item.lead or ""
                if event_id:
                    self._calendar_done.add(f"{event_id}:{lead}")
                    for leftover in ("t15", "t5", "start"):
                        self._calendar_done.add(f"{event_id}:{leftover}")
            self._snooze_until.pop(item.id, None)
        self.items = kept

    def clear_kind(self, kind: str) -> None:
        self.items = [n for n in self.items if n.kind != kind]

    def find(self, notice_id: str) -> Notice | None:
        return next((n for n in self.items if n.id == notice_id), None)

    def find_group(self, group_key: str) -> Notice | None:
        return next((n for n in self.items if n.group_key == group_key), None)

    def set_allow(self, pending: bool, summary: str = "") -> Notice | None:
        self.clear_kind("allow")
        if not pending:
            return None
        return self.add(
            new_notice(
                kind="allow",
                title="Allow",
                body=(summary or "A tool is waiting for Allow.").strip(),
                group_key="allow",
                sticky=True,
                data={"pill": "Allow"},
            )
        )

    def upsert_job(
        self,
        tool: str,
        *,
        elapsed_s: float | None = None,
        done: bool = False,
        failed: bool = False,
        output: str = "",
        path: str = "",
    ) -> Notice | None:
        name = (tool or "job").strip() or "job"
        key = f"job:{name}"
        if failed:
            body = (output or f"{name} failed.").strip()
            pill = f"{name} · failed"
            sticky = True
            unread = True
        elif done:
            body = (output or f"{name} finished.").strip()
            pill = f"{name} · ready"
            sticky = False
            unread = True
        else:
            secs = max(0, int(elapsed_s or 0))
            pill = f"{name} · {secs // 60}:{secs % 60:02d}"
            body = f"{name} is still running."
            sticky = True
            unread = True
        existing = self.find_group(key)
        if existing is not None:
            existing.title = name
            existing.body = body
            existing.sticky = sticky
            existing.unread = unread
            existing.data["pill"] = pill
            existing.data["tool"] = name
            existing.data["failed"] = failed
            existing.data["done"] = done
            if path:
                existing.data["path"] = path
            if not failed and not done:
                existing.created_at = existing.created_at
            return existing
        data = {
            "pill": pill,
            "tool": name,
            "failed": failed,
            "done": done,
        }
        if path:
            data["path"] = path
        return self.add(
            new_notice(
                kind="job",
                title=name,
                body=body,
                group_key=key,
                sticky=sticky,
                data=data,
            )
        )

    def remember_mail(self, uid: str) -> bool:
        """True if this mailbox uid is new to the session."""
        if not uid or uid in self._seen_mail:
            return False
        self._seen_mail.add(uid)
        return True

    def remember_task(self, task_id: str) -> bool:
        if not task_id or task_id in self._seen_tasks:
            return False
        self._seen_tasks.add(task_id)
        return True

    def apply_calendar(
        self,
        events: list[Any],
        now: datetime,
    ) -> list[Notice]:
        if not self.enabled("calendar"):
            return []
        leads = _leads_from_config(self.config)
        fresh = calendar_lead_notices(
            events,
            now,
            leads_min=leads,
            already=self._calendar_done,
        )
        added: list[Notice] = []
        for notice in fresh:
            self._calendar_done.add(f"{notice.data.get('event_id')}:{notice.lead}")
            got = self.add(notice)
            if got is not None:
                added.append(got)
        return added

    def _merge_sms(self, notice: Notice) -> Notice:
        key = notice.group_key
        existing = next((n for n in self.items if n.group_key == key), None)
        body = (notice.body or "").strip()
        if existing is None:
            notice.data.setdefault("bodies", [body] if body else [])
            notice.data["count"] = 1
            self.items.insert(0, notice)
            return notice
        bodies = list(existing.data.get("bodies") or [])
        last = str(bodies[-1]).strip() if bodies else (existing.body or "").strip()
        if body and body.casefold() == last.casefold():
            existing.unread = True
            existing.created_at = notice.created_at
            self.items = [existing, *[n for n in self.items if n.id != existing.id]]
            return existing
        if body:
            bodies.append(body)
        existing.data["bodies"] = bodies
        existing.data["count"] = len(bodies) or existing.count + 1
        existing.body = body or existing.body
        existing.title = notice.title
        existing.unread = True
        existing.created_at = notice.created_at
        existing.voice_cue = notice.voice_cue
        existing.data["from"] = notice.data.get("from") or existing.data.get("from")
        existing.data["alias"] = notice.data.get("alias") or existing.data.get("alias")
        # Newest grouped SMS rises to the top.
        self.items = [existing, *[n for n in self.items if n.id != existing.id]]
        return existing

    def _is_snoozed(self, notice: Notice, now: datetime) -> bool:
        until = self._snooze_until.get(notice.id)
        if until is None:
            return False
        if now >= until:
            self._snooze_until.pop(notice.id, None)
            notice.unread = True
            return False
        return True


def calendar_lead_notices(
    events: list[Any],
    now: datetime,
    *,
    leads_min: tuple[int, ...] = _DEFAULT_LEADS,
    already: set[str] | None = None,
    window_s: int = 45,
) -> list[Notice]:
    """Emit at most one lead per event per threshold, inside a short window.

    ``window_s`` keeps a 30s poll from missing a 15-minute mark and from
    re-firing for the rest of the hour.
    """
    done = already if already is not None else set()
    out: list[Notice] = []
    window = timedelta(seconds=max(15, int(window_s)))
    for ev in events:
        if bool(getattr(ev, "all_day", False)):
            continue
        starts = getattr(ev, "starts_at", None)
        summary = str(getattr(ev, "summary", "") or "").strip()
        event_id = str(
            getattr(ev, "id", None)
            or getattr(ev, "event_id", None)
            or getattr(ev, "raw_id", None)
            or summary
        )
        if starts is None or not summary or not event_id:
            continue
        start_dt = starts
        if start_dt.tzinfo is None and now.tzinfo is not None:
            start_dt = start_dt.replace(tzinfo=now.tzinfo)
        elif start_dt.tzinfo is not None and now.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=None)
        if start_dt < now - timedelta(minutes=2):
            continue
        for minutes in leads_min:
            lead_name = "start" if int(minutes) == 0 else f"t{int(minutes)}"
            key = f"{event_id}:{lead_name}"
            if key in done:
                continue
            target = start_dt if int(minutes) == 0 else start_dt - timedelta(minutes=int(minutes))
            delta = now - target
            if timedelta(0) <= delta <= window:
                remaining = start_dt - now
                mins_left = max(0, int(remaining.total_seconds() // 60))
                if int(minutes) == 0:
                    pill = f"{summary} · now"
                    body = f"{summary} is starting."
                    title = summary
                else:
                    pill = f"{summary} · {mins_left} min"
                    body = f"{summary} in {mins_left} minutes."
                    title = summary
                stamp = start_dt.strftime("%H:%M")
                out.append(
                    Notice(
                        id=uuid4().hex,
                        kind="calendar",
                        title=title,
                        body=f"{body} ({stamp})",
                        group_key=f"calendar:{event_id}",
                        created_at=now,
                        lead=lead_name,
                        data={
                            "event_id": event_id,
                            "pill": pill,
                            "starts_at": start_dt.isoformat(),
                        },
                    )
                )
    return out


def new_notice(
    *,
    kind: str,
    title: str,
    body: str = "",
    group_key: str = "",
    sticky: bool = False,
    voice_cue: str = "",
    data: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> Notice:
    stamp = now or datetime.now().astimezone()
    return Notice(
        id=uuid4().hex,
        kind=kind,
        title=title,
        body=body,
        group_key=group_key or f"{kind}:{uuid4().hex}",
        created_at=stamp,
        sticky=sticky,
        voice_cue=voice_cue,
        data=dict(data or {}),
    )
