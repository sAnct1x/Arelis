"""Failure-lesson playbook selection."""

from __future__ import annotations

from arelis.core.lessons import format_lessons, load_lessons, select_lessons


def test_seed_lessons_load() -> None:
    lessons = load_lessons()
    ids = {lesson.id for lesson in lessons}
    assert "weather-not-scrape" in ids
    assert "sms-call-not-chat" in ids
    assert "search-url-not-title" in ids


def test_weather_turn_gets_weather_lesson() -> None:
    picked = select_lessons(skill_ids=["weather"], preflight_kinds=["weather"])
    texts = " ".join(lesson.text for lesson in picked).lower()
    assert "weather tool" in texts
    block = format_lessons(picked)
    assert block and "Lessons from past failures" in block
    assert "weather-not-scrape" in block


def test_sms_turn_gets_sms_lesson() -> None:
    picked = select_lessons(skill_ids=["sms"], preflight_kinds=["sms_send"])
    assert any(lesson.id == "sms-call-not-chat" for lesson in picked)
