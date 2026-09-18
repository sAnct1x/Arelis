"""In-process reminders. Persist + due logic — no Qt, no Task Scheduler.

``schedule`` is Windows Task Scheduler plus email. This is the short timer:
"remind me in 20 minutes" lands here, survives a restart, and returns a
plain dict the parent can turn into a tray toast plus a notify-center
Notice. The poller lives in the parent; this module only answers
``due_now`` / ``mark_fired`` / ``seconds_until_next``.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from arelis.paths import state_dir

log = logging.getLogger(__name__)

DEFAULT_STORE_NAME = "reminders.json"
KIND = "remind"
MAX_PENDING = 50
MAX_MESSAGE_CHARS = 400
MAX_DELAY_DAYS = 7
MAX_DELAY = timedelta(days=MAX_DELAY_DAYS)
MAX_DELAY_SECONDS = MAX_DELAY.total_seconds()

_LONG_DELAY = (
    "Reminders only go up to 7 days. Use schedule or agenda for anything later."
)


class ReminderError(ValueError):
    """The caller asked for a reminder this store will not keep."""


@dataclass
class Reminder:
    id: str
    message: str
    due_iso: str
    created_iso: str = ""
    fired: bool = False

    def due_at(self) -> datetime:
        return parse_local_datetime(self.due_iso)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def fire_payload(self) -> dict[str, Any]:
        """Plain dict for a tray toast + notify-center Notice."""
        return {
            "id": self.id,
            "message": self.message,
            "due_iso": self.due_iso,
            "kind": KIND,
        }


def default_reminders_path() -> Path:
    """``data/reminders.json`` under the user data dir."""
    return state_dir() / DEFAULT_STORE_NAME


def local_now() -> datetime:
    return datetime.now().astimezone()


def as_aware(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=local_now().tzinfo)


def parse_local_datetime(text: str) -> datetime:
    """ISO or ``YYYY-MM-DD HH:MM`` local time. Naive clocks stay local."""
    raw = (text or "").strip()
    if not raw:
        raise ReminderError(
            "Could not read that as a time. Use ISO or YYYY-MM-DD HH:MM."
        )
    cleaned = raw.replace("Z", "+00:00")
    if "T" not in cleaned and " " in cleaned:
        cleaned = cleaned.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        raise ReminderError(
            f"Could not read {text!r} as a time. Use ISO or YYYY-MM-DD HH:MM."
        ) from None
    return as_aware(parsed)


def normalize_message(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        raise ReminderError("A reminder needs a message.")
    if len(text) > MAX_MESSAGE_CHARS:
        raise ReminderError(
            f"That message is too long. Keep it to {MAX_MESSAGE_CHARS} characters."
        )
    return text


def delay_seconds(
    *,
    hours: Any = 0,
    minutes: Any = 0,
    seconds: Any = 0,
) -> float:
    """Total delay in seconds. Refuses 0, negative, and anything past 7 days."""
    total = (
        _as_number(hours, "hours") * 3600.0
        + _as_number(minutes, "minutes") * 60.0
        + _as_number(seconds, "seconds")
    )
    if total <= 0:
        raise ReminderError("Delay must be greater than zero.")
    if total > MAX_DELAY_SECONDS:
        raise ReminderError(_LONG_DELAY)
    return total


def fire_payload(reminder: Reminder) -> dict[str, Any]:
    return reminder.fire_payload()


class ReminderStore:
    """JSON list of one-shot reminders. Atomic write. Thread-safe."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_reminders_path()
        self._lock = threading.Lock()
        self._next_id = 1

    def add_in(
        self,
        message: str,
        *,
        minutes: Any = 0,
        seconds: Any = 0,
        hours: Any = 0,
        now: datetime | None = None,
    ) -> Reminder:
        stamp = as_aware(now or local_now())
        due = stamp + timedelta(seconds=delay_seconds(
            hours=hours, minutes=minutes, seconds=seconds
        ))
        return self._add(message, due, created=stamp)

    def add_at(
        self,
        when: datetime | str,
        message: str,
        *,
        now: datetime | None = None,
    ) -> Reminder:
        stamp = as_aware(now or local_now())
        due = when if isinstance(when, datetime) else parse_local_datetime(when)
        due = as_aware(due)
        delta = (due - stamp).total_seconds()
        if delta <= 0:
            raise ReminderError("That time is already past. Use a future time.")
        if delta > MAX_DELAY_SECONDS:
            raise ReminderError(_LONG_DELAY)
        return self._add(message, due, created=stamp)

    def list_pending(self) -> list[Reminder]:
        with self._lock:
            items = self._load_unlocked()
        pending = [item for item in items if not item.fired]
        pending.sort(key=lambda item: item.due_iso)
        return pending

    def get(self, reminder_id: str | int) -> Reminder | None:
        wanted = _id_text(reminder_id)
        if not wanted:
            return None
        with self._lock:
            for item in self._load_unlocked():
                if item.id == wanted:
                    return item
        return None

    def cancel(self, reminder_id: str | int) -> Reminder | None:
        wanted = _id_text(reminder_id)
        if not wanted:
            return None
        with self._lock:
            items = self._load_unlocked()
            kept: list[Reminder] = []
            removed: Reminder | None = None
            for item in items:
                if item.id == wanted and removed is None:
                    removed = item
                else:
                    kept.append(item)
            if removed is not None:
                self._save_unlocked(items=kept, next_id=self._next_id)
            return removed

    def due_now(self, now: datetime | None = None) -> list[Reminder]:
        """Unfired reminders whose due is at or before ``now``.

        Overdue items stay on disk until ``mark_fired``. A restart must
        still return them — dropping them here would swallow a timer that
        matured while the process was down.
        """
        stamp = as_aware(now or local_now())
        due: list[Reminder] = []
        with self._lock:
            items = self._load_unlocked()
        for item in items:
            if item.fired:
                continue
            try:
                when = item.due_at()
            except ReminderError:
                continue
            if when <= stamp:
                due.append(item)
        due.sort(key=lambda item: item.due_iso)
        return due

    def mark_fired(self, reminder_id: str | int) -> bool:
        wanted = _id_text(reminder_id)
        if not wanted:
            return False
        with self._lock:
            items = self._load_unlocked()
            found = False
            for item in items:
                if item.id == wanted:
                    item.fired = True
                    found = True
                    break
            if found:
                self._save_unlocked(items=items, next_id=self._next_id)
            return found

    def seconds_until_next(self, now: datetime | None = None) -> float | None:
        """Seconds to the next unfired due, or ``None`` if the list is empty.

        Already-due items return ``0.0`` so a poller can fire immediately
        after startup instead of waiting a full tick.
        """
        stamp = as_aware(now or local_now())
        soonest: float | None = None
        with self._lock:
            items = self._load_unlocked()
        for item in items:
            if item.fired:
                continue
            try:
                when = item.due_at()
            except ReminderError:
                continue
            wait = max(0.0, (when - stamp).total_seconds())
            if soonest is None or wait < soonest:
                soonest = wait
        return soonest

    def _add(self, message: str, due: datetime, *, created: datetime) -> Reminder:
        text = normalize_message(message)
        due_iso = as_aware(due).isoformat(timespec="seconds")
        created_iso = as_aware(created).isoformat(timespec="seconds")
        with self._lock:
            items = self._load_unlocked()
            pending = sum(1 for item in items if not item.fired)
            if pending >= MAX_PENDING:
                raise ReminderError(
                    f"Too many pending reminders ({MAX_PENDING}). Cancel one first."
                )
            reminder_id = str(self._next_id)
            self._next_id += 1
            item = Reminder(
                id=reminder_id,
                message=text,
                due_iso=due_iso,
                created_iso=created_iso,
                fired=False,
            )
            items.append(item)
            self._save_unlocked(items=items, next_id=self._next_id)
            return item

    def _load_unlocked(self) -> list[Reminder]:
        self._next_id = 1
        if not self.path.is_file():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Could not read reminders %s: %s", self.path, exc)
            return []
        if not isinstance(raw, dict):
            return []
        try:
            self._next_id = max(1, int(raw.get("next_id") or 1))
        except (TypeError, ValueError):
            self._next_id = 1
        rows = raw.get("items")
        if not isinstance(rows, list):
            return []
        items: list[Reminder] = []
        max_id = self._next_id - 1
        for row in rows:
            item = _reminder_from_row(row)
            if item is None:
                continue
            items.append(item)
            try:
                max_id = max(max_id, int(item.id))
            except ValueError:
                pass
        self._next_id = max(self._next_id, max_id + 1)
        return items

    def _save_unlocked(self, *, items: list[Reminder], next_id: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "next_id": int(next_id),
            "items": [item.as_dict() for item in items],
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)


def _as_number(raw: Any, label: str) -> float:
    if raw is None or str(raw).strip() == "":
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise ReminderError(f"{label} must be a number.") from None


def _id_text(raw: Any) -> str:
    text = str(raw or "").strip()
    if text.startswith("#"):
        text = text[1:].strip()
    return text


def _reminder_from_row(row: Any) -> Reminder | None:
    if not isinstance(row, dict):
        return None
    reminder_id = _id_text(row.get("id"))
    message = str(row.get("message") or "").strip()
    due_iso = str(row.get("due_iso") or "").strip()
    if not reminder_id or not message or not due_iso:
        return None
    try:
        parse_local_datetime(due_iso)
    except ReminderError:
        log.warning("Skipping reminder %r with bad due %r", reminder_id, due_iso)
        return None
    return Reminder(
        id=reminder_id,
        message=message,
        due_iso=due_iso,
        created_iso=str(row.get("created_iso") or ""),
        fired=bool(row.get("fired", False)),
    )
