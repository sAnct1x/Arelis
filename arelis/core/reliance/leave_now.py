"""Whether to leave for the next event.

Weather is a detail on this line. It does not stand in for the event.
"""

from __future__ import annotations

from datetime import datetime, timedelta


def leave_line(
    *,
    now: datetime,
    event_start: datetime | None,
    place: str = "",
    conditions: str = "",
    travel_minutes: int = 0,
    window_minutes: int = 180,
) -> str | None:
    """One line for the next event, or None when there is nothing to leave for.

    ``None`` when there is no start, the event has already begun, or it sits
    further out than ``window_minutes``. A negative travel time is zero.
    A naive instant beside an aware one is read in the aware zone.
    """
    if event_start is None:
        return None
    now, event_start = _share_zone(now, event_start)
    try:
        delta = event_start - now
    except TypeError:
        return None
    if delta.total_seconds() <= 0:
        return None
    if delta > timedelta(minutes=window_minutes):
        return None

    minutes_until = int(delta.total_seconds() // 60)
    travel = _travel_minutes(travel_minutes)
    where = place.strip()
    weather = conditions.strip()

    when = _minutes(minutes_until) if minutes_until else "less than a minute"
    parts = [f"In {when} at {where}." if where else f"In {when}."]
    if weather:
        parts.append(_sentence(weather))
    if travel > 0:
        slack = minutes_until - travel
        if slack > 0:
            parts.append(f"Leave in {_minutes(slack)}.")
        else:
            parts.append("Leave now.")
    return " ".join(parts)


def _travel_minutes(travel_minutes: int) -> int:
    try:
        travel = int(travel_minutes)
    except (TypeError, ValueError):
        return 0
    return travel if travel > 0 else 0


def _minutes(count: int) -> str:
    unit = "minute" if count == 1 else "minutes"
    return f"{count} {unit}"


def _sentence(text: str) -> str:
    if text.endswith((".", "!", "?")):
        return text
    return f"{text}."


def _is_aware(moment: datetime) -> bool:
    if moment.tzinfo is None:
        return False
    try:
        return moment.tzinfo.utcoffset(moment) is not None
    except Exception:
        # A broken tzinfo that throws is not a real offset. Treat it as naive.
        return False


def _share_zone(now: datetime, event_start: datetime) -> tuple[datetime, datetime]:
    now_aware = _is_aware(now)
    event_aware = _is_aware(event_start)
    if now_aware and not event_aware:
        return now, event_start.replace(tzinfo=now.tzinfo)
    if event_aware and not now_aware:
        return now.replace(tzinfo=event_start.tzinfo), event_start
    return now, event_start
