"""Morning plate. Time-bound first, then mail, then the home forecast.

Pure. No window, no network, no tool calls. The caller already has the
lists; this only decides what to show and in what order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

_HORIZON_HOURS = 18
_TASK_CAP = 5
_MAIL_CAP = 5


@dataclass(frozen=True)
class PlateRow:
    kind: str  # leave, event, task, mail, weather
    title: str
    detail: str


@dataclass(frozen=True)
class MorningPlate:
    lead: str
    rows: tuple[PlateRow, ...]


def compose_morning(
    *,
    now: datetime,
    events: list[dict],
    unread: list[dict],
    tasks: list[dict],
    weather_home: str = "",
    weather_by_place: dict[str, str] | None = None,
    leave: str | None = None,
    horizon_hours: int = _HORIZON_HOURS,
) -> MorningPlate:
    """Build the plate for ``now``.

    Order is leave, events inside the horizon, tasks due today or overdue,
    unread, then home weather. The lead names the first time-bound thing.
    Mail and the home forecast do not change the lead.
    """
    places = weather_by_place or {}
    horizon = now + timedelta(hours=horizon_hours)
    today = now.date()

    rows: list[PlateRow] = []
    leave_text = (leave or "").strip()
    if leave_text:
        rows.append(PlateRow(kind="leave", title=leave_text, detail=""))

    kept_events = _events_in_horizon(
        events, now=now, horizon=horizon, places=places
    )
    rows.extend(kept_events)

    kept_tasks = _due_tasks(tasks, now=now, today=today)
    rows.extend(kept_tasks)

    rows.extend(_unread_rows(unread))

    home = (weather_home or "").strip()
    if home:
        rows.append(PlateRow(kind="weather", title="Home", detail=home))

    return MorningPlate(
        lead=_lead(leave_text, kept_events, kept_tasks),
        rows=tuple(rows),
    )


def render_plate(plate: MorningPlate) -> str:
    """Plain text. Lead, then one block per row, separated by a blank line."""
    blocks = [plate.lead]
    for row in plate.rows:
        block = f"[{row.kind}] {row.title}"
        if row.detail:
            block = f"{block}\n{row.detail}"
        blocks.append(block)
    return "\n\n".join(blocks) + "\n"


def _lead(leave_text: str, events: list[PlateRow], tasks: list[PlateRow]) -> str:
    if leave_text:
        return _leave_lead(leave_text)
    if events:
        return _event_lead(events[0])
    if tasks:
        return _task_lead(tasks[0])
    return "Nothing time-bound."


def _leave_lead(leave_text: str) -> str:
    raw = leave_text.strip()
    # A full leave-now sentence already reads on its own. Prefixing "Leave"
    # turns it into "Leave In 40 minutes... Leave in 25 minutes."
    if ". " in raw:
        return raw if raw.endswith(".") else f"{raw}."
    text = raw.rstrip(".").strip()
    if text.casefold().startswith("leave"):
        sentence = text
    else:
        sentence = f"Leave {text}"
    if sentence[:1].islower():
        sentence = sentence[0].upper() + sentence[1:]
    return f"{sentence}."


def _event_lead(row: PlateRow) -> str:
    name = row.title or "Untitled"
    clock = _clock_from_detail(row.detail)
    if clock:
        return f"{name} at {clock}."
    return f"{name}."


def _task_lead(row: PlateRow) -> str:
    name = row.title or "Untitled"
    if row.detail.startswith("overdue"):
        return f"{name} is overdue."
    return f"{name} is due."


def _clock_from_detail(detail: str) -> str:
    head = detail.split(",", 1)[0].strip()
    if not head:
        return ""
    return head.split("-", 1)[0].strip()


def _events_in_horizon(
    events: list[dict],
    *,
    now: datetime,
    horizon: datetime,
    places: dict[str, str],
) -> list[PlateRow]:
    chosen: list[tuple[datetime, int, PlateRow]] = []
    for index, event in enumerate(events):
        start = _parse_dt(event.get("starts_at"), now)
        if start is None or not (now <= start < horizon):
            continue
        end = _parse_dt(event.get("ends_at"), now)
        if end is not None and end < now:
            continue
        location = str(event.get("location") or "").strip()
        title = str(event.get("summary") or "").strip()
        chosen.append(
            (
                start,
                index,
                PlateRow(
                    kind="event",
                    title=title,
                    detail=_event_detail(start, end, location, places),
                ),
            )
        )
    chosen.sort(key=lambda item: (item[0], item[1]))
    return [row for _, _, row in chosen]


def _event_detail(
    start: datetime,
    end: datetime | None,
    location: str,
    places: dict[str, str],
) -> str:
    parts = [_span(start, end)]
    if location:
        parts.append(location)
        blurb = _weather_for(location, places)
        if blurb:
            parts.append(blurb)
    return ", ".join(parts)


def _span(start: datetime, end: datetime | None) -> str:
    left = start.strftime("%H:%M")
    if end is None:
        return left
    return f"{left}-{end.strftime('%H:%M')}"


def _weather_for(location: str, places: dict[str, str]) -> str:
    folded = location.casefold()
    for key, value in places.items():
        if str(key).strip().casefold() == folded:
            return str(value or "").strip()
    return ""


def _due_tasks(tasks: list[dict], *, now: datetime, today: date) -> list[PlateRow]:
    ranked: list[tuple[int, date, int, PlateRow]] = []
    for index, task in enumerate(tasks):
        due = _due_date(task.get("due"), now)
        if due is None or due > today:
            continue
        title = str(task.get("title") or "").strip()
        high = str(task.get("priority") or "").strip().casefold() == "high"
        status = "overdue" if due < today else "due today"
        ranked.append(
            (
                0 if high else 1,
                due,
                index,
                PlateRow(
                    kind="task",
                    title=title,
                    detail=f"{status}, {due.isoformat()}",
                ),
            )
        )
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    return [row for _, _, _, row in ranked[:_TASK_CAP]]


def _unread_rows(unread: list[dict]) -> list[PlateRow]:
    rows: list[PlateRow] = []
    for message in unread[:_MAIL_CAP]:
        rows.append(
            PlateRow(
                kind="mail",
                title=str(message.get("subject") or "").strip(),
                detail=str(message.get("from") or "").strip(),
            )
        )
    return rows


def _due_date(raw: object, now: datetime) -> date | None:
    parsed = _parse_dt(raw, now)
    if parsed is None:
        return None
    return parsed.date()


def _parse_dt(raw: object, now: datetime) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return _align(parsed, now)


def _align(value: datetime, now: datetime) -> datetime:
    """Compare naive and aware values without raising.

    An aware ``now`` treats a naive input as already in that zone.
    A naive ``now`` drops the input's zone instead of converting it.
    Two aware values are compared in ``now``'s zone.
    """
    if now.tzinfo is None:
        if value.tzinfo is not None:
            return value.replace(tzinfo=None)
        return value
    if value.tzinfo is None:
        return value.replace(tzinfo=now.tzinfo)
    return value.astimezone(now.tzinfo)
