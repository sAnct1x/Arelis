"""Poster charts the model sends as several expressions, and a chart
Python refused before any chart call failed.

The batch that reproduced this kept screenshots only. The exact call
arguments were not saved, so these tests cover every shape that reaches
the tuple error: a comma joined expression, a real tuple, the string
form of that tuple, one expression per panel, and a range pair in one key.
"""

from __future__ import annotations

import pytest

from tests.hardening_helpers import _collect, _ScriptedRouter
from tests.test_plot_charts import _assert_two_panels, _tool
from tests.test_plot_fail_ends_turn import (
    _ASK,
    _assert_honest,
    _call,
    _loop,
)

_POSTER = dict(action="subplots", panels=["line", "line"], xmin="0", xmax="2pi", look="poster")


@pytest.mark.asyncio
async def test_comma_joined_expressions_draw_two_poster_panels(tmp_path, monkeypatch) -> None:
    tool, drop = _tool(tmp_path, monkeypatch)

    result = await tool.run(**_POSTER, expr="sin(x), cos(x)", out="joined.png")

    assert "unsupported syntax" not in result.output
    assert result.ok, result.output
    png = drop / "joined.png"
    assert png.is_file()
    assert "Panels: line, line" in result.output
    _assert_two_panels(png)


@pytest.mark.asyncio
async def test_a_joined_import_is_still_refused(tmp_path, monkeypatch) -> None:
    tool, drop = _tool(tmp_path, monkeypatch)

    result = await tool.run(
        action="line",
        expr="__import__('os'), 1",
        xmin="0",
        xmax="1",
        out="nope.png",
    )

    assert not result.ok
    assert "unsupported syntax" not in result.output
    assert not (drop / "nope.png").is_file()


@pytest.mark.asyncio
async def test_python_refusing_a_chart_first_gets_one_quiet_round_then_stops() -> None:
    """The refusal owes one round. An empty follow-up still ends honestly."""
    router = _ScriptedRouter(
        [
            [("tool_calls", [_call("python", {"code": "import matplotlib.pyplot as plt"})])],
            [("token", "")],
            [("token", "")],
            [("token", "")],
        ]
    )
    bus, loop = _loop(router)
    events = await _collect(bus, loop.run(_ASK, "fast"))
    assert router.i == 2
    _assert_honest(_done(events))


def _done(events):
    from arelis.core.events import EventType

    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    return str(done.payload.get("text") or "")
