"""Agenda tool — local cache + Google/Outlook APIs (ICS fallback).

Read actions are free. create/update/delete require Allow and never batch.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from arelis.briefing.calendar import (
    CalendarEvent,
    format_agenda_section,
    load_agenda,
    resolve_calendar_path,
)
from arelis.calendar.models import CachedEvent
from arelis.calendar.secrets import load_calendar_secrets
from arelis.calendar.service import CalendarService
from arelis.calendar.store import CalendarStore
from arelis.tools.base import ToolResult

log = logging.getLogger(__name__)

_MAX_RANGE_DAYS = 31
AGENDA_WRITE_ACTIONS = frozenset({"create", "update", "delete"})
_READ_ACTIONS = frozenset({"today", "tomorrow", "range", "list", "sync"})


def _local_now() -> datetime:
    return datetime.now().astimezone()


class AgendaTool:
    name = "agenda"
    description = (
        "Calendar: open or close the Arelis calendar tile; list today's/"
        "tomorrow's events or a date range; sync from Google/Outlook; "
        "create/update/delete events (writes need Allow). Never invent "
        "meetings — list first and cite the tool (time, title, place, "
        "one-line notes). Never ask the user for a Google event id; delete "
        "by title/time. provider=google|outlook|all|ics. action=open shows "
        "the local tile; action=close hides it — do not use the browser "
        "calendar alias unless they asked for the website."
    )
    # Registered as read; write actions gated in ToolRegistry.needs_confirm.
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "today",
                    "tomorrow",
                    "range",
                    "list",
                    "sync",
                    "open",
                    "close",
                    "create",
                    "update",
                    "delete",
                ],
                "description": (
                    "open/close show or hide the Arelis calendar tile; "
                    "today/tomorrow/range/list read; sync refreshes Google/Outlook "
                    "cache (or provider=ics writes local ICS from secrets URL); "
                    "create/update/delete change cloud calendars (Allow required)."
                ),
            },
            "start": {
                "type": "string",
                "description": "YYYY-MM-DD for range, or ISO datetime for create/update.",
            },
            "end": {
                "type": "string",
                "description": "YYYY-MM-DD for range, or ISO datetime for create/update.",
            },
            "provider": {
                "type": "string",
                "enum": ["all", "google", "outlook", "ics"],
                "description": "Which source (default all for reads; required for writes).",
            },
            "summary": {
                "type": "string",
                "description": (
                    "Event title for create/update, or the title to match on "
                    "delete when event_id is unknown."
                ),
            },
            "event_id": {
                "type": "string",
                "description": (
                    "Cached or provider event id for update/delete. Optional "
                    "for delete — prefer summary (and start) and the tool "
                    "resolves the id. Never ask the user to paste a Google id."
                ),
            },
            "keep": {
                "type": "integer",
                "description": (
                    "On delete-by-title: how many matching duplicates to keep "
                    "(1 = delete extras). Default 1 when several share title+time."
                ),
            },
            "all_day": {
                "type": "boolean",
                "description": "All-day event (create/update).",
            },
            "location": {"type": "string", "description": "Optional location."},
            "description": {"type": "string", "description": "Optional notes."},
            "calendar_id": {
                "type": "string",
                "description": "Optional calendar id override.",
            },
        },
        "required": ["action"],
    }

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip().lower()
        if (
            action in _READ_ACTIONS
            or action in AGENDA_WRITE_ACTIONS
            or action in {"open", "close"}
        ):
            pass
        else:
            return ToolResult(
                ok=False,
                output=(
                    "Unknown action. Use open, close, today, tomorrow, range, "
                    "list, sync, create, update, or delete."
                ),
            )
        if action == "open":
            return await self._open()
        if action == "close":
            return await self._close()
        if action == "sync":
            return await self._sync(kwargs)
        if action in {"today", "tomorrow", "range", "list"}:
            return await self._list(action, kwargs)
        if action == "create":
            return await self._create(kwargs)
        if action == "update":
            return await self._update(kwargs)
        if action == "delete":
            return await self._delete(kwargs)
        return ToolResult(ok=False, output=f"Unknown action: {action}")

    async def _open(self) -> ToolResult:
        return ToolResult(
            ok=True,
            output="Opened the Arelis calendar.",
            data={"open": True},
        )

    async def _close(self) -> ToolResult:
        return ToolResult(
            ok=True,
            output="Closed the Arelis calendar.",
            data={"close": True},
        )

    async def _sync(self, kwargs: dict[str, Any]) -> ToolResult:
        provider = str(kwargs.get("provider") or "all").strip().lower()
        if provider == "ics":
            from arelis.briefing.ics_sync import sync_ics_from_url

            summary = await sync_ics_from_url(self._config)
            if summary.get("missing_secret"):
                return ToolResult(
                    ok=True,
                    output=str(summary.get("error") or "ICS URL not configured."),
                    data=summary,
                )
            if not summary.get("ok"):
                return ToolResult(
                    ok=False,
                    output=f"ICS sync failed: {summary.get('error') or 'unknown'}",
                    data=summary,
                )
            path = summary.get("path") or resolve_calendar_path(self._config)
            return ToolResult(
                ok=True,
                output=(
                    f"ICS sync: wrote {summary.get('bytes', 0)} bytes to {path}.\n"
                    "Use agenda(action=today) to list events from the local file."
                ),
                data=summary,
            )
        providers: tuple[str, ...]
        if provider in {"google", "outlook"}:
            providers = (provider,)
        else:
            providers = ("google", "outlook")
        summary = await CalendarService(self._config).sync(providers=providers)
        lines = ["Calendar sync:"]
        for name, info in (summary.get("providers") or {}).items():
            if info.get("ok"):
                lines.append(f"- {name}: {info.get('count', 0)} events cached")
            else:
                lines.append(f"- {name}: FAIL — {info.get('error')}")
        for err in summary.get("errors") or []:
            if not any(err.startswith(f"{p}:") for p in (summary.get("providers") or {})):
                lines.append(f"- {err}")
        return ToolResult(
            ok=bool(summary.get("ok")),
            output="\n".join(lines),
            data=summary,
        )

    async def _list(self, action: str, kwargs: dict[str, Any]) -> ToolResult:
        now = _local_now()
        try:
            begin, finish = self._window(action, kwargs, now=now)
        except ValueError as exc:
            return ToolResult(ok=False, output=str(exc))

        provider = str(kwargs.get("provider") or "all").strip().lower()
        secrets = load_calendar_secrets()
        store = CalendarStore()
        try:
            # Soft sync when authorized so reads stay fresh without a separate call.
            if secrets.any_authorized() and provider != "ics":
                try:
                    await CalendarService(self._config, store=store).sync(
                        providers=(
                            (provider,)
                            if provider in {"google", "outlook"}
                            else ("google", "outlook")
                        ),
                    )
                except Exception as exc:
                    log.warning("Background agenda sync failed: %s", exc)

            cached = store.list_range(
                begin,
                finish,
                provider=None if provider in {"all", "ics"} else provider,
            )
        finally:
            store.close()

        if cached and provider != "ics":
            events = [_cached_as_briefing(ev) for ev in cached]
            body = format_agenda_section(events, now=now)
            sources = sorted({ev.provider for ev in cached})
            output = (
                f"{body}\n\nSource: cache ({', '.join(sources)})\n"
                "Summarize these events for the user (time, title, place, "
                "one-line notes). Do not invent events. Do not quote "
                "Google/Outlook event ids."
            )
            return ToolResult(
                ok=True,
                output=output,
                data={
                    "action": action,
                    "start": begin.isoformat(),
                    "end": finish.isoformat(),
                    "count": len(cached),
                    "source": "cache",
                    "events": [ev.as_dict() for ev in cached],
                },
            )

        # ICS fallback
        path = resolve_calendar_path(self._config)
        if not path.is_file():
            return ToolResult(
                ok=True,
                output=(
                    "No events. Authorize Google/Outlook "
                    "(`arelis --auth-calendar …`) or add data/calendar.ics.\n"
                    f"ICS path: {path}"
                ),
                data={
                    "action": action,
                    "events": [],
                    "count": 0,
                    "source": str(path),
                    "missing": True,
                },
            )
        ics_events = load_agenda(path, now=now, start_day=begin, end_day=finish)
        body = format_agenda_section(ics_events, now=now)
        return ToolResult(
            ok=True,
            output=(
                f"{body}\n\nSource: {path} (ICS fallback)\n"
                "Summarize these events for the user (time, title, place, "
                "one-line notes). Do not invent events. Do not quote event ids."
            ),
            data={
                "action": action,
                "start": begin.isoformat(),
                "end": finish.isoformat(),
                "count": len(ics_events),
                "source": str(path),
                "events": [
                    {
                        "summary": ev.summary,
                        "starts_at": ev.starts_at.isoformat(),
                        "all_day": ev.all_day,
                        "location": ev.location,
                        "description": ev.description,
                        "provider": "ics",
                    }
                    for ev in ics_events
                ],
            },
        )

    async def _create(self, kwargs: dict[str, Any]) -> ToolResult:
        provider = str(kwargs.get("provider") or "").strip().lower()
        if provider not in {"google", "outlook"}:
            return ToolResult(
                ok=False,
                output="create requires provider=google or provider=outlook.",
            )
        summary = str(kwargs.get("summary") or "").strip()
        if not summary:
            return ToolResult(ok=False, output="create requires summary.")
        try:
            starts_at = _parse_dt(kwargs.get("start"), field="start")
        except ValueError as exc:
            return ToolResult(ok=False, output=str(exc))
        ends_at = None
        if kwargs.get("end"):
            try:
                ends_at = _parse_dt(kwargs.get("end"), field="end")
            except ValueError as exc:
                return ToolResult(ok=False, output=str(exc))
        all_day = bool(kwargs.get("all_day"))
        location = str(kwargs.get("location") or "").strip()
        description = str(kwargs.get("description") or "").strip()
        calendar_id = str(kwargs.get("calendar_id") or "").strip() or None

        # Idempotency: refuse a second POST for the same title+start (S11).
        store = CalendarStore()
        try:
            day = starts_at.date()
            cached = store.list_range(day, day, provider=provider)
            for hit in cached:
                if _same_event(summary, starts_at, hit):
                    return ToolResult(
                        ok=True,
                        output=(
                            f"Already on {provider}: {hit.summary} @ "
                            f"{hit.starts_at.isoformat()} — not creating a duplicate."
                        ),
                        data={
                            "event": hit.as_dict(),
                            "action": "create",
                            "duplicate": True,
                        },
                    )
        finally:
            store.close()

        try:
            svc = CalendarService(self._config, client_factory=self._client)
            ev = await svc.create(
                summary=summary,
                starts_at=starts_at,
                ends_at=ends_at,
                all_day=all_day,
                location=location,
                description=description,
                provider=provider,
                calendar_id=calendar_id,
            )
        except Exception as exc:
            return ToolResult(ok=False, output=f"create failed: {exc}")
        return ToolResult(
            ok=True,
            output=(
                f"Created on {provider}: {ev.summary} @ {ev.starts_at.isoformat()}"
            ),
            data={"event": ev.as_dict(), "action": "create"},
        )

    async def _update(self, kwargs: dict[str, Any]) -> ToolResult:
        event_id = str(kwargs.get("event_id") or "").strip()
        if not event_id:
            return ToolResult(ok=False, output="update requires event_id.")
        provider, _raw_id = _split_id(event_id, kwargs.get("provider"))
        if provider not in {"google", "outlook"}:
            return ToolResult(
                ok=False,
                output="Could not resolve provider; pass provider=google|outlook.",
            )
        starts_at = None
        ends_at = None
        if kwargs.get("start"):
            try:
                starts_at = _parse_dt(kwargs.get("start"), field="start")
            except ValueError as exc:
                return ToolResult(ok=False, output=str(exc))
        if kwargs.get("end"):
            try:
                ends_at = _parse_dt(kwargs.get("end"), field="end")
            except ValueError as exc:
                return ToolResult(ok=False, output=str(exc))
        try:
            svc = CalendarService(self._config, client_factory=self._client)
            ev = await svc.update(
                event_id,
                summary=str(kwargs["summary"]).strip()
                if kwargs.get("summary") is not None
                else None,
                starts_at=starts_at,
                ends_at=ends_at,
                all_day=bool(kwargs["all_day"]) if "all_day" in kwargs else None,
                location=str(kwargs.get("location")).strip()
                if kwargs.get("location") is not None
                else None,
                description=str(kwargs.get("description")).strip()
                if kwargs.get("description") is not None
                else None,
                provider=provider,
                calendar_id=str(kwargs.get("calendar_id") or "").strip() or None,
            )
        except Exception as exc:
            return ToolResult(ok=False, output=f"update failed: {exc}")
        return ToolResult(
            ok=True,
            output=f"Updated on {provider}: {ev.summary} (id={ev.id})",
            data={"event": ev.as_dict(), "action": "update"},
        )

    async def _delete(self, kwargs: dict[str, Any]) -> ToolResult:
        event_id = str(kwargs.get("event_id") or "").strip()
        if not event_id:
            return await self._delete_resolved(kwargs)
        return await self._delete_one(
            event_id,
            provider_hint=kwargs.get("provider"),
            calendar_id=str(kwargs.get("calendar_id") or "").strip() or None,
        )

    async def _delete_resolved(self, kwargs: dict[str, Any]) -> ToolResult:
        """Delete by title/time. Never require the user to paste a Google id."""
        needle = str(
            kwargs.get("summary") or kwargs.get("query") or ""
        ).strip()
        keep_raw = kwargs.get("keep")
        try:
            keep = int(keep_raw) if keep_raw is not None and str(keep_raw) != "" else None
        except (TypeError, ValueError):
            keep = None
        matches = await self._find_events(kwargs)
        if needle:
            key = needle.casefold()
            matches = [
                ev
                for ev in matches
                if key in (ev.summary or "").casefold()
                or key in (ev.description or "").casefold()
            ]
        start_raw = str(kwargs.get("start") or "").strip()
        if start_raw:
            try:
                when = _parse_dt(start_raw, field="start")
                has_clock = bool(
                    re.search(r"T\d{2}:|\bat\s+\d", start_raw, re.I)
                ) or bool(when.hour or when.minute)
                if has_clock:
                    matches = [
                        ev
                        for ev in matches
                        if ev.starts_at.date() == when.date()
                        and ev.starts_at.hour == when.hour
                    ]
            except ValueError:
                pass
        if not matches:
            return ToolResult(
                ok=False,
                output=(
                    "[fail:agenda] No matching calendar events to delete. "
                    "Call agenda(action=list) and delete by title/time — "
                    "do not ask the user for a Google event id."
                ),
                data={"action": "delete", "count": 0},
            )
        groups: dict[tuple[str, str], list] = {}
        for ev in matches:
            stamp = ev.starts_at.replace(second=0, microsecond=0).isoformat()
            groups.setdefault(((ev.summary or "").casefold(), stamp), []).append(ev)
        # Several copies of the same title+time → keep one unless keep=0.
        dup_groups = [rows for rows in groups.values() if len(rows) > 1]
        unique_slots = len(groups)
        if unique_slots > 1 and keep is None:
            lines = [
                "Several different events match. Say which time/title to "
                "delete (or 'the duplicates'). Do not ask for a Google id."
            ]
            for ev in matches:
                when = ev.starts_at.strftime("%a %I:%M %p").lstrip("0")
                lines.append(f"- {when} — {ev.summary} ({ev.provider})")
            return ToolResult(
                ok=False,
                output="\n".join(lines),
                data={
                    "action": "delete",
                    "ambiguous": True,
                    "events": [ev.as_dict() for ev in matches],
                },
            )
        to_delete: list = []
        if dup_groups and keep is None:
            keep = 1
        if keep is not None:
            for rows in groups.values():
                rows_sorted = sorted(rows, key=lambda e: e.id)
                to_delete.extend(rows_sorted[keep:])
        else:
            to_delete = list(matches)
        if not to_delete:
            return ToolResult(
                ok=True,
                output="Nothing extra to delete — already a single copy.",
                data={"action": "delete", "count": 0, "kept": len(matches)},
            )
        deleted: list[str] = []
        errors: list[str] = []
        for ev in to_delete:
            result = await self._delete_one(
                ev.id,
                provider_hint=ev.provider,
                calendar_id=ev.calendar_id or None,
            )
            if result.ok:
                deleted.append(ev.id)
            else:
                errors.append(result.output)
        if not deleted:
            return ToolResult(
                ok=False,
                output="; ".join(errors) or "delete failed",
                data={"action": "delete", "count": 0},
            )
        titles = ", ".join(sorted({ev.summary for ev in to_delete if ev.summary}))
        extra = f" Errors: {'; '.join(errors)}" if errors else ""
        return ToolResult(
            ok=True,
            output=(
                f"Deleted {len(deleted)} event(s) on calendar ({titles})."
                f"{extra}"
            ),
            data={
                "action": "delete",
                "count": len(deleted),
                "event_ids": deleted,
            },
        )

    async def _find_events(self, kwargs: dict[str, Any]) -> list:
        now = _local_now()
        provider = str(kwargs.get("provider") or "all").strip().lower()
        start_raw = str(kwargs.get("start") or "").strip()
        if start_raw:
            try:
                when = _parse_dt(start_raw, field="start")
                begin, finish = when.date(), when.date()
            except ValueError:
                begin, finish = now.date(), now.date() + timedelta(days=14)
        else:
            begin, finish = now.date(), now.date() + timedelta(days=14)
        secrets = load_calendar_secrets()
        store = CalendarStore()
        try:
            if secrets.any_authorized() and provider != "ics":
                try:
                    await CalendarService(self._config, store=store).sync(
                        providers=(
                            (provider,)
                            if provider in {"google", "outlook"}
                            else ("google", "outlook")
                        ),
                    )
                except Exception as exc:
                    log.warning("Background agenda sync failed: %s", exc)
            return store.list_range(
                begin,
                finish,
                provider=None if provider in {"all", "ics"} else provider,
            )
        finally:
            store.close()

    async def _delete_one(
        self,
        event_id: str,
        *,
        provider_hint: Any = None,
        calendar_id: str | None = None,
    ) -> ToolResult:
        provider, raw_id = _split_id(event_id, provider_hint)
        if provider not in {"google", "outlook"}:
            return ToolResult(
                ok=False,
                output="Could not resolve provider; pass provider=google|outlook.",
            )
        try:
            svc = CalendarService(self._config, client_factory=self._client)
            await svc.delete(
                event_id, provider=provider, calendar_id=calendar_id
            )
        except Exception as exc:
            return ToolResult(ok=False, output=f"delete failed: {exc}")
        return ToolResult(
            ok=True,
            output=f"Deleted on {provider}: {raw_id}",
            data={"action": "delete", "event_id": event_id, "provider": provider},
        )

    def _client(self, provider: str):
        return CalendarService(self._config).client(provider)

    def _window(
        self,
        action: str,
        kwargs: dict[str, Any],
        *,
        now: datetime,
    ) -> tuple[date, date]:
        today = now.date()
        if action == "today" and not kwargs.get("start"):
            return today, today
        if action == "list" and not kwargs.get("start") and not kwargs.get("end"):
            return today, today + timedelta(days=7)
        if action == "tomorrow":
            day = today + timedelta(days=1)
            return day, day
        if action in {"range", "list"}:
            if action == "range" and not kwargs.get("start"):
                raise ValueError("action=range requires start=YYYY-MM-DD.")
            start = _parse_iso_date(
                kwargs.get("start") or today.isoformat(), field="start"
            )
            end = _parse_iso_date(
                kwargs.get("end") or kwargs.get("start") or today.isoformat(),
                field="end",
            )
            if end < start:
                start, end = end, start
            span = (end - start).days + 1
            if span > _MAX_RANGE_DAYS:
                raise ValueError(
                    f"Range too long ({span} days). Cap is {_MAX_RANGE_DAYS} days."
                )
            return start, end
        return today, today


def _cached_as_briefing(ev: CachedEvent) -> CalendarEvent:
    return CalendarEvent(
        starts_at=ev.starts_at,
        summary=ev.summary,
        all_day=ev.all_day,
        location=ev.location or "",
        description=ev.description or "",
        event_id=ev.id,
    )


def _split_id(event_id: str, provider_hint: Any) -> tuple[str, str]:
    hint = str(provider_hint or "").strip().lower()
    if ":" in event_id:
        prov, raw = event_id.split(":", 1)
        return prov.lower(), raw
    return hint, event_id


def _parse_iso_date(raw: Any, *, field: str) -> date:
    text = str(raw or "").strip()
    if not text:
        raise ValueError(f"action=range requires {field}=YYYY-MM-DD.")
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError(f"Invalid {field} {text!r}; use YYYY-MM-DD.") from exc


_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_WEEKDAYS = (
    "monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    "mon|tue|wed|thu|fri|sat|sun"
)
_NAMED_DT = re.compile(
    rf"(?ix)(?:(?:{_WEEKDAYS})\s+)?"
    r"(?P<month>january|february|march|april|may|june|july|august|"
    r"september|october|november|december|jan|feb|mar|apr|jun|jul|"
    r"aug|sep|sept|oct|nov|dec)\s+"
    r"(?P<day>\d{1,2}),?\s+(?P<year>\d{4})"
    r"(?:\s+at)?\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?"
    r"(?:\s*(?P<ampm>am|pm))?"
)
_RELATIVE_DT = re.compile(
    r"(?ix)\b(?P<when>today|tomorrow)\b(?:\s+at)?\s+"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?(?:\s*(?P<ampm>am|pm))?"
)
_ISO_SPACE_DT = re.compile(
    r"(?ix)(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})[ T]"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?"
    r"(?:\s*(?P<ampm>am|pm))?"
)


def _hour_24(hour: int, ampm: str) -> int:
    stamp = (ampm or "").strip().lower()
    if stamp == "am":
        return 0 if hour == 12 else hour
    if stamp == "pm":
        return hour if hour == 12 else hour + 12
    return hour


def _from_parts(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int = 0,
    ampm: str = "",
) -> datetime:
    return datetime(
        year,
        month,
        day,
        _hour_24(hour, ampm),
        minute,
        second,
        tzinfo=_local_now().tzinfo,
    )


def _parse_natural_dt(text: str) -> datetime | None:
    """Best-effort wall-clock parse when the model skips ISO."""
    raw = (text or "").strip()
    named = _NAMED_DT.search(raw)
    if named:
        month = _MONTHS[named.group("month").lower()]
        return _from_parts(
            int(named.group("year")),
            month,
            int(named.group("day")),
            int(named.group("hour")),
            int(named.group("minute") or 0),
            ampm=named.group("ampm") or "",
        )
    spaced = _ISO_SPACE_DT.fullmatch(raw)
    if spaced:
        return _from_parts(
            int(spaced.group("year")),
            int(spaced.group("month")),
            int(spaced.group("day")),
            int(spaced.group("hour")),
            int(spaced.group("minute")),
            int(spaced.group("second") or 0),
            ampm=spaced.group("ampm") or "",
        )
    relative = _RELATIVE_DT.search(raw)
    if relative:
        now = _local_now()
        day = now.date()
        if relative.group("when").lower() == "tomorrow":
            day = day + timedelta(days=1)
        return _from_parts(
            day.year,
            day.month,
            day.day,
            int(relative.group("hour")),
            int(relative.group("minute") or 0),
            ampm=relative.group("ampm") or "",
        )
    return None


def _parse_dt(raw: Any, *, field: str) -> datetime:
    """Parse ISO date/datetime; naive clock times are local, never UTC.

    Models often emit `2026-08-09T23:00:00` meaning 11pm on the user's wall
    clock. Treating that as UTC (old Google path) shifted Eastern events to
    19:00 and helped produce the S11 duplicates at the wrong hour.
    Natural phrases ("Monday September 7, 2026 at 10:15 AM", "tomorrow 3pm")
    used to fail create and then refuse with a calendar-reading warrant.
    """
    text = str(raw or "").strip()
    if not text:
        raise ValueError(f"{field} is required (ISO date or datetime).")
    try:
        if len(text) == 10:
            d = date.fromisoformat(text)
            return datetime(d.year, d.month, d.day, tzinfo=_local_now().tzinfo)
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_local_now().tzinfo)
        return dt
    except ValueError:
        parsed = _parse_natural_dt(text)
        if parsed is not None:
            return parsed
        raise ValueError(f"Invalid {field} {text!r}; use ISO date/datetime.") from None


def _same_event(a_summary: str, a_start: datetime, b: Any, *, skew_s: float = 60.0) -> bool:
    """True when cache row matches title + start within skew (idempotency)."""
    other_sum = str(getattr(b, "summary", "") or "").strip().casefold()
    if other_sum != a_summary.strip().casefold():
        return False
    other_start = getattr(b, "starts_at", None)
    if not isinstance(other_start, datetime):
        return False
    left = a_start if a_start.tzinfo else a_start.replace(tzinfo=_local_now().tzinfo)
    right = (
        other_start
        if other_start.tzinfo
        else other_start.replace(tzinfo=_local_now().tzinfo)
    )
    try:
        return abs((left - right).total_seconds()) <= skew_s
    except Exception:
        return False
