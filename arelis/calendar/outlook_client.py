"""Microsoft Graph calendar via MSAL refresh + REST."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from arelis.calendar.models import CachedEvent
from arelis.calendar.secrets import OutlookCalendarCreds

log = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = ["Calendars.ReadWrite", "offline_access", "User.Read"]


class OutlookCalendarClient:
    def __init__(self, creds: OutlookCalendarCreds) -> None:
        self.creds = creds
        self._access: str | None = None

    async def access_token(self) -> str:
        if self._access:
            return self._access
        if not self.creds.refresh_token:
            raise RuntimeError(
                "Outlook not authorized. Run: arelis --auth-calendar outlook"
            )
        try:
            import msal
        except ImportError as exc:
            raise RuntimeError(
                "msal is required for Outlook. pip install msal"
            ) from exc

        app = msal.PublicClientApplication(
            self.creds.client_id,
            authority=f"https://login.microsoftonline.com/{self.creds.tenant}",
        )
        result = app.acquire_token_by_refresh_token(
            self.creds.refresh_token,
            scopes=SCOPES,
        )
        if not isinstance(result, dict) or "access_token" not in result:
            err = (result or {}).get("error_description") or (result or {}).get("error")
            log.warning("Outlook token refresh failed: %s", err)
            raise RuntimeError(
                f"Outlook token refresh failed: {err}. "
                "Re-run: arelis --auth-calendar outlook"
            )
        self._access = str(result["access_token"])
        return self._access

    def _events_url(self) -> str:
        cal = (self.creds.calendar_id or "").strip()
        if cal:
            return f"{GRAPH}/me/calendars/{quote(cal, safe='')}/events"
        return f"{GRAPH}/me/calendar/events"

    async def list_events(
        self,
        *,
        time_min: datetime,
        time_max: datetime,
        calendar_id: str | None = None,
    ) -> list[CachedEvent]:
        token = await self.access_token()
        # calendarView is better for range queries
        cal = (calendar_id or self.creds.calendar_id or "").strip()
        if cal:
            url = f"{GRAPH}/me/calendars/{quote(cal, safe='')}/calendarView"
        else:
            url = f"{GRAPH}/me/calendarView"
        params = {
            "startDateTime": _rfc3339(time_min),
            "endDateTime": _rfc3339(time_max),
            "$orderby": "start/dateTime",
            "$top": "250",
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.get(
                url,
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Prefer": 'outlook.timezone="UTC"',
                },
            )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Outlook list failed ({resp.status_code}): {resp.text[:240]}"
            )
        items = (resp.json() or {}).get("value") or []
        out: list[CachedEvent] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            ev = _parse_outlook_event(item, calendar_id=cal or "default")
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
        cal = (calendar_id or self.creds.calendar_id or "").strip()
        body = _outlook_body(
            summary=summary,
            starts_at=starts_at,
            ends_at=ends_at,
            all_day=all_day,
            location=location,
            description=description,
        )
        if cal:
            url = f"{GRAPH}/me/calendars/{quote(cal, safe='')}/events"
        else:
            url = f"{GRAPH}/me/events"
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
                f"Outlook create failed ({resp.status_code}): {resp.text[:240]}"
            )
        ev = _parse_outlook_event(resp.json(), calendar_id=cal or "default")
        if ev is None:
            raise RuntimeError("Outlook create returned an unreadable event")
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
        body: dict[str, Any] = {}
        if summary is not None:
            body["subject"] = summary
        if location is not None:
            body["location"] = {"displayName": location}
        if description is not None:
            body["body"] = {"contentType": "text", "content": description}
        if starts_at is not None:
            end = ends_at or starts_at
            use_all_day = bool(all_day) if all_day is not None else False
            body.update(
                _outlook_body(
                    summary=summary or "",
                    starts_at=starts_at,
                    ends_at=end,
                    all_day=use_all_day,
                    location=location or "",
                    description=description or "",
                )
            )
            if summary is None:
                body.pop("subject", None)
        url = f"{GRAPH}/me/events/{quote(event_id, safe='')}"
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
                f"Outlook update failed ({resp.status_code}): {resp.text[:240]}"
            )
        cal = (calendar_id or self.creds.calendar_id or "").strip() or "default"
        ev = _parse_outlook_event(resp.json(), calendar_id=cal)
        if ev is None:
            raise RuntimeError("Outlook update returned an unreadable event")
        return ev

    async def delete_event(
        self,
        event_id: str,
        *,
        calendar_id: str | None = None,
    ) -> None:
        del calendar_id  # Graph delete uses event id globally under /me/events
        token = await self.access_token()
        url = f"{GRAPH}/me/events/{quote(event_id, safe='')}"
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.delete(
                url,
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code not in {200, 204, 404}:
            raise RuntimeError(
                f"Outlook delete failed ({resp.status_code}): {resp.text[:240]}"
            )


def _rfc3339(dt: datetime) -> str:
    # Naive = local wall clock (same policy as Google / agenda._parse_dt).
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _outlook_body(
    *,
    summary: str,
    starts_at: datetime,
    ends_at: datetime | None,
    all_day: bool,
    location: str,
    description: str,
) -> dict[str, Any]:
    end = ends_at or (starts_at + timedelta(hours=1))
    body: dict[str, Any] = {"subject": summary}
    if location:
        body["location"] = {"displayName": location}
    if description:
        body["body"] = {"contentType": "text", "content": description}
    if all_day:
        body["isAllDay"] = True
        body["start"] = {
            "dateTime": starts_at.date().isoformat() + "T00:00:00",
            "timeZone": "UTC",
        }
        body["end"] = {
            "dateTime": (end.date() + timedelta(days=1)).isoformat() + "T00:00:00",
            "timeZone": "UTC",
        }
    else:
        body["isAllDay"] = False
        body["start"] = {
            "dateTime": starts_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "UTC",
        }
        body["end"] = {
            "dateTime": end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "UTC",
        }
    return body


def _parse_outlook_event(item: dict[str, Any], *, calendar_id: str) -> CachedEvent | None:
    raw_id = str(item.get("id") or "").strip()
    if not raw_id:
        return None
    start = item.get("start") or {}
    end = item.get("end") or {}
    all_day = bool(item.get("isAllDay"))
    try:
        starts_at = _parse_graph_dt(start)
        ends_at = _parse_graph_dt(end)
    except (TypeError, ValueError):
        return None
    loc = item.get("location") or {}
    loc_name = ""
    if isinstance(loc, dict):
        loc_name = str(loc.get("displayName") or "")
    body = item.get("body") or {}
    desc = ""
    if isinstance(body, dict):
        desc = str(body.get("content") or "")[:2000]
    return CachedEvent(
        id=f"outlook:{raw_id}",
        provider="outlook",
        calendar_id=calendar_id,
        summary=str(item.get("subject") or "(no title)"),
        starts_at=starts_at,
        ends_at=ends_at,
        all_day=all_day,
        location=loc_name,
        description=desc,
        etag=str(item.get("@odata.etag") or ""),
        raw_id=raw_id,
    )


def _parse_graph_dt(block: dict[str, Any]) -> datetime:
    raw = str(block.get("dateTime") or "").strip()
    if not raw:
        raise ValueError("missing dateTime")
    # Graph often returns without tz; Prefer header asked for UTC.
    if raw.endswith("Z"):
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if "+" in raw[10:] or raw.endswith("Z"):
        return datetime.fromisoformat(raw)
    return datetime.fromisoformat(raw).replace(tzinfo=UTC)
