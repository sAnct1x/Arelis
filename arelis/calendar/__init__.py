"""Cloud calendar sync (Google + Outlook) with a local cache.

Explicit OAuth exception for calendar only. See docs/calendar-oauth.md.
"""

from __future__ import annotations

from arelis.calendar.models import CachedEvent
from arelis.calendar.secrets import CalendarSecrets, load_calendar_secrets
from arelis.calendar.store import CalendarStore

__all__ = [
    "CachedEvent",
    "CalendarSecrets",
    "CalendarStore",
    "load_calendar_secrets",
]
