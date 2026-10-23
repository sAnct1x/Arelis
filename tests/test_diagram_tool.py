"""Text diagrams: a picture plus the text that made it, inside the room."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from arelis.tools.diagram import DiagramTool
from arelis.tools.diagram_bins import (
    OFFLINE,
)
from arelis.tools.diagram_render import render_typst
from arelis.workspace import RootEntry, WorkspaceRoots

_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="40">'
    '<rect width="80" height="40" fill="#123456"/></svg>'
)
_FLOW = "flowchart LR\n  raw[Telescope raw FITS] --> bias[Bias and dark] --> flat[Flat field]\n"
_BAD_FLOW = "flowchart LR\n  A -->\n"
_VEGA = json.dumps(
    {
        "data": {"values": [{"x": 1, "y": 2}, {"x": 2, "y": 1}, {"x": 3, "y": 3}]},
        "mark": "line",
        "encoding": {
            "x": {"field": "x", "type": "quantitative"},
            "y": {"field": "y", "type": "quantitative"},
        },
    }
)
_TYPST = '#set page(width: 160pt, height: 60pt, margin: 8pt)\nDepth delta approx 1.5%\n'
# Vega and typst load native libraries into this interpreter. On the Ubuntu
# runner that makes the next math picture miss its time budget, so those
# checks run in a fresh process and then go away.
_CHILD = "ARELIS_DIAGRAM_CHILD"


def _fresh_interpreter(nodeid: str) -> bool:
    if os.environ.get(_CHILD) == "1":
        return False
    repo = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env[_CHILD] = "1"
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=short", nodeid],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-4000:]
    return True


def _tool(tmp_path: Path, *, room: bool = True) -> tuple[DiagramTool, Path]:
    root = tmp_path / "proj"
    root.mkdir()
    workspace = WorkspaceRoots([RootEntry(name="proj", path=root.resolve())])
    rooms = SimpleNamespace(active=SimpleNamespace(root="proj")) if room else None
    return DiagramTool(workspace, rooms), root


def _assert_picture(svg: Path, png: Path) -> None:
    assert svg.is_file() and svg.stat().st_size > 1024
    assert png.is_file() and png.stat().st_size > 1024
    assert png.read_bytes().startswith(b"\x89PNG")
    assert b"<svg" in svg.read_bytes()[:200].lower() or b"<svg" in svg.read_bytes().lower()


@pytest.mark.serial
@pytest.mark.asyncio
async def test_invalid_mermaid_returns_the_parser_line(tmp_path: Path) -> None:
    tool, root = _tool(tmp_path)
    result = await tool.run(kind="mermaid", source=_BAD_FLOW, out="broken")

    assert not result.ok
    assert result.output.strip()
    assert "offline" not in result.output.lower()
    assert not (root / "results" / "broken.png").exists()
    assert not (root / "results" / "broken.svg").exists()
    lowered = result.output.lower()
    assert any(token in lowered for token in ("line", "parse", "expect", "error", "syntax"))


@pytest.mark.asyncio
async def test_svg_drawing_lands_in_the_room_results_folder(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    workspace = WorkspaceRoots([RootEntry(name="proj", path=root.resolve())])
    rooms = SimpleNamespace(active=SimpleNamespace(root="proj"))
    tool = DiagramTool(workspace, rooms)

    result = await tool.run(kind="svg", source=_SVG, out="../outside")

    assert result.ok, result.output
    png = Path(result.data["abs_path"])
    results = (root / "results").resolve()
    assert png.resolve().is_relative_to(results)
    assert png.stat().st_size > 32
    assert not (tmp_path / "outside.png").exists()
    assert "the project's results folder" in result.output


def test_typst_package_failure_offline_is_plain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if _fresh_interpreter(
        "tests/test_diagram_tool.py::test_typst_package_failure_offline_is_plain"
    ):
        return
    import typst

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("failed to download package @preview/cetz:0.3.1: connection failed")

    monkeypatch.setattr(typst, "compile", _boom)
    message = render_typst("#import \"@preview/cetz:0.3.1\"\n", tmp_path / "a.svg", tmp_path / "a.png")

    assert message == OFFLINE
    assert "@preview" not in (message or "")
    assert "http" not in (message or "")


