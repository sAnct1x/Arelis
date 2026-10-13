"""Poster and subplot calls the 9B actually sends.

The documented shape is panels="line,histogram" with one flat series.
The model also sends a list of kinds, a JSON array, one object per panel,
the key subplots instead of panels, and two series joined with a semicolon.
Those have to draw. A line chart handed a list of lists has to say so.
"""

from __future__ import annotations

import pytest

from tests.test_plot_charts import _assert_two_panels, _tool


@pytest.mark.asyncio
async def test_panels_list_with_poster_look_draws_both(tmp_path, monkeypatch) -> None:
    tool, drop = _tool(tmp_path, monkeypatch)

    result = await tool.run(
        action="subplots",
        panels=["line", "histogram"],
        xs="1,2,3,4",
        ys="1,4,2,8",
        look="poster",
        out="poster.png",
    )

    assert result.ok, result.output
    png = drop / "poster.png"
    svg = drop / "poster.svg"
    assert png.is_file() and svg.is_file()
    assert "Panels: line, histogram" in result.output
    _assert_two_panels(png)


@pytest.mark.asyncio
async def test_json_panels_and_nested_ys_draw(tmp_path, monkeypatch) -> None:
    tool, drop = _tool(tmp_path, monkeypatch)

    result = await tool.run(
        action="subplots",
        panels='["line","histogram"]',
        xs="1,2,3",
        ys=[[1, 2, 3], [4, 5, 6, 7]],
        out="nested.png",
    )

    assert result.ok, result.output
    written = drop / "nested.png"
    assert written.is_file()
    assert "Panels: line, histogram" in result.output
    _assert_two_panels(written)


@pytest.mark.asyncio
async def test_panel_objects_with_their_own_series_draw_poster(tmp_path, monkeypatch) -> None:
    tool, drop = _tool(tmp_path, monkeypatch)

    result = await tool.run(
        action="subplots",
        panels=[
            {"kind": "line", "xs": [1, 2, 3, 4], "ys": [1, 4, 2, 8]},
            {"kind": "histogram", "ys": [1, 1, 2, 2, 2, 3, 4, 4]},
        ],
        look="poster",
        out="objects.png",
    )

    assert result.ok, result.output
    png = drop / "objects.png"
    assert png.is_file()
    assert (drop / "objects.svg").is_file()
    assert (drop / "objects.pdf").is_file()
    assert "Panels: line, histogram" in result.output
    _assert_two_panels(png)


@pytest.mark.asyncio
async def test_subplots_key_is_accepted_as_panels(tmp_path, monkeypatch) -> None:
    tool, drop = _tool(tmp_path, monkeypatch)

    result = await tool.run(
        action="subplots",
        subplots="line,histogram",
        xs="0,1,2,3",
        ys="0,1,4,9",
        out="alias.png",
    )

    assert result.ok, result.output
    written = drop / "alias.png"
    assert written.is_file()
    assert "Panels: line, histogram" in result.output
    _assert_two_panels(written)


@pytest.mark.asyncio
async def test_semicolon_ys_is_one_series_per_panel(tmp_path, monkeypatch) -> None:
    tool, drop = _tool(tmp_path, monkeypatch)

    result = await tool.run(
        action="subplots",
        panels="line,histogram",
        xs="1,2,3",
        ys="1,2,3;4,5,6",
        out="semi.png",
    )

    assert result.ok, result.output
    written = drop / "semi.png"
    assert written.is_file()
    assert "same length" not in result.output
    _assert_two_panels(written)


@pytest.mark.asyncio
async def test_line_chart_names_a_list_of_lists(tmp_path, monkeypatch) -> None:
    tool, _drop = _tool(tmp_path, monkeypatch)

    result = await tool.run(action="line", ys=[[1, 2], [3, 4]], xs=[1, 2], out="bad.png")

    assert not result.ok
    folded = result.output.lower()
    assert "list of lists" in folded or "one list per panel" in folded
    assert "not an expression" not in folded


@pytest.mark.asyncio
async def test_one_panel_object_asks_for_two(tmp_path, monkeypatch) -> None:
    tool, _drop = _tool(tmp_path, monkeypatch)

    result = await tool.run(
        action="subplots",
        panels=[{"kind": "line", "xs": [1, 2, 3], "ys": [1, 4, 9]}],
        out="one.png",
    )

    assert not result.ok
    folded = result.output.lower()
    assert "at least two" in folded
    assert "unknown panel" not in folded
    assert "at most 4" not in folded
