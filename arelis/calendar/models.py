"""Normalized calendar events for the local cache and agenda tool."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class CachedEvent:
    id: str
    provider: str  # google | outlook | ics
    calendar_id: str
    summary: str
    starts_at: datetime
    ends_at: datetime | None
    all_day: bool
    location: str = ""
    description: str = ""
    etag: str = ""
    raw_id: str = ""  # provider-native event id

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "calendar_id": self.calendar_id,
            "summary": self.summary,
            "starts_at": self.starts_at.isoformat(),
            "ends_at": self.ends_at.isoformat() if self.ends_at else "",
            "all_day": self.all_day,
            "location": self.location,
            "description": self.description,
            "raw_id": self.raw_id or self.id,
        }
