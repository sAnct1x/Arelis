"""Chat path: Horizons distance answers stay the tool text.

The 9B calls catalog with a date or a sentence, then writes a closest the
tool did not return. These fail if that date is kept or the invented line
is what chat shows.
"""

from __future__ import annotations

import pytest

from arelis.tools.catalog import (
    chat_line_for_distance,
    format_distance_for_model,
    normalize_horizons_distance_args,
)

_MARS = (
    "Mars is 228,000,000 km from Earth right now. "
    "It keeps getting closer for the next 30 days, so there is "
    "no closest or farthest point in that time."
)
_INVENTED = "Mars stays near 228 million km. Closest Nov 4 ~335.9M km."
_MOON = (
    "The Moon is 373,979 km from Earth right now. "
    "It will be closest on Oct 28 at about 2:40 PM Eastern (364,387 km) "
    "and farthest on Oct 16 at about 6:40 PM Eastern (404,680 km)."
)


class _Tools:
    def get(self, name: str):
        del name
        return None


def test_distance_call_drops_a_made_up_date_and_odd_query() -> None:
    args = normalize_horizons_distance_args(
        {
            "action": "horizons",
            "target": "Mars closest Nov 4",
            "date": "2026-11-04",
            "query": "closest approach",
            "table": "vectors",
        },
        "how far is Mars and when is it closest",
    )
    assert args["action"] == "horizons"
    assert args["target"] == "Mars"
    assert args["table"] == "observer"
    assert "date" not in args
    assert "query" not in args


def test_model_note_stays_off_the_chat_line() -> None:
    shown = format_distance_for_model(_MARS)
    assert "from Earth right now" in shown
    assert "Do not add a closest" in shown
    line = chat_line_for_distance(shown, _INVENTED, ask="how far is Mars")
    assert line == _MARS
    assert "Do not add" not in line
    assert "Nov 4" not in line
    assert "335.9" not in line


def test_invented_mars_closest_cannot_replace_a_none() -> None:
    line = chat_line_for_distance(
        _MARS,
        _INVENTED,
        ask="how far is Mars and when is it closest",
    )
    assert line == _MARS
    assert "no closest or farthest" in line
    assert "Nov 4" not in line
    assert "335.9" not in line
    assert "335" not in line


def test_invented_moon_closest_keeps_the_tool_dates() -> None:
    invented = "The Moon is about 374,000 km away. Closest Nov 4 ~335.9M km."
    line = chat_line_for_distance(_MOON, invented, ask="how far is the Moon")
    assert line == _MOON
    assert "Oct 28" in line
    assert "Oct 16" in line
    assert "Nov 4" not in line
    assert "335.9" not in line


@pytest.mark.asyncio
async def test_finish_will_not_ship_an_invented_mars_closest() -> None:
    from tests.hardening_helpers import _loop_with_tools, _ScriptedRouter

    loop = _loop_with_tools(_ScriptedRouter(["ignored"]))
    loop._horizons_distance_text = _MARS
    loop._horizons_distance_ask = "how far is Mars and when is it closest"
    await loop._finish(_INVENTED, [])
    bubble = loop.memory.messages[-1].content
    assert bubble == _MARS
    assert "Nov 4" not in bubble
    assert "335.9" not in bubble
    assert "no closest or farthest" in bubble
