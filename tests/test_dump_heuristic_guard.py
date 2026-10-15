"""Dump heuristic must keep person lists and content lookups, still catch Horizons."""

from __future__ import annotations

from arelis.core.failure_copy import _looks_like_data_dump, chat_followup_from_tool

_DATA = "could not put it into words"

_REMIND_LIST = (
    "#12  2026-10-05T18:00:00-04:00  call the dentist\n"
    "#13  2026-10-06T09:00:00-04:00  pack for the lab\n"
    "#14  2026-10-07T09:00:00-04:00  submit homework\n"
    "3 pending reminder(s)."
)

_TASKS_LIST = "[ ] buy milk\n[ ] finish lab report\n[x] email professor"

_BULLETS = "- Mercury\n- Venus\n- Earth"

_HAIKU = "An old silent pond\nA frog jumps into the pond\nSplash! Silence again"

_RECIPE = "2 cups flour\n1 cup sugar\n3 eggs\n1 tsp vanilla"

_CODE = "def add(a, b):\n    return a + b\nprint(add(2, 3))"

_CHINESE = "火星有两颗卫星。\n它们叫火卫一和火卫二\n火卫一比火卫二大"

_WEATHER_NOW = (
    "Place: Springfield, Illinois\n"
    "Coordinates: 39.7817, -89.6501\n"
    "Now: 54°F (feels 52°F), overcast, precip 0.0."
)

_HORIZONS = "API VERSION: 1.2\nTarget body name: Moon (301)"


def test_remind_list_stays_readable_via_exemption() -> None:
    """Without _PERSON_LIST_TOOLS this sample trips the dump heuristic."""
    assert _looks_like_data_dump(_REMIND_LIST) is True
    line = chat_followup_from_tool("remind", _REMIND_LIST, ask="what reminders do I have?")
    assert _DATA not in line.lower()
    assert "call the dentist" in line
    assert "submit homework" in line


def test_tasks_list_stays_readable_via_exemption() -> None:
    assert _looks_like_data_dump(_TASKS_LIST) is True
    line = chat_followup_from_tool("tasks", _TASKS_LIST, ask="what's on my task list?")
    assert _DATA not in line.lower()
    assert "buy milk" in line
    assert "email professor" in line


def test_bulleted_list_from_lookup_ships_as_is() -> None:
    """Bullet guard: a short list from a non-exempt lookup is still person-facing."""
    assert _looks_like_data_dump(_BULLETS) is False
    line = chat_followup_from_tool("wikipedia", _BULLETS, ask="name the inner planets")
    assert line.strip() == _BULLETS
    assert _DATA not in line.lower()


