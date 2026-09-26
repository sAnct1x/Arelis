"""Normalized calendar events for the local cache and agenda tool."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=datetime.now().astimezone().tzinfo)


def event_slot_key(starts_at: datetime, *, all_day: bool = False) -> str:
    """Minute-precision UTC slot so retries with different ISO strings match."""
    if all_day:
        return starts_at.date().isoformat()
    return _aware(starts_at).astimezone(UTC).strftime("%Y-%m-%dT%H:%M")


def create_fingerprint(provider: Any, summary: Any, start: Any) -> str:
    """Turn-level create key. Naive clocks stay local; offsets collapse to UTC."""
    text = str(start or "").strip()
    slot = text
    if text:
        try:
            if len(text) == 10:
                slot = text
            else:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
                slot = event_slot_key(dt)
        except ValueError:
            pass
    return (
        f"{str(provider or '').strip().lower()}|"
        f"{str(summary or '').strip().casefold()}|"
        f"{slot}"
    )


def same_event_slot(
    summary: str,
    starts_at: datetime,
    other: Any,
    *,
    skew_s: float = 60.0,
) -> bool:
    """True when a cache row is the same title + start (idempotency)."""
    other_sum = str(getattr(other, "summary", "") or "").strip().casefold()
    if other_sum != summary.strip().casefold():
        return False
    other_start = getattr(other, "starts_at", None)
    if not isinstance(other_start, datetime):
        return False
    try:
        return abs((_aware(starts_at) - _aware(other_start)).total_seconds()) <= skew_s
    except Exception:
        return False


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
    sync_state: str = "synced"  # pending | synced | failed

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
            "sync_state": self.sync_state,
        }
