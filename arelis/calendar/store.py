"""SQLite cache for synced calendar events."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from arelis.calendar.models import CachedEvent
from arelis.config import PROJECT_ROOT

DEFAULT_DB = PROJECT_ROOT / "data" / "calendar_cache.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    calendar_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    ends_at TEXT,
    all_day INTEGER NOT NULL DEFAULT 0,
    location TEXT,
    description TEXT,
    etag TEXT,
    raw_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_starts ON events(starts_at);
CREATE INDEX IF NOT EXISTS idx_events_provider ON events(provider);
"""


class CalendarStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def replace_provider_window(
        self,
        provider: str,
        events: list[CachedEvent],
        *,
        start: datetime,
        end: datetime,
    ) -> int:
        """Replace cached events for provider overlapping [start, end)."""
        cur = self._conn.cursor()
        cur.execute(
            """
            DELETE FROM events
            WHERE provider = ?
              AND starts_at < ?
              AND (ends_at IS NULL OR ends_at > ?)
            """,
            (provider, end.isoformat(), start.isoformat()),
        )
        now = datetime.now().astimezone().isoformat()
        for ev in events:
            cur.execute(
                """
                INSERT OR REPLACE INTO events (
                    id, provider, calendar_id, summary, starts_at, ends_at,
                    all_day, location, description, etag, raw_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ev.id,
                    ev.provider,
                    ev.calendar_id,
                    ev.summary,
                    ev.starts_at.isoformat(),
                    ev.ends_at.isoformat() if ev.ends_at else None,
                    1 if ev.all_day else 0,
                    ev.location,
                    ev.description,
                    ev.etag,
                    ev.raw_id or ev.id,
                    now,
                ),
            )
        self._conn.commit()
        return len(events)

    def list_range(
        self,
        start_day: date,
        end_day: date,
        *,
        provider: str | None = None,
        tz: ZoneInfo | None = None,
    ) -> list[CachedEvent]:
        # Inclusive date window → UTC-ish ISO bounds using local midnight.
        zone = tz or datetime.now().astimezone().tzinfo
        start_dt = datetime(
            start_day.year, start_day.month, start_day.day, tzinfo=zone
        )
        end_exclusive = datetime(
            end_day.year, end_day.month, end_day.day, tzinfo=zone
        )
        from datetime import timedelta

        end_exclusive = end_exclusive + timedelta(days=1)
        sql = """
            SELECT * FROM events
            WHERE starts_at < ?
              AND (ends_at IS NULL OR ends_at > ?)
        """
        args: list[Any] = [end_exclusive.isoformat(), start_dt.isoformat()]
        if provider and provider != "all":
            sql += " AND provider = ?"
            args.append(provider)
        sql += " ORDER BY starts_at ASC"
        rows = self._conn.execute(sql, args).fetchall()
        return [_row_to_event(r) for r in rows]

    def get(self, event_id: str) -> CachedEvent | None:
        row = self._conn.execute(
            "SELECT * FROM events WHERE id = ? OR raw_id = ?",
            (event_id, event_id),
        ).fetchone()
        return _row_to_event(row) if row else None

    def delete_id(self, event_id: str) -> None:
        self._conn.execute(
            "DELETE FROM events WHERE id = ? OR raw_id = ?",
            (event_id, event_id),
        )
        self._conn.commit()


def _row_to_event(row: sqlite3.Row) -> CachedEvent:
    ends = row["ends_at"]
    return CachedEvent(
        id=row["id"],
        provider=row["provider"],
        calendar_id=row["calendar_id"],
        summary=row["summary"] or "",
        starts_at=datetime.fromisoformat(row["starts_at"]),
        ends_at=datetime.fromisoformat(ends) if ends else None,
        all_day=bool(row["all_day"]),
        location=row["location"] or "",
        description=row["description"] or "",
        etag=row["etag"] or "",
        raw_id=row["raw_id"] or row["id"],
    )
