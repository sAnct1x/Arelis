"""Plot tool — named charts, real PNG, Allow on write, no Python eval."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from arelis.tools import build_tool_registry
from arelis.tools.base import capability_class
from arelis.tools.confirm_copy import confirm_headline
from arelis.tools.plot import PlotTool
from arelis.workspace import WorkspaceRoots


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    data = tmp_path / "appdata"
    data.mkdir()
    monkeypatch.setenv("ARELIS_DATA_DIR", str(data))
    workspace = WorkspaceRoots.from_config(
        {"workspace": {"roots": [{"name": "project", "path": str(root)}]}}
    )
    return root, data, workspace


@pytest.fixture
def tool(project):
    _root, _data, workspace = project
    return PlotTool(workspace)


@pytest.mark.asyncio
async def test_line_from_inline_numbers(project, tool) -> None:
    _root, data, _ws = project
    result = await tool.run(
        action="line",
        xs="1, 2, 3, 4",
        ys="1, 4, 9, 16",
        title="squares",
        xlabel="x",
        ylabel="y",
    )
    assert result.ok, result.output
    dest = result.data["abs_path"]
    assert dest.endswith(".png")
    with Image.open(dest) as img:
        assert img.size[0] > 100 and img.size[1] > 80
    assert (data / "outputs" / "plots").is_dir()
    assert "from this turn" in result.output.lower()
    assert "Wrote" in result.output


@pytest.mark.asyncio
async def test_residuals_from_csv_reports_fit(project, tool) -> None:
    root, _data, _ws = project
    csv = root / "lab.csv"
    csv.write_text("t,y\n0,1\n1,3\n2,5\n3,7\n", encoding="utf-8")
    result = await tool.run(
        action="residuals",
        path="project:lab.csv",
        x="t",
        y="y",
    )
    assert result.ok, result.output
    assert "R^2" in result.output
    assert result.data["n"] == 4
    table = Path(result.data["abs_path"]).with_suffix(".csv")
    assert "residual" in table.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_rejects_expression_instead_of_numbers(tool) -> None:
    result = await tool.run(action="line", xs="__import__('os')", ys="1,2")
    assert not result.ok
    assert "numbers" in result.output.lower()


@pytest.mark.asyncio
async def test_path_outside_workspace_is_refused(tool, tmp_path) -> None:
    outside = tmp_path / "elsewhere" / "secret.csv"
    outside.parent.mkdir()
    outside.write_text("t,y\n0,1\n1,2\n2,3\n", encoding="utf-8")
    result = await tool.run(
        action="line", path=str(outside), x="t", y="y"
    )
    assert not result.ok
    assert "outside" in result.output.lower()


@pytest.mark.asyncio
async def test_out_basename_cannot_leave_plots_dir(project, tool) -> None:
    _root, data, _ws = project
    result = await tool.run(
        action="line",
        xs="1, 2, 3",
        ys="1, 2, 3",
        out="..\\..\\escape.png",
    )
    assert result.ok, result.output
    dest = result.data["abs_path"]
    plots = (data / "outputs" / "plots").resolve()
    assert Path(dest).resolve().parent == plots
    assert Path(dest).name == "escape.png"


@pytest.mark.asyncio
async def test_rejects_missing_columns(project, tool) -> None:
    root, _data, _ws = project
    (root / "lab.csv").write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    result = await tool.run(action="scatter", path="project:lab.csv", x="t", y="y")
    assert not result.ok
    assert "No column" in result.output


@pytest.mark.asyncio
async def test_excel_without_reader_says_save_as_csv(project, tool, monkeypatch) -> None:
    root, _data, _ws = project
    (root / "lab.xlsx").write_bytes(b"not-a-real-workbook")

    def boom(*_args, **_kwargs):
        raise ImportError("Missing optional dependency 'openpyxl'")

    monkeypatch.setattr("arelis.tools.plot.pd.read_excel", boom)
    result = await tool.run(
        action="line", path="project:lab.xlsx", x="t", y="y"
    )
    assert not result.ok
    assert "csv" in result.output.lower()


def test_plot_needs_confirm_writes_and_skips_jobs(project) -> None:
    _root, _data, workspace = project
    config = {"tools": {}, "agent": {}}
    registry = build_tool_registry(config, workspace, allow_send=True)
    assert registry.get("plot") is not None
    args = {"action": "line", "xs": "1,2", "ys": "3,4"}
    assert registry.needs_confirm("plot", args)
    assert registry.needs_confirm("plot", args, confirm_image=False)
    assert not registry.needs_confirm("plot", args, confirm_writes=False)
    jobs = build_tool_registry(config, workspace, allow_send=False)
    assert jobs.get("plot") is None
    assert capability_class("plot") == "WRITE_LOCAL"
    assert confirm_headline("plot", {}) == "write a plot"
    assert confirm_headline("plot", {"out": "residuals.png"}) == "write residuals.png"
