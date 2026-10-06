"""Chat path: Horizons distance answers stay the tool text.

The 9B calls catalog with a date or a sentence, then writes a closest the
tool did not return. These fail if that date is kept or the invented line
is what chat shows.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from arelis.core.compact_prompt import skinny_description
from arelis.tools.catalog import (
    CatalogTool,
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


def test_short_description_says_omit_date_and_do_not_add() -> None:
    text = skinny_description("catalog", CatalogTool.description)
    assert "omit date" in text
    assert "closest" in text
    assert "do not add" in text
    assert len(f"`catalog`: {text}") <= 220


def test_date_schema_is_not_for_closest() -> None:
    desc = CatalogTool.parameters_schema["properties"]["date"]["description"]
    assert "Omit" in desc
    assert "closest" in desc
    target = CatalogTool.parameters_schema["properties"]["target"]["description"]
    assert "Not a sentence" in target


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


def test_fill_round_calls_drops_the_made_up_horizons_date() -> None:
    from arelis.core.turn_dispatch import fill_round_calls

    loop = SimpleNamespace(tools=_Tools(), memory=None, _receipts=None)
    filled = fill_round_calls(
        loop,
        [
            (
                "catalog",
                {
                    "action": "horizons",
                    "target": "Mars",
                    "date": "2026-11-04",
                    "query": "closest approach",
                },
            )
        ],
        text="how far is Mars and when is it closest",
    )
    args = filled[0][1]
    assert args["target"] == "Mars"
    assert "date" not in args
    assert "query" not in args


def test_a_named_sky_day_is_not_rewritten() -> None:
    args = normalize_horizons_distance_args(
        {
            "action": "horizons",
            "target": "499",
            "date": "2026-10-01",
            "table": "observer",
        },
        "Use the catalog horizons lookup for Mars on 2026-10-01 and report the RA and Dec.",
    )
    assert args["date"] == "2026-10-01"
    assert args["target"] == "499"
    assert args["table"] == "observer"


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


def test_a_day_the_user_named_is_kept() -> None:
    args = normalize_horizons_distance_args(
        {"action": "horizons", "target": "Mars", "date": "2026-10-01"},
        "how far was Mars on 2026-10-01",
    )
    assert args["date"] == "2026-10-01"
    assert args["target"] == "Mars"


def test_invented_moon_closest_keeps_the_tool_dates() -> None:
    invented = "The Moon is about 374,000 km away. Closest Nov 4 ~335.9M km."
    line = chat_line_for_distance(_MOON, invented, ask="how far is the Moon")
    assert line == _MOON
    assert "Oct 28" in line
    assert "Oct 16" in line
    assert "Nov 4" not in line
    assert "335.9" not in line


def test_a_second_topic_can_stay_if_it_does_not_invent() -> None:
    reply = _MARS + " Boston is sunny."
    line = chat_line_for_distance(
        _MARS,
        reply,
        ask="how far is Mars and what is the weather",
    )
    assert line == reply
    invented = reply + " Closest Nov 4 ~335.9M km."
    locked = chat_line_for_distance(
        _MARS,
        invented,
        ask="how far is Mars and what is the weather",
    )
    assert locked == _MARS
    assert "335.9" not in locked


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
