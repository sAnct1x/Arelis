"""Overlap check for a new agenda block. Exact duplicates stay upstream."""

from __future__ import annotations

from datetime import datetime

from arelis.core.reliance.conflicts import find_overlaps, overlap_line

DAY = "2026-09-26"


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 26, hour, minute)


def _event(
    summary: str,
    start: str,
    end: str | None = None,
    *,
    all_day: bool = False,
) -> dict:
    row = {"summary": summary, "starts_at": start}
    if end is not None:
        row["ends_at"] = end
    if all_day:
        row["all_day"] = True
    return row


def test_overlapping_hours_conflict() -> None:
    hits = find_overlaps(
        start=_at(11),
        end=_at(12),
        events=[_event("Morning", f"{DAY}T10:30:00", f"{DAY}T11:30:00")],
    )
    assert [hit.summary for hit in hits] == ["Morning"]
    assert hits[0].starts_at == f"{DAY}T10:30:00"
    assert hits[0].ends_at == f"{DAY}T11:30:00"


def test_adjacent_blocks_are_not_a_conflict() -> None:
    hits = find_overlaps(
        start=_at(11),
        end=_at(12),
        events=[_event("Morning", f"{DAY}T10:00:00", f"{DAY}T11:00:00")],
    )
    assert hits == []


def test_different_title_in_the_same_hour_conflicts() -> None:
    hits = find_overlaps(
        start=_at(15),
        end=_at(16),
        events=[_event("Dentist", f"{DAY}T15:00:00", f"{DAY}T16:00:00")],
    )
    assert len(hits) == 1
    assert hits[0].summary == "Dentist"


def test_ignore_summary_skips_the_duplicate_title() -> None:
    hits = find_overlaps(
        start=_at(15),
        end=_at(16),
        events=[
            _event("Dentist", f"{DAY}T15:00:00", f"{DAY}T16:00:00"),
            _event("Standup", f"{DAY}T15:15:00", f"{DAY}T15:45:00"),
        ],
        ignore_summary="DENTIST",
    )
    assert [hit.summary for hit in hits] == ["Standup"]


def test_all_day_covers_a_3pm_event() -> None:
    hits = find_overlaps(
        start=_at(15),
        end=_at(16),
        events=[_event("Vacation", DAY, all_day=True)],
    )
    assert [hit.summary for hit in hits] == ["Vacation"]
    next_day = find_overlaps(
        start=datetime(2026, 9, 27, 15, 0),
        end=datetime(2026, 9, 27, 16, 0),
        events=[_event("Vacation", DAY, all_day=True)],
    )
    assert next_day == []


def test_missing_end_defaults_to_one_hour() -> None:
    proposed = find_overlaps(
        start=_at(10),
        end=None,
        events=[
            _event("Soon", f"{DAY}T10:30:00", f"{DAY}T11:00:00"),
            _event("Later", f"{DAY}T11:00:00", f"{DAY}T12:00:00"),
        ],
    )
    assert [hit.summary for hit in proposed] == ["Soon"]

    stored = find_overlaps(
        start=_at(11),
        end=_at(11, 30),
        events=[_event("Open ended", f"{DAY}T10:30:00")],
    )
    assert len(stored) == 1
    assert stored[0].ends_at == f"{DAY}T11:30:00"
    abutting = find_overlaps(
        start=_at(11, 30),
        end=_at(12),
        events=[_event("Open ended", f"{DAY}T10:30:00")],
    )
    assert abutting == []


def test_results_are_chronological_and_bad_rows_are_skipped() -> None:
    hits = find_overlaps(
        start=_at(9),
        end=_at(17),
        events=[
            {"summary": "Broken", "starts_at": "not-a-time"},
            _event("Afternoon", f"{DAY}T15:00:00", f"{DAY}T16:00:00"),
            {"summary": "No start"},
            _event("Morning", f"{DAY}T09:30:00", f"{DAY}T10:00:00"),
        ],
    )
    assert [hit.summary for hit in hits] == ["Morning", "Afternoon"]


def test_overlap_line_is_empty_without_hits_and_a_sentence_with_them() -> None:
    assert overlap_line([]) == ""
    hits = find_overlaps(
        start=_at(15),
        end=_at(16),
        events=[_event("Dentist", f"{DAY}T15:00:00", f"{DAY}T16:00:00")],
    )
    line = overlap_line(hits)
    assert line == "You already have Dentist from 3:00 PM to 4:00 PM."
    assert "\n" not in line
