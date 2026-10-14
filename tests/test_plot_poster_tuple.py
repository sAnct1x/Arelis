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
@pytest.mark.parametrize(
    "expr",
    [
        ("sin(x)", "cos(x)"),
        "('sin(x)', 'cos(x)')",
        "(sin(x), x**2)",
    ],
)
async def test_tuple_expressions_draw_two_poster_panels(tmp_path, monkeypatch, expr) -> None:
    tool, drop = _tool(tmp_path, monkeypatch)

    result = await tool.run(**_POSTER, expr=expr, out="tuple.png")

    assert "unsupported syntax" not in result.output
    assert result.ok, result.output
    png = drop / "tuple.png"
    assert png.is_file()
    _assert_two_panels(png)


@pytest.mark.asyncio
async def test_each_panel_keeps_its_own_expression_and_range_pair(tmp_path, monkeypatch) -> None:
    tool, drop = _tool(tmp_path, monkeypatch)

    result = await tool.run(
        action="subplots",
        panels=[
            {"kind": "line", "expr": "sin(x)", "xmin": "(0, 10)"},
            {"kind": "line", "expr": "cos(x)", "xmax": "0, 10"},
        ],
        look="poster",
        out="panels.png",
    )

    assert "unsupported syntax" not in result.output
    assert result.ok, result.output
    png = drop / "panels.png"
    assert png.is_file()
    _assert_two_panels(png)


@pytest.mark.asyncio
async def test_a_line_chart_draws_several_expressions(tmp_path, monkeypatch) -> None:
    tool, drop = _tool(tmp_path, monkeypatch)

    result = await tool.run(action="line", expr="x, x**2", xmin="0", xmax="2", out="lines.png")

    assert "unsupported syntax" not in result.output
    assert result.ok, result.output
    assert (drop / "lines.png").is_file()
    source = str(result.data.get("source") or "")
    assert "x**2" in source


@pytest.mark.asyncio
async def test_a_comma_inside_a_call_stays_one_expression(tmp_path, monkeypatch) -> None:
    tool, _drop = _tool(tmp_path, monkeypatch)

    result = await tool.run(action="line", expr="atan2(y, x)", xmin="0", xmax="1", out="atan.png")

    assert "unsupported syntax" not in result.output
    assert not result.ok
    assert "unbound" in result.output.lower()


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
