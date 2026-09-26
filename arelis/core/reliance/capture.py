"""One sentence in, one destination out.

A clock or a self-contained delay is a reminder. No clock is a task.
Recurrence is not a fired reminder: "every morning" stays a task and
keeps the phrase so a later layer can refuse to pretend it is a timer.
``schedule`` and ``goals`` are not destinations of this function.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime

_RECURRENCE = re.compile(
    r"\b("
    r"every\s+(?:single\s+|other\s+)?(?:\d+\s+)?"
    r"(?:morning|afternoon|evening|nights?|days?|weeks?|weekdays?|weekends?|"
    r"months?|mondays?|tuesdays?|wednesdays?|thursdays?|fridays?|"
    r"saturdays?|sundays?|minutes?|hours?)"
    r"(?:\s+at\s+(?:noon|midnight|\d{1,2}(?::\d{2})?(?:\s*[ap]\.?m\.?)?))?"
    r"|daily"
    r"|(?:on\s+)?weekdays"
    r")\b",
    re.IGNORECASE,
)

_RELATIVE = re.compile(
    r"\b("
    r"in\s+(?:an|a|one|\d+(?:\.\d+)?)\s+"
    r"(?:seconds?|secs?|minutes?|mins?|hours?|hrs?)"
    r"(?:\s+and\s+a\s+half)?"
    r")\b",
    re.IGNORECASE,
)

_CLOCK = re.compile(
    r"\b("
    r"(?:tomorrow|today|tonight)\s+at\s+"
    r"(?:noon|midnight|\d{1,2}(?::\d{2})?(?:\s*[ap]\.?m\.?)?)"
    r"|(?:tomorrow|today|this)\s+(?:morning|afternoon|evening|night|noon)"
    r"|tonight"
    r"|at\s+\d{1,2}(?::\d{2})?(?:\s*[ap]\.?m\.?)?"
    r"|at\s+(?:noon|midnight)"
    r")\b",
    re.IGNORECASE,
)

_FILLER = re.compile(
    r"^(?:please\s+)?(?:remind\s+me\s+(?:to\s+)?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Capture:
    dest: str  # "remind" or "task"
    title: str
    when_text: str | None  # the time phrase, if any
    minutes: int | None  # set for relative delays like "in 20 minutes"


def classify_capture(text: str, *, now: datetime) -> Capture:
    """Classify one utterance as a reminder or a task.

    Relative delays ("in 20 minutes", "in an hour", "in 2 hours",
    "in 90 seconds") are ``dest="remind"``. Minutes are taken from the
    phrase. When the only unit is seconds, the count is ``ceil`` of
    seconds/60, and anything under a minute becomes 1 minute
    ("in 90 seconds" is 2). The time phrase is stripped from the title.

    Clock phrases ("at 3", "at 3pm", "at 15:00", "tomorrow at 8",
    "tonight", "tomorrow morning") are also ``dest="remind"``, with
    ``minutes=None`` and ``when_text`` set to that phrase. The title is
    whatever remains.

    No time means ``dest="task"``. The word "remind" is not a clock, so
    "remind me to buy milk" is a task titled "buy milk".

    Recurrence is not a fired reminder. "every", "daily", and "weekdays"
    keep ``dest="task"`` and put the recurrence phrase in ``when_text``
    so a later layer can refuse to pretend it is a timer.

    ``now`` is accepted for a later absolute-time layer. Relative phrases
    are self-contained, so this function does not read ``now`` and does
    not call ``datetime.now()``.

    Empty text raises ``ValueError``.
    """
    # `now` belongs to a later layer that resolves clocks against a wall
    # time. Relative minutes do not need it.
    del now

    raw = (text or "").strip()
    if not raw:
        raise ValueError("capture text is empty")

    recurrence = _first(_RECURRENCE, raw)
    if recurrence is not None:
        title = _clean_title(_cut(raw, _RECURRENCE))
        title = _clean_title(_cut(title, _CLOCK, valid=_valid_clock))
        return Capture(
            dest="task",
            title=title,
            when_text=_phrase(recurrence),
            minutes=None,
        )

    relative = _first(_RELATIVE, raw)
    if relative is not None:
        return Capture(
            dest="remind",
            title=_clean_title(_cut(raw, _RELATIVE)),
            when_text=_phrase(relative),
            minutes=_minutes_from_relative(relative),
        )

    clock = _first(_CLOCK, raw, valid=_valid_clock)
    if clock is not None:
        return Capture(
            dest="remind",
            title=_clean_title(_cut(raw, _CLOCK, valid=_valid_clock)),
            when_text=_phrase(clock),
            minutes=None,
        )

    return Capture(dest="task", title=_clean_title(raw), when_text=None, minutes=None)


def _first(
    pattern: re.Pattern[str],
    text: str,
    *,
    valid=None,
) -> str | None:
    for match in pattern.finditer(text):
        phrase = match.group(1)
        if valid is None or valid(phrase):
            return phrase
    return None


def _cut(text: str, pattern: re.Pattern[str], *, valid=None) -> str:
    pieces: list[str] = []
    last = 0
    for match in pattern.finditer(text):
        if valid is not None and not valid(match.group(1)):
            continue
        pieces.append(text[last : match.start()])
        last = match.end()
    pieces.append(text[last:])
    return "".join(pieces)


def _phrase(phrase: str) -> str:
    return re.sub(r"\s+", " ", phrase).strip()


def _clean_title(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    filler = _FILLER.match(collapsed)
    if filler is not None:
        collapsed = collapsed[filler.end() :]
    collapsed = re.sub(r"^(?:to|about)\s+", "", collapsed, flags=re.IGNORECASE)
    collapsed = re.sub(r"\s+", " ", collapsed).strip(" \t,;:-")
    if collapsed.endswith((".", "!", "?")):
        collapsed = collapsed[:-1].rstrip()
    return collapsed.strip()


def _minutes_from_relative(phrase: str) -> int:
    match = re.search(
        r"(?i)in\s+(an|a|one|\d+(?:\.\d+)?)\s+"
        r"(seconds?|secs?|minutes?|mins?|hours?|hrs?)"
        r"(?:\s+and\s+a\s+half)?",
        phrase,
    )
    if match is None:
        raise ValueError(f"not a relative delay: {phrase}")
    raw_amount, unit = match.group(1).lower(), match.group(2).lower()
    half = re.search(r"(?i)and\s+a\s+half", phrase) is not None
    amount = 1.0 if raw_amount in {"a", "an", "one"} else float(raw_amount)
    if unit.startswith("sec"):
        # Only-seconds delays: ceil, and anything under a minute is 1.
        return max(1, math.ceil(amount / 60))
    if unit.startswith("min"):
        return _as_minutes(amount + (0.5 if half else 0.0))
    return _as_minutes(amount * 60 + (30 if half else 0))


def _as_minutes(value: float) -> int:
    whole = round(value)
    if abs(value - whole) < 1e-6:
        return int(whole)
    return math.ceil(value)


def _valid_clock(phrase: str) -> bool:
    match = re.search(
        r"(?i)(\d{1,2})(?::(\d{2}))?(?:\s*([ap])\.?m\.?)?",
        phrase,
    )
    if match is None:
        return True
    hour = int(match.group(1))
    minute = int(match.group(2)) if match.group(2) is not None else None
    ampm = match.group(3)
    if minute is not None and not 0 <= minute <= 59:
        return False
    if ampm is not None:
        return 1 <= hour <= 12
    return 0 <= hour <= 23
