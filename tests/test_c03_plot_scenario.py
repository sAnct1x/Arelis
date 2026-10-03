"""Test C03 scenario: python > plot > document with real plot validation.

This test demonstrates why C03 fails in demo but passes in matrix.
Matrix uses stubbed tools that always succeed; demo uses real plot validation.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from arelis.rooms import RoomStore
from arelis.tools.plot import PlotTool
from arelis.workspace import RootEntry, WorkspaceRoots


@pytest.mark.no_ui
@pytest.mark.asyncio
async def test_plot_rejects_empty_ys():
    """Plot correctly rejects empty ys parameter - this is what could cause C03 failure.
    
    If the 9B model calls plot(xs="1,2,3,4,5,6,7,8", ys="") after python,
    the real plot tool fails while the matrix stub would succeed.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "proj"
        root.mkdir()
        workspace = WorkspaceRoots([RootEntry(name="proj", path=root)])
        plot = PlotTool(workspace, rooms=None)
        
        # Simulating a 9B model error: passing empty ys
        result = await plot.run(
            action="line",
            xs="1,2,3,4,5,6,7,8",
            ys="",  # Empty - the model should pass the squares here
        )
        
        assert not result.ok, "Plot should reject empty ys"
        assert "Give a table path" in result.output or "xs and ys as numbers" in result.output


@pytest.mark.no_ui
@pytest.mark.asyncio
async def test_plot_rejects_variable_reference():
    """Plot rejects variable names instead of actual data.
    
    If 9B passes ys="squares" (a variable name) instead of "1,4,9,16,25,36,49,64",
    plot's _parse_numbers will fail trying to parse "squares" as a float.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "proj"
        root.mkdir()
        workspace = WorkspaceRoots([RootEntry(name="proj", path=root)])
        plot = PlotTool(workspace, rooms=None)
        
        # Simulating 9B passing a variable name
        result = await plot.run(
            action="line",
            xs="1,2,3,4,5,6,7,8",
            ys="squares",  # Variable name, not actual numbers
        )
        
        assert not result.ok, "Plot should reject non-numeric data"
        assert "must be numbers" in result.output or "not an expression" in result.output


@pytest.mark.no_ui
@pytest.mark.asyncio
async def test_plot_accepts_correct_data():
    """Plot accepts properly formatted numeric data.
    
    This is what SHOULD happen in C03 if the model generates correct arguments.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "proj"  
        root.mkdir()
        plots = root / "plots"
        plots.mkdir()
        workspace = WorkspaceRoots([RootEntry(name="proj", path=root)])
        plot = PlotTool(workspace, rooms=None)
        
        # Correct format
        result = await plot.run(
            action="line",
            xs="1,2,3,4,5,6,7,8",
            ys="1,4,9,16,25,36,49,64",
        )
        
        assert result.ok, f"Plot should accept correct data: {result.output}"
        assert "Wrote" in result.output
        
        # Verify file was created
        png_path = plots / "plot-line.png"
        assert png_path.exists(), f"PNG should be created at {png_path}"


@pytest.mark.no_ui
def test_matrix_stub_vs_real_plot():
    """Document the key difference: matrix stubs always succeed, real tool validates.
    
    This is not a runnable test, but documents the root cause:
    - Matrix: PlotTool is stubbed (harness.py:586) - returns ok=True always
    - Demo: Real PlotTool validates arguments and can fail
    
    Result: Matrix completes C03 in ~3 rounds, demo burns rounds on plot retries.
    """
    # This documents the finding - no actual test needed
    pass


def test_fail_counts_fingerprint_uses_full_args():
    """Verify that different arguments get different fail_counts fingerprints.
    
    This confirms that fail_counts CORRECTLY doesn't block calls with different args.
    The fingerprint includes the full JSON-serialized args dict.
    """
    from arelis.core.loop_helpers import _tool_fail_fingerprint
    
    fp1 = _tool_fail_fingerprint("plot", {"xs": "", "ys": ""})
    fp2 = _tool_fail_fingerprint("plot", {"xs": "1,2,3", "ys": "1,4,9"})
    fp3 = _tool_fail_fingerprint("plot", {"xs": "", "ys": ""})  # Same as fp1
    
    assert fp1 != fp2, "Different args should get different fingerprints"
    assert fp1 == fp3, "Same args should get same fingerprint"


@pytest.mark.no_ui
def test_unique_dest_collision_avoidance():
    """Verify -2 suffix is correct behavior when file exists."""
    from arelis.tools.plot import _unique_dest
    
    with tempfile.TemporaryDirectory() as tmpdir:
        folder = Path(tmpdir)
        
        # First call - no collision
        dest1 = _unique_dest(folder, "Squares-Report", ".md")
        assert dest1.name == "Squares-Report.md"
        
        # Create the file
        dest1.touch()
        
        # Second call - collision, gets -2
        dest2 = _unique_dest(folder, "Squares-Report", ".md")
        assert dest2.name == "Squares-Report-2.md"
        
        # This is CORRECT behavior - prevents overwriting existing files
