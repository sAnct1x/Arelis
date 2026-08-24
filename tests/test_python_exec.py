"""Scientific Python cell — scripts yes, os/subprocess no."""

from __future__ import annotations

import math

import pytest

from arelis.core.evidence import EvidenceLedger
from arelis.tools import build_tool_registry
from arelis.tools.python_exec import PythonTool
from arelis.workspace import WorkspaceRoots


@pytest.mark.asyncio
async def test_projectile_range_from_height() -> None:
    tool = PythonTool()
    result = await tool.run(
        code=(
            "g=9.81; h=5; v=5; th=radians(45)\n"
            "vx=v*cos(th); vy=v*sin(th)\n"
            "disc=vy*vy + 2*g*h\n"
            "t=(vy + sqrt(disc))/g\n"
            "vx*t"
        )
    )
    assert result.ok, result.output
    range_m = float(result.output.strip().splitlines()[-1])
    assert 4.5 < range_m < 6.0


@pytest.mark.asyncio
async def test_import_math_works() -> None:
    tool = PythonTool()
    result = await tool.run(code="import math\nmath.sqrt(9)")
    assert result.ok, result.output
    assert result.output.strip() in {"3", "3.0"}


@pytest.mark.asyncio
async def test_rejects_os() -> None:
    tool = PythonTool()
    result = await tool.run(code="import os\nos.getcwd()")
    assert not result.ok
    assert "os" in result.output.lower()


@pytest.mark.asyncio
async def test_rejects_open() -> None:
    tool = PythonTool()
    result = await tool.run(code="open('secrets.yaml')")
    assert not result.ok


@pytest.mark.asyncio
async def test_source_alias() -> None:
    tool = PythonTool()
    result = await tool.run(source="2+2")
    assert result.ok
    assert result.output.strip() == "4"


def test_python_is_always_registered(tmp_path) -> None:
    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(tmp_path)]}})
    registry = build_tool_registry({"tools": {}, "agent": {}}, workspace)
    assert registry.get("python") is not None
    assert not registry.needs_confirm("python", {"code": "1+1"})
    jobs = build_tool_registry(
        {"tools": {}, "agent": {}}, workspace, allow_send=False
    )
    assert jobs.get("python") is not None


def test_python_success_counts_as_calc() -> None:
    ledger = EvidenceLedger()
    ledger.record_tool(
        "python",
        ok=True,
        output="4.53",
        data={"result": "4.53"},
    )
    assert ledger.has_ok("calc")


def test_trig_preload_matches_math() -> None:
    assert abs(math.sin(math.radians(45)) - math.sqrt(2) / 2) < 1e-9
