"""Curated auto-lessons from turns.log failure signatures."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import pytest

from arelis.core.lesson_mine import (
    append_lessons,
    mine_turns_log,
    parse_turns_log,
    propose_lesson_ids,
)
from arelis.core.lessons import load_lessons, select_lessons

_SAMPLE = """
turn 02:15:55.170 tool         id=895d00b5 t=19668 name=recall ms=0 ok=0
turn 02:16:00.027 tool         id=895d00b5 t=24525 name=web_search ms=191 ok=0
turn 02:18:31.319 tool         id=ec77da34 t=18509 name=scrape ms=120 ok=0
turn 02:24:41.933 tool         id=2e45cdfe t=20599 name=scrape ms=50 ok=0
turn 02:24:49.207 tool         id=2e45cdfe t=27873 name=web_fetch ms=570 ok=0
turn 02:25:01.073 tool         id=2e45cdfe t=39739 name=scrape ms=1009 ok=0
turn 02:26:10.000 tool         id=aaaa1111 t=100 name=weather ms=20 ok=1
"""


def test_parse_and_propose_from_real_signatures() -> None:
    fails, oks, lines, exact, routing = parse_turns_log(_SAMPLE)
    assert lines >= 7
    assert fails["scrape"] == 3
    assert fails["web_fetch"] == 1
    assert fails["web_search"] == 1
    assert fails["recall"] == 1
    assert oks["weather"] == 1
    assert routing["routing_gap"] == 0
    proposed = propose_lesson_ids(fails, exactness_gates=exact, routing_gaps=routing)
    assert "scrape-fail-stop-loop" in proposed
    assert "search-fail-say-so" in proposed
    assert "recall-miss-is-ok" in proposed


def test_exactness_math_gate_proposes_lesson() -> None:
    text = "turn 01:00:00.000 exactness    id=abcd gate=math action=force\n"
    fails, _oks, _lines, exact, routing = parse_turns_log(text)
    assert exact["math"] == 1
    assert "math-use-calculator" in propose_lesson_ids(
        fails, exactness_gates=exact, routing_gaps=routing
    )


def test_exactness_science_gate_proposes_lesson() -> None:
    text = (
        "turn 01:00:00.000 exactness    id=abcd gate=symbolic action=force\n"
        "turn 01:00:01.000 exactness    id=abce gate=units action=force\n"
        "turn 01:00:02.000 exactness    id=abcf gate=plot action=force\n"
        "turn 01:00:03.000 exactness    id=abcg gate=catalog action=force\n"
    )
    fails, _oks, _lines, exact, routing = parse_turns_log(text)
    assert exact["symbolic"] == 1
    assert exact["units"] == 1
    assert exact["plot"] == 1
    assert exact["catalog"] == 1
    proposed = propose_lesson_ids(fails, exactness_gates=exact, routing_gaps=routing)
    assert "science-use-cas-units" in proposed
    ids = {lesson.id for lesson in load_lessons()}
    assert "science-use-cas-units" in ids


def test_routing_gap_proposes_lesson() -> None:
    text = (
        "turn 01:00:00.000 routing_gap  id=abcd t=1200 "
        "expected=web_search,scrape used=-\n"
    )
    fails, _oks, _lines, exact, routing = parse_turns_log(text)
    assert routing["routing_gap"] == 1
    proposed = propose_lesson_ids(fails, exactness_gates=exact, routing_gaps=routing)
    assert "routing-gap-call-tools" in proposed


def test_seed_covers_routing_gap_lesson() -> None:
    ids = {lesson.id for lesson in load_lessons()}
    assert "routing-gap-call-tools" in ids


def test_seed_covers_mined_web_failures() -> None:
    ids = {lesson.id for lesson in load_lessons()}
    assert "scrape-fail-stop-loop" in ids
    picked = select_lessons(skill_ids=["web"], user_text="latest news article")
    assert any(lesson.id == "scrape-fail-stop-loop" for lesson in picked)


def test_append_skips_seeded_ids(tmp_path: Path) -> None:
    path = tmp_path / "lessons.yaml"
    path.write_text("lessons: []\n", encoding="utf-8")
    assert append_lessons(["scrape-fail-stop-loop"], path=path) == []


def test_append_writes_catalog_only_ids(tmp_path: Path, monkeypatch) -> None:
    import arelis.core.lesson_mine as mine

    monkeypatch.setitem(
        mine._CATALOG,
        "machine-local-test",
        {
            "id": "machine-local-test",
            "tags": ["web"],
            "text": "Test-only tactic from the catalog.",
            "when": "unit test",
        },
    )
    path = tmp_path / "lessons.yaml"
    path.write_text("lessons: []\n", encoding="utf-8")
    added = append_lessons(["machine-local-test"], path=path)
    assert added == ["machine-local-test"]
    assert "machine-local-test" in path.read_text(encoding="utf-8")
    assert append_lessons(["machine-local-test"], path=path) == []


def test_mine_turns_log_proposes_seeded_signatures(tmp_path: Path) -> None:
    log_path = tmp_path / "turns.log"
    lessons_path = tmp_path / "lessons.yaml"
    log_path.write_text(_SAMPLE, encoding="utf-8")
    lessons_path.write_text("lessons: []\n", encoding="utf-8")

    dry = mine_turns_log(
        log_path=log_path, lessons_path=lessons_path, write=False
    )
    assert "scrape-fail-stop-loop" in dry.proposed_ids
    assert dry.appended_ids == ()

    written = mine_turns_log(
        log_path=log_path, lessons_path=lessons_path, write=True
    )
    # Seed already covers these ids — append stays empty; proposal still fires.
    assert written.proposed_ids
    assert set(written.already_present) == set(written.proposed_ids)
    assert written.appended_ids == ()


@pytest.mark.asyncio
async def test_auto_lessons_stay_quiet_when_playbook_already_covers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Covered misses belong in the log, not on the boot rail."""
    from arelis.core.bus import EventBus
    from arelis.core.events import EventType
    from arelis.core.lesson_mine import MineReport
    from arelis.llm.startup import run_auto_lessons

    report = MineReport(
        tool_fail_counts={"calculator": 11, "inbox": 2},
        tool_ok_counts={},
        proposed_ids=("scrape-fail-stop-loop",),
        already_present=("scrape-fail-stop-loop",),
        appended_ids=(),
        lines_scanned=40,
    )
    monkeypatch.setattr(
        "arelis.core.lesson_mine.mine_turns_log", lambda **kwargs: report
    )
    bus = EventBus()
    seen: list[str] = []

    async def collect(event) -> None:
        if event.type == EventType.STATUS:
            seen.append(str((event.payload or {}).get("message") or ""))

    bus.subscribe(None, collect)
    task = asyncio.create_task(bus.run())
    try:
        await run_auto_lessons(bus)
        await bus.drain()
    finally:
        bus.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    assert seen == []
