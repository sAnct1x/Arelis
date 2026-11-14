"""A sentinel status ask that says "units" does not owe the units tool."""

from __future__ import annotations

from types import SimpleNamespace

from arelis.core.claims import detect_exactness_need
from arelis.core.turn_scratch import named_tools_owed


def _owed(text: str) -> list[str]:
    ctx = SimpleNamespace(
        text=text,
        typed_text=None,
        staged_files=(),
        available_all={"units", "sentinel_status", "sentinel_list"},
    )
    return named_tools_owed(SimpleNamespace(tools_used=[]), ctx)


def test_sentinel_unit_counts_owe_no_units_but_conversions_still_route() -> None:
    for ask in (
        "Give me the Sentinel status in one line: total units, Harvester count, "
        "and whether EMP is off. Do not change anything.",
        "Give me the Sentinel status in one line: total units, Harvester count, "
        "and whether EMP stop is on or off.",
        "Sentinel status again in one line: total units and Harvester count.",
        "how many units are deployed?",
        "How many units are in the swarm, and how many Harvesters?",
    ):
        assert "units" not in _owed(ask), ask
        assert "units" not in detect_exactness_need(ask).kinds, ask
    for ask in (
        "Convert 5 miles to kilometers with the units tool.",
        "use units: how many grams in a pound",
        "what is 30 C in F? call units",
        "convert these units",
        "can you do units: 5 ft to m",
        "what units is this in",
        "convert 22 units from feet to meters",
    ):
        assert _owed(ask) == ["units"], ask
    for ask in ("convert 5 miles to km", "how many kilometers is 5 miles"):
        assert "units" in detect_exactness_need(ask).kinds, ask
