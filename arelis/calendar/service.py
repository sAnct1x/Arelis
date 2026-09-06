"""One write path for the calendar tile and the agenda tool.

Local SQLite is always writable. Google or Outlook is the cloud copy:
creates land locally first when nothing is authorized, then a background
push (no model turn) ships pending rows after OAuth. Successful writes
and syncs emit CALENDAR_CHANGED so the tile can reload.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any
from uuid import uuid4

from arelis.calendar.google_client import GoogleCalendarClient
from arelis.calendar.models import CachedEvent, same_event_slot
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
        return "local"

    def _authorized(self, provider: str) -> bool:
        if self._client_factory is not None and provider in {"google", "outlook"}:
            return True
        secrets = self.secrets
        if provider == "google":
            return bool(secrets.google and secrets.google.authorized)
        if provider == "outlook":
            return bool(secrets.outlook and secrets.outlook.authorized)
        return False

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
        pushed: dict[str, Any] = {}
        try:
            try:
                pushed = await self.push_pending(store=store)
                summary = await asyncio.wait_for(
                    sync_calendars(
                        self._config,
                        store=store,
                        secrets=self.secrets,
                        providers=providers,
                    ),
                    timeout=float(SYNC_TIMEOUT_S),
                )
            except TimeoutError:
                log.warning("calendar sync timed out after %.1fs", SYNC_TIMEOUT_S)
                summary = {
                    "ok": False,
                    "providers": {},
                    "errors": ["sync timed out"],
                }
        finally:
            if owns:
                store.close()
        summary["pushed"] = int((pushed or {}).get("pushed") or 0)
        if not self._authorized("google") and not self._authorized("outlook"):
            leftover = [
                err
                for err in (summary.get("errors") or [])
                if "No authorized calendar providers" not in str(err)
            ]
            summary["errors"] = leftover
            if not leftover:
                summary["ok"] = True
        emit_nowait(
            Event(
                EventType.CALENDAR_CHANGED,
                {"action": "sync", "ok": bool(summary.get("ok"))},
            )
        )
        return summary

    async def push_pending(
        self, *, store: CalendarStore | None = None
    ) -> dict[str, Any]:
        """Ship local pending events to the first authorized cloud. No model."""
        dest = self.default_provider()
        if dest == "local":
            if self._authorized("google"):
                dest = "google"
            elif self._authorized("outlook"):
                dest = "outlook"
            else:
                return {"ok": True, "pushed": 0, "skipped": True}
        if store is not None:
            cache, owns = store, False
        else:
            cache, owns = self._open_store()
        pushed = 0
        errors: list[str] = []
        try:
            pending = cache.list_pending()
            if not pending:
                return {"ok": True, "pushed": 0}
            client = self.client(dest)
            for ev in pending:
                try:
                    twin = self._slot_in_store(
                        cache, ev.summary, ev.starts_at, skip_id=ev.id
                    )
                    if twin is not None and twin.provider == dest:
                        cache.delete_id(ev.id)
                        pushed += 1
                        continue
                    remote = await client.create_event(
                        summary=ev.summary,
                        starts_at=ev.starts_at,
                        ends_at=ev.ends_at,
                        all_day=ev.all_day,
                        location=ev.location,
                        description=ev.description,
                    )
                    cache.put(remote)
                    cache.delete_id(ev.id)
                    pushed += 1
                except Exception as exc:
                    log.warning("pending calendar push failed: %s", exc)
                    errors.append(str(exc))
                    cache.mark_sync_state(ev.id, "failed")
        finally:
            if owns:
                cache.close()
        if pushed:
            emit_nowait(
                Event(
                    EventType.CALENDAR_CHANGED,
                    {"action": "push", "pushed": pushed, "provider": dest},
                )
            )
        return {"ok": not errors, "pushed": pushed, "errors": errors}

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
        existing = self._find_slot(summary, starts_at)
        if existing is not None:
            if existing.provider in {"google", "outlook"} and existing.sync_state != "failed":
                return existing
            if (
                existing.provider == "local"
                and which in {"google", "outlook"}
                and self._authorized(which)
            ):
                return await self._promote_pending(
                    existing, dest=which, calendar_id=calendar_id
                )
            if existing.provider == "local":
                return existing
        if which not in {"google", "outlook"} or not self._authorized(which):
            return self._create_local(
                summary=summary,
                starts_at=starts_at,
                ends_at=ends_at,
                all_day=all_day,
                location=location,
                description=description,
            )
        client = self.client(which)
        try:
            ev = await client.create_event(
                summary=summary,
                starts_at=starts_at,
                ends_at=ends_at,
                all_day=all_day,
                location=location,
                description=description,
                calendar_id=calendar_id,
            )
        except Exception as exc:
            log.warning(
                "cloud calendar create failed (%s); saving locally", exc
            )
            return self._create_local(
                summary=summary,
                starts_at=starts_at,
                ends_at=ends_at,
                all_day=all_day,
                location=location,
                description=description,
            )
        ev.sync_state = "synced"
        self._put(ev)
        emit_nowait(
            Event(
                EventType.CALENDAR_CHANGED,
                {"action": "create", "id": ev.id, "provider": ev.provider},
            )
        )
        return ev

    def _create_local(
        self,
        *,
        summary: str,
        starts_at: datetime,
        ends_at: datetime | None = None,
        all_day: bool = False,
        location: str = "",
        description: str = "",
    ) -> CachedEvent:
        raw = uuid4().hex
        ev = CachedEvent(
            id=f"local:{raw}",
            provider="local",
            calendar_id="local",
            summary=summary,
            starts_at=starts_at,
            ends_at=ends_at or starts_at + timedelta(hours=1),
            all_day=all_day,
            location=location,
            description=description,
            raw_id=raw,
            sync_state="pending",
        )
        self._put(ev)
        emit_nowait(
            Event(
                EventType.CALENDAR_CHANGED,
                {"action": "create", "id": ev.id, "provider": "local"},
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
        if which == "local":
            return self._update_local(
                event_id,
                summary=summary,
                starts_at=starts_at,
                ends_at=ends_at,
                all_day=all_day,
                location=location,
                description=description,
            )
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
        if which == "local":
            store, owns = self._open_store()
            try:
                store.delete_id(event_id)
                store.delete_id(f"local:{raw_id}")
            finally:
                if owns:
                    store.close()
            emit_nowait(
                Event(
                    EventType.CALENDAR_CHANGED,
                    {"action": "delete", "id": event_id, "provider": "local"},
                )
            )
            return
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
                    "Google Calendar not authorized. Sign in on the calendar tile."
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
                "Outlook not authorized. Sign in on the calendar tile."
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

    def _update_local(
        self,
        event_id: str,
        *,
        summary: str | None = None,
        starts_at: datetime | None = None,
        ends_at: datetime | None = None,
        all_day: bool | None = None,
        location: str | None = None,
        description: str | None = None,
    ) -> CachedEvent:
        existing = self.get(event_id)
        if existing is None:
            raise RuntimeError(f"No local event {event_id}.")
        ev = CachedEvent(
            id=existing.id,
            provider="local",
            calendar_id=existing.calendar_id,
            summary=summary if summary is not None else existing.summary,
            starts_at=starts_at if starts_at is not None else existing.starts_at,
            ends_at=ends_at if ends_at is not None else existing.ends_at,
            all_day=existing.all_day if all_day is None else all_day,
            location=location if location is not None else existing.location,
            description=(
                description if description is not None else existing.description
            ),
            raw_id=existing.raw_id,
            sync_state="pending",
        )
        self._put(ev)
        emit_nowait(
            Event(
                EventType.CALENDAR_CHANGED,
                {"action": "update", "id": ev.id, "provider": "local"},
            )
        )
        return ev

    def _find_slot(self, summary: str, starts_at: datetime) -> CachedEvent | None:
        store, owns = self._open_store()
        try:
            return self._slot_in_store(store, summary, starts_at)
        finally:
            if owns:
                store.close()

    def _slot_in_store(
        self,
        store: CalendarStore,
        summary: str,
        starts_at: datetime,
        *,
        skip_id: str = "",
    ) -> CachedEvent | None:
        day = starts_at.date()
        for hit in store.list_range(day, day):
            if skip_id and hit.id == skip_id:
                continue
            if same_event_slot(summary, starts_at, hit):
                return hit
        return None

    async def _promote_pending(
        self,
        ev: CachedEvent,
        *,
        dest: str,
        calendar_id: str | None = None,
    ) -> CachedEvent:
        client = self.client(dest)
        remote = await client.create_event(
            summary=ev.summary,
            starts_at=ev.starts_at,
            ends_at=ev.ends_at,
            all_day=ev.all_day,
            location=ev.location,
            description=ev.description,
            calendar_id=calendar_id,
        )
        remote.sync_state = "synced"
        store, owns = self._open_store()
        try:
            store.put(remote)
            store.delete_id(ev.id)
        finally:
            if owns:
                store.close()
        emit_nowait(
            Event(
                EventType.CALENDAR_CHANGED,
                {"action": "push", "id": remote.id, "provider": dest},
            )
        )
        return remote

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
