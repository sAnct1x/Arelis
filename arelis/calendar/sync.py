"""Sync Google/Outlook windows into the local calendar cache."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from arelis.calendar.google_client import (
    GoogleCalendarClient,
    extra_google_calendar_ids,
)
from arelis.calendar.outlook_client import OutlookCalendarClient
from arelis.calendar.secrets import CalendarSecrets, load_calendar_secrets
from arelis.calendar.store import CalendarStore

log = logging.getLogger(__name__)


async def sync_calendars(
    config: dict[str, Any],
    *,
    store: CalendarStore | None = None,
    secrets: CalendarSecrets | None = None,
    providers: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Pull a past/future window into the cache. Returns a summary dict."""
    cal_cfg = (config.get("tools") or {}).get("calendar") or {}
    past = int(cal_cfg.get("sync_past_days", 7))
    future = int(cal_cfg.get("sync_future_days", 60))
    now = datetime.now().astimezone()
    start = now - timedelta(days=max(0, past))
    end = now + timedelta(days=max(1, future))

    secrets = secrets or load_calendar_secrets()
    owns = store is None
    store = store or CalendarStore()
    wanted = set(providers or ("google", "outlook"))
    summary: dict[str, Any] = {"ok": True, "providers": {}, "errors": []}

    try:
        if "google" in wanted and secrets.google and secrets.google.authorized:
            try:
                client = GoogleCalendarClient(secrets.google)
                cal_id = (
                    str(cal_cfg.get("google_calendar_id") or "").strip()
                    or secrets.google.calendar_id
                )
                events = await client.list_events(
                    time_min=start, time_max=end, calendar_id=cal_id
                )
                extra_ids: list[str] = []
                if bool(cal_cfg.get("include_holidays", True)):
                    try:
                        extra_ids = extra_google_calendar_ids(
                            await client.list_calendar_list(),
                            primary_id=cal_id or "primary",
                        )
                        for extra_id in extra_ids:
                            events.extend(
                                await client.list_events(
                                    time_min=start,
                                    time_max=end,
                                    calendar_id=extra_id,
                                )
                            )
                    except Exception as exc:
                        log.warning("Google holiday calendars skipped: %s", exc)
                seen: set[str] = set()
                deduped: list[Any] = []
                for ev in events:
                    if ev.id in seen:
                        continue
                    seen.add(ev.id)
                    deduped.append(ev)
                n = store.replace_provider_window(
                    "google", deduped, start=start, end=end
                )
                summary["providers"]["google"] = {
                    "count": n,
                    "ok": True,
                    "calendars": 1 + len(extra_ids),
                }
            except Exception as exc:
                log.warning("Google calendar sync failed: %s", exc)
                summary["providers"]["google"] = {"ok": False, "error": str(exc)}
                summary["errors"].append(f"google: {exc}")
                summary["ok"] = False

        if "outlook" in wanted and secrets.outlook and secrets.outlook.authorized:
            try:
                client = OutlookCalendarClient(secrets.outlook)
                cal_id = (
                    str(cal_cfg.get("outlook_calendar_id") or "").strip()
                    or secrets.outlook.calendar_id
                    or None
                )
                events = await client.list_events(
                    time_min=start, time_max=end, calendar_id=cal_id or None
                )
                n = store.replace_provider_window(
                    "outlook", events, start=start, end=end
                )
                summary["providers"]["outlook"] = {"count": n, "ok": True}
            except Exception as exc:
                log.warning("Outlook calendar sync failed: %s", exc)
                summary["providers"]["outlook"] = {"ok": False, "error": str(exc)}
                summary["errors"].append(f"outlook: {exc}")
                summary["ok"] = False
    finally:
        if owns:
            store.close()

    if not summary["providers"]:
        summary["ok"] = False
        summary["errors"].append(
            "No authorized calendar providers. "
            "See docs/calendar-oauth.md and run arelis --auth-calendar …"
        )
    return summary
