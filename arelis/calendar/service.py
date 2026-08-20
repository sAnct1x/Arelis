"""One write path for the calendar tile and the agenda tool.

Google (or Outlook) is the source of truth. The SQLite cache is the read model.
Successful writes and syncs emit CALENDAR_CHANGED so the tile can reload.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any, Callable

from arelis.calendar.google_client import GoogleCalendarClient
from arelis.calendar.models import CachedEvent
from arelis.calendar.outlook_client import OutlookCalendarClient
from arelis.calendar.secrets import (
    CalendarSecrets,
    GoogleCalendarCreds,
    OutlookCalendarCreds,
    load_calendar_secrets,
)
from arelis.calendar.store import CalendarStore
from arelis.calendar.sync import sync_calendars
from arelis.core.bus import emit_nowait
from arelis.core.events import Event, EventType

log = logging.getLogger(__name__)

SYNC_TIMEOUT_S = 20.0

ClientFactory = Callable[[str], GoogleCalendarClient | OutlookCalendarClient]


class CalendarService:
    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        store: CalendarStore | None = None,
        secrets: CalendarSecrets | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._config = config or {}
        self._store = store
        self._secrets = secrets
        self._client_factory = client_factory

    @property
    def secrets(self) -> CalendarSecrets:
        return self._secrets or load_calendar_secrets()

    def default_provider(self) -> str:
        secrets = self.secrets
        if secrets.google and secrets.google.authorized:
            return "google"
        if secrets.outlook and secrets.outlook.authorized:
            return "outlook"
        raise RuntimeError(
            "No authorized calendar. Run: arelis --auth-calendar google"
        )

    def list_range(
        self,
        start_day: date,
        end_day: date,
        *,
        provider: str | None = None,
    ) -> list[CachedEvent]:
        store, owns = self._open_store()
        try:
            return store.list_range(start_day, end_day, provider=provider)
        finally:
            if owns:
                store.close()

    def get(self, event_id: str) -> CachedEvent | None:
        store, owns = self._open_store()
        try:
            return store.get(event_id)
        finally:
            if owns:
                store.close()

    async def sync(
        self,
        providers: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        store, owns = self._open_store()
        try:
            try:
                summary = await asyncio.wait_for(
                    sync_calendars(
                        self._config,
                        store=store,
                        secrets=self.secrets,
                        providers=providers,
                    ),
                    timeout=float(SYNC_TIMEOUT_S),
                )
            except asyncio.TimeoutError:
                log.warning("calendar sync timed out after %.1fs", SYNC_TIMEOUT_S)
                summary = {
                    "ok": False,
                    "providers": {},
                    "errors": ["sync timed out"],
                }
        finally:
            if owns:
                store.close()
        emit_nowait(
            Event(
                EventType.CALENDAR_CHANGED,
                {"action": "sync", "ok": bool(summary.get("ok"))},
            )
        )
        return summary

    async def create(
        self,
        *,
        summary: str,
        starts_at: datetime,
        ends_at: datetime | None = None,
        all_day: bool = False,
        location: str = "",
        description: str = "",
        provider: str | None = None,
        calendar_id: str | None = None,
    ) -> CachedEvent:
        which = (provider or self.default_provider()).strip().lower()
        client = self.client(which)
        ev = await client.create_event(
            summary=summary,
            starts_at=starts_at,
            ends_at=ends_at,
            all_day=all_day,
            location=location,
            description=description,
            calendar_id=calendar_id,
        )
        self._put(ev)
        emit_nowait(
            Event(
                EventType.CALENDAR_CHANGED,
                {"action": "create", "id": ev.id, "provider": ev.provider},
            )
        )
        return ev

    async def update(
        self,
        event_id: str,
        *,
        summary: str | None = None,
        starts_at: datetime | None = None,
        ends_at: datetime | None = None,
        all_day: bool | None = None,
        location: str | None = None,
        description: str | None = None,
        provider: str | None = None,
        calendar_id: str | None = None,
    ) -> CachedEvent:
        which, raw_id = _split_id(event_id, provider)
        if which not in {"google", "outlook"}:
            raise RuntimeError("Could not resolve provider; pass google or outlook.")
        client = self.client(which)
        ev = await client.update_event(
            raw_id,
            summary=summary,
            starts_at=starts_at,
            ends_at=ends_at,
            all_day=all_day,
            location=location,
            description=description,
            calendar_id=calendar_id,
        )
        self._put(ev)
        emit_nowait(
            Event(
                EventType.CALENDAR_CHANGED,
                {"action": "update", "id": ev.id, "provider": ev.provider},
            )
        )
        return ev

    async def delete(
        self,
        event_id: str,
        *,
        provider: str | None = None,
        calendar_id: str | None = None,
    ) -> None:
        which, raw_id = _split_id(event_id, provider)
        if which not in {"google", "outlook"}:
            raise RuntimeError("Could not resolve provider; pass google or outlook.")
        client = self.client(which)
        await client.delete_event(raw_id, calendar_id=calendar_id)
        store, owns = self._open_store()
        try:
            store.delete_id(event_id)
            store.delete_id(f"{which}:{raw_id}")
        finally:
            if owns:
                store.close()
        emit_nowait(
            Event(
                EventType.CALENDAR_CHANGED,
                {"action": "delete", "id": event_id, "provider": which},
            )
        )

    def client(self, provider: str) -> GoogleCalendarClient | OutlookCalendarClient:
        if self._client_factory is not None:
            return self._client_factory(provider)
        secrets = self.secrets
        cal_cfg = (self._config.get("tools") or {}).get("calendar") or {}
        if provider == "google":
            if secrets.google is None or not secrets.google.authorized:
                raise RuntimeError(
                    "Google Calendar not authorized. "
                    "Run: arelis --auth-calendar google"
                )
            creds = secrets.google
            override = str(cal_cfg.get("google_calendar_id") or "").strip()
            if override and override != creds.calendar_id:
                creds = GoogleCalendarCreds(
                    client_id=creds.client_id,
                    client_secret=creds.client_secret,
                    refresh_token=creds.refresh_token,
                    calendar_id=override,
                )
            return GoogleCalendarClient(creds)
        if secrets.outlook is None or not secrets.outlook.authorized:
            raise RuntimeError(
                "Outlook not authorized. Run: arelis --auth-calendar outlook"
            )
        creds = secrets.outlook
        override = str(cal_cfg.get("outlook_calendar_id") or "").strip()
        if override and override != creds.calendar_id:
            creds = OutlookCalendarCreds(
                client_id=creds.client_id,
                client_secret=creds.client_secret,
                refresh_token=creds.refresh_token,
                tenant=creds.tenant,
                calendar_id=override,
            )
        return OutlookCalendarClient(creds)

    def _put(self, ev: CachedEvent) -> None:
        store, owns = self._open_store()
        try:
            store.put(ev)
        finally:
            if owns:
                store.close()

    def _open_store(self) -> tuple[CalendarStore, bool]:
        if self._store is not None:
            return self._store, False
        return CalendarStore(), True


def _split_id(event_id: str, provider_hint: str | None) -> tuple[str, str]:
    hint = str(provider_hint or "").strip().lower()
    if ":" in event_id:
        prov, raw = event_id.split(":", 1)
        return prov.lower(), raw
    return hint, event_id
