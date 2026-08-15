"""Google Calendar API via OAuth refresh + REST (httpx)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from arelis.calendar.models import CachedEvent
from arelis.calendar.secrets import GoogleCalendarCreds

log = logging.getLogger(__name__)

GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_CAL_BASE = "https://www.googleapis.com/calendar/v3"
SCOPES = ("https://www.googleapis.com/auth/calendar",)


class GoogleCalendarClient:
    def __init__(self, creds: GoogleCalendarCreds) -> None:
        self.creds = creds
        self._access: str | None = None

    async def access_token(self) -> str:
        if self._access:
            return self._access
        if not self.creds.refresh_token:
            raise RuntimeError(
                "Google Calendar not authorized. Run: arelis --auth-calendar google"
            )
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                GOOGLE_TOKEN,
                data={
                    "client_id": self.creds.client_id,
                    "client_secret": self.creds.client_secret,
                    "refresh_token": self.creds.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        if resp.status_code >= 400:
            log.warning("Google token refresh failed: %s", resp.text[:300])
            raise RuntimeError(
                f"Google token refresh failed ({resp.status_code}). "
                "Re-run: arelis --auth-calendar google"
            )
        data = resp.json()
        self._access = str(data.get("access_token") or "")
        if not self._access:
            raise RuntimeError("Google token response missing access_token")
        return self._access

    async def list_events(
        self,
        *,
        time_min: datetime,
        time_max: datetime,
        calendar_id: str | None = None,
    ) -> list[CachedEvent]:
        token = await self.access_token()
        cal = calendar_id or self.creds.calendar_id or "primary"
        params = {
            "timeMin": _rfc3339(time_min),
            "timeMax": _rfc3339(time_max),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": "250",
        }
        url = f"{GOOGLE_CAL_BASE}/calendars/{quote(cal, safe='')}/events"
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Google list events failed ({resp.status_code}): {resp.text[:240]}"
            )
        items = (resp.json() or {}).get("items") or []
        out: list[CachedEvent] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            ev = _parse_google_event(item, calendar_id=cal)
            if ev:
                out.append(ev)
        return out

    async def create_event(
        self,
        *,
        summary: str,
        starts_at: datetime,
        ends_at: datetime | None = None,
        all_day: bool = False,
        location: str = "",
        description: str = "",
        calendar_id: str | None = None,
    ) -> CachedEvent:
        token = await self.access_token()
        cal = calendar_id or self.creds.calendar_id or "primary"
        body = _google_body(
            summary=summary,
            starts_at=starts_at,
            ends_at=ends_at,
            all_day=all_day,
            location=location,
            description=description,
        )
        url = f"{GOOGLE_CAL_BASE}/calendars/{quote(cal, safe='')}/events"
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                url,
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Google create failed ({resp.status_code}): {resp.text[:240]}"
            )
        ev = _parse_google_event(resp.json(), calendar_id=cal)
        if ev is None:
            raise RuntimeError("Google create returned an unreadable event")
        return ev

    async def update_event(
        self,
        event_id: str,
        *,
        summary: str | None = None,
        starts_at: datetime | None = None,
        ends_at: datetime | None = None,
        all_day: bool | None = None,
        location: str | None = None,
        description: str | None = None,
        calendar_id: str | None = None,
    ) -> CachedEvent:
        token = await self.access_token()
        cal = calendar_id or self.creds.calendar_id or "primary"
        # Patch: fetch not required if we send fields; Google accepts partial.
        body: dict[str, Any] = {}
        if summary is not None:
            body["summary"] = summary
        if location is not None:
            body["location"] = location
        if description is not None:
            body["description"] = description
        if starts_at is not None:
            end = ends_at or starts_at
            use_all_day = bool(all_day) if all_day is not None else False
            body.update(
                _google_body(
                    summary=summary or "",
                    starts_at=starts_at,
                    ends_at=end,
                    all_day=use_all_day,
                    location=location or "",
                    description=description or "",
                )
            )
            if summary is None:
                body.pop("summary", None)
        url = (
            f"{GOOGLE_CAL_BASE}/calendars/{quote(cal, safe='')}/events/"
            f"{quote(event_id, safe='')}"
        )
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.patch(
                url,
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Google update failed ({resp.status_code}): {resp.text[:240]}"
            )
        ev = _parse_google_event(resp.json(), calendar_id=cal)
        if ev is None:
            raise RuntimeError("Google update returned an unreadable event")
        return ev

    async def delete_event(
        self,
        event_id: str,
        *,
        calendar_id: str | None = None,
    ) -> None:
        token = await self.access_token()
        cal = calendar_id or self.creds.calendar_id or "primary"
        url = (
            f"{GOOGLE_CAL_BASE}/calendars/{quote(cal, safe='')}/events/"
            f"{quote(event_id, safe='')}"
        )
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.delete(
                url,
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code not in {200, 204, 410}:
            raise RuntimeError(
                f"Google delete failed ({resp.status_code}): {resp.text[:240]}"
            )


def _rfc3339(dt: datetime) -> str:
    # Naive = local wall clock (agenda._parse_dt). Never invent UTC for bare ISO.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _google_body(
    *,
    summary: str,
    starts_at: datetime,
    ends_at: datetime | None,
    all_day: bool,
    location: str,
    description: str,
) -> dict[str, Any]:
    end = ends_at or starts_at
    body: dict[str, Any] = {"summary": summary}
    if location:
        body["location"] = location
    if description:
        body["description"] = description
    if all_day:
        body["start"] = {"date": starts_at.date().isoformat()}
        # Google all-day end is exclusive.
        from datetime import timedelta

        body["end"] = {"date": (end.date() + timedelta(days=1)).isoformat()}
    else:
        body["start"] = {"dateTime": _rfc3339(starts_at)}
        body["end"] = {"dateTime": _rfc3339(end)}
    return body


def _parse_google_event(item: dict[str, Any], *, calendar_id: str) -> CachedEvent | None:
    raw_id = str(item.get("id") or "").strip()
    if not raw_id:
        return None
    start = item.get("start") or {}
    end = item.get("end") or {}
    all_day = "date" in start and "dateTime" not in start
    try:
        if all_day:
            starts_at = datetime.fromisoformat(str(start["date"])).replace(
                tzinfo=datetime.now().astimezone().tzinfo
            )
            ends_at = datetime.fromisoformat(str(end.get("date") or start["date"]))
            ends_at = ends_at.replace(tzinfo=starts_at.tzinfo)
        else:
            starts_at = datetime.fromisoformat(
                str(start.get("dateTime") or "").replace("Z", "+00:00")
            )
            ends_raw = str(end.get("dateTime") or "").replace("Z", "+00:00")
            ends_at = datetime.fromisoformat(ends_raw) if ends_raw else None
    except (TypeError, ValueError, KeyError):
        return None
    return CachedEvent(
        id=f"google:{raw_id}",
        provider="google",
        calendar_id=calendar_id,
        summary=str(item.get("summary") or "(no title)"),
        starts_at=starts_at,
        ends_at=ends_at,
        all_day=all_day,
        location=str(item.get("location") or ""),
        description=str(item.get("description") or "")[:2000],
        etag=str(item.get("etag") or ""),
        raw_id=raw_id,
    )
