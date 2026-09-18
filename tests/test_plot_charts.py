"""histogram, bar, and subplots must write real PNGs — not line charts in disguise."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from arelis.tools.plot import PlotTool
from arelis.workspace import RootEntry, WorkspaceRoots


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[PlotTool, Path]:
    root = tmp_path / "proj"
    root.mkdir()
    drop = tmp_path / "drop"
    tool = PlotTool(WorkspaceRoots([RootEntry(name="proj", path=root.resolve())]))
    monkeypatch.setattr(tool, "drop_dir", lambda: _ensure(drop))
    return tool, drop


def _load_rgb(path: Path) -> np.ndarray:
    import matplotlib.image as mpimg

    arr = mpimg.imread(path)
    if arr.ndim == 2:
        return arr
    return arr[..., :3]


def _column_ink(img: np.ndarray) -> np.ndarray:
    gray = img.mean(axis=-1) if img.ndim == 3 else img
    return (gray < 0.92).sum(axis=0)


def _assert_histogram_not_line(path: Path) -> None:
    """A line chart smears ink along one ridge; a histogram fills the axis width."""
    cols = _column_ink(_load_rgb(path))
    assert cols.max() > 10
    n = len(cols)
    chunks = [cols[i * n // 5 : (i + 1) * n // 5].sum() for i in range(5)]
    active = sum(1 for c in chunks if c > max(chunks) * 0.2)
    assert active >= 3, "histogram ink should spread across the axis, not one diagonal stroke"


def _assert_bar_respects_categories(path: Path) -> None:
    """Three bars with 1/5/10 must not look flat — tallest column has more ink."""
    cols = _column_ink(_load_rgb(path))
    third = len(cols) // 3
    left = cols[third // 2 : third].sum()
    mid = cols[third : 2 * third].sum()
    right = cols[2 * third : 3 * third].sum()
    assert right > left * 1.5, "tallest bar should dominate the right third"
    assert mid > left * 1.2, "middle bar should beat the short bar"


def _assert_two_panels(path: Path) -> None:
    img = _load_rgb(path)
    _h, w = img.shape[:2]
    left = img[:, : w // 2]
    right = img[:, w // 2 :]
    assert (left < 0.92).sum() > 200, "left panel is empty"
    assert (right < 0.92).sum() > 200, "right panel is empty"


@pytest.mark.asyncio
async def test_histogram_from_inline_numbers_writes_bars(tmp_path, monkeypatch) -> None:
    tool, drop = _tool(tmp_path, monkeypatch)
    # Skewed counts — a line would not produce separated vertical bins.
    ys = "1,2,2,3,3,3,4,4,4,4,5,5,5,5,5"

    result = await tool.run(action="histogram", ys=ys, bins=5, out="hist.png")

    assert result.ok, result.output
    written = drop / "hist.png"
    assert written.is_file()
    assert written.stat().st_size > 800
    assert written.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    _assert_histogram_not_line(written)

    xs = ",".join(str(i) for i in range(15))
    line = await tool.run(action="line", xs=xs, ys=ys, out="same-data-line.png")
    assert line.ok
    diff = np.abs(_load_rgb(written) - _load_rgb(drop / "same-data-line.png")).mean()
    assert diff > 0.02, "histogram must not be a line chart in disguise"


@pytest.mark.asyncio
async def test_histogram_from_a_table_column(tmp_path, monkeypatch) -> None:
    tool, drop = _tool(tmp_path, monkeypatch)
    table = tmp_path / "proj" / "scores.csv"
    table.write_text("score\n1\n2\n2\n3\n3\n3\n4\n4\n4\n4\n", encoding="utf-8")

    result = await tool.run(
        action="histogram",
        path="scores.csv",
        y="score",
        bins=4,
        out="col-hist.png",
    )

    assert result.ok, result.output
    written = drop / "col-hist.png"
    assert written.is_file()
    _assert_histogram_not_line(written)


@pytest.mark.asyncio
async def test_bar_from_categories_and_values_is_not_a_line(tmp_path, monkeypatch) -> None:
    tool, drop = _tool(tmp_path, monkeypatch)

    result = await tool.run(
        action="bar",
        categories="short,medium,tall",
        values="1,5,10",
        out="bars.png",
    )

    assert result.ok, result.output
    written = drop / "bars.png"
    assert written.is_file()
    assert written.stat().st_size > 800
    _assert_bar_respects_categories(written)


@pytest.mark.asyncio
async def test_bar_from_table_columns_uses_category_labels(tmp_path, monkeypatch) -> None:
    tool, drop = _tool(tmp_path, monkeypatch)
    table = tmp_path / "proj" / "sales.csv"
    table.write_text("team,revenue\nA,1\nB,5\nC,10\n", encoding="utf-8")

    result = await tool.run(
        action="bar",
        path="sales.csv",
        x="team",
        y="revenue",
        out="team-bars.png",
    )

    assert result.ok, result.output
    written = drop / "team-bars.png"
    assert written.is_file()
    _assert_bar_respects_categories(written)


@pytest.mark.asyncio
async def test_subplots_line_and_histogram_both_render(tmp_path, monkeypatch) -> None:
    tool, drop = _tool(tmp_path, monkeypatch)

    result = await tool.run(
        action="subplots",
        panels="line,histogram",
        xs="0,1,2,3,4",
        ys="0,1,4,9,16",
        bins=4,
        out="combo.png",
    )

    assert result.ok, result.output
    written = drop / "combo.png"
    assert written.is_file()
    assert "Panels: line, histogram" in result.output
    _assert_two_panels(written)


@pytest.mark.asyncio
async def test_subplots_refuses_one_panel(tmp_path, monkeypatch) -> None:
    tool, _drop = _tool(tmp_path, monkeypatch)

    result = await tool.run(action="subplots", panels="histogram", ys="1,2,3", out="nope.png")

    assert not result.ok
    assert "at least two" in result.output.lower()


def test_the_schema_advertises_histogram_bar_and_subplots() -> None:
    props = PlotTool.parameters_schema["properties"]
    for key in ("bins", "categories", "values", "panels"):
        assert key in props, f"{key} is not offered to the model"
    enum = props["action"]["enum"]
    for action in ("histogram", "bar", "subplots"):
        assert action in enum
    desc = PlotTool.description
    assert "histogram" in desc
    assert "bar" in desc
    assert "subplots" in desc
