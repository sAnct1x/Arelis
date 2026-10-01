"""Regression tests for live matrix issues (S45, P03, C05, P05, C24b).

Tests that the routing and path handling fixes from cursor/fix-live-matrix-routing-0e78
remain correct. Each test corresponds to a specific live matrix problem that was reported.

These tests are marked with 'no_ui' to skip UI-related fixtures.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from arelis.tools.diagnostics import DiagnosticsTool
from arelis.tools.doc_extract import DocExtractTool, build_simple_pdf_bytes
from arelis.tools.pdf_assemble import PdfAssembleTool
from arelis.tools.run_task import RunTaskTool
from arelis.workspace import RootEntry, WorkspaceRoots

pytestmark = pytest.mark.no_ui


def _workspace(tmp_path: Path) -> tuple[WorkspaceRoots, Path]:
    project = tmp_path / "project"
    project.mkdir()
    workspace = WorkspaceRoots([RootEntry(name="project", path=project.resolve())])
    return workspace, project


def _pdf_with_pages(path: Path, texts: list[str]) -> Path:
    writer = PdfWriter()
    for text in texts:
        reader = PdfReader(BytesIO(build_simple_pdf_bytes(text)))
        writer.add_page(reader.pages[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


@pytest.mark.asyncio
async def test_diagnostics_description_no_longer_says_only_when_asked() -> None:
    """Issue 1 (S45, P03): diagnostics tool description was too conservative.
    
    The old description said 'Call this only when the user asks to run diagnostics',
    which discouraged routing to it. The new description mentions test/pytest/diagnostics
    to improve matching.
    """
    tool = DiagnosticsTool()
    assert "only when the user asks to run diagnostics" not in tool.description.lower()
    assert "test" in tool.description.lower() or "pytest" in tool.description.lower()
    assert "diagnostics" in tool.description.lower()


@pytest.mark.asyncio
async def test_run_task_unknown_suggests_run_script_for_paths(tmp_path: Path) -> None:
    """Issue 2 (C05, P05): run_task should suggest run_script for unknown tasks with path chars.
    
    When a task name contains path separators (like 'sq.py' or 'work/sq'), the error
    should suggest using run_script instead.
    """
    workspace, _project = _workspace(tmp_path)
    tool = RunTaskTool(workspace)
    
    result = await tool.run(action="run", name="sq.py")
    assert not result.ok
    assert "run_script" in result.output.lower()
    assert "unknown task" in result.output.lower()


@pytest.mark.asyncio
async def test_run_task_unknown_does_not_suggest_run_script_for_simple_names(tmp_path: Path) -> None:
    """Issue 2 continuation: simple task names should not get the run_script hint."""
    workspace, _project = _workspace(tmp_path)
    tool = RunTaskTool(workspace)
    
    result = await tool.run(action="run", name="build")
    assert not result.ok
    assert "unknown task" in result.output.lower()
    assert "run_script" not in result.output.lower()


@pytest.mark.asyncio
async def test_workspace_write_missing_content_is_actionable(tmp_path: Path) -> None:
    """Issue 2 (empty content): workspace write error should explain how to pass content."""
    from arelis.tools.code_workspace import CodeWorkspaceTool
    
    workspace, _project = _workspace(tmp_path)
    tool = CodeWorkspaceTool(workspace)
    
    result = await tool.run(action="write", path="test.txt")
    assert not result.ok
    assert "missing content" in result.output.lower()
    assert "content=" in result.output.lower()
    assert "empty" in result.output.lower() or "pass" in result.output.lower()


@pytest.mark.asyncio
async def test_pdf_merge_output_is_workspace_relative(tmp_path: Path) -> None:
    """Issue 3 (C24b): pdf tool should report workspace-relative paths.
    
    The pdf tool used display_path() which could return absolute paths. It now uses
    qualified() like the workspace tool, so doc_extract can resolve the path correctly.
    """
    workspace, project = _workspace(tmp_path)
    tool = PdfAssembleTool(workspace)
    
    a = _pdf_with_pages(project / "a.pdf", ["ALPHA"])
    b = _pdf_with_pages(project / "b.pdf", ["BRAVO"])
    
    result = await tool.run(action="merge", paths=[str(a), str(b)])
    assert result.ok, result.output
    
    path = result.data["path"]
    abs_path = result.data["abs_path"]
    
    # The path should be workspace-relative (starts with outputs/ or project:outputs/)
    assert not Path(path).is_absolute(), f"path {path} should be workspace-relative"
    assert "outputs" in path.lower()
    
    # But abs_path should still be absolute
    assert Path(abs_path).is_absolute()


@pytest.mark.asyncio
async def test_pdf_output_can_be_used_by_doc_extract(tmp_path: Path) -> None:
    """Issue 3 chain test: pdf output path works as doc_extract input.
    
    This is the actual failure mode: after pdf merge, the model tried to use the
    output path with doc_extract and got 'outputs/test_matrix/outputs/merged-2.pdf'
    because the path wasn't workspace-relative.
    """
    workspace, project = _workspace(tmp_path)
    pdf_tool = PdfAssembleTool(workspace)
    extract_tool = DocExtractTool(workspace)
    
    a = _pdf_with_pages(project / "a.pdf", ["ALPHA-123"])
    b = _pdf_with_pages(project / "b.pdf", ["BRAVO-456"])
    
    merge_result = await pdf_tool.run(action="merge", paths=[str(a), str(b)])
    assert merge_result.ok, merge_result.output
    
    merged_path = merge_result.data["path"]
    
    # Now try to extract from the merged PDF using the workspace-relative path
    extract_result = await extract_tool.run(path=merged_path)
    assert extract_result.ok, f"doc_extract failed on pdf output path {merged_path}: {extract_result.output}"
    assert "ALPHA-123" in extract_result.output
    assert "BRAVO-456" in extract_result.output


@pytest.mark.asyncio
async def test_pdf_sources_are_also_workspace_relative(tmp_path: Path) -> None:
    """Issue 3 extension: source paths in data should also be workspace-relative."""
    workspace, project = _workspace(tmp_path)
    tool = PdfAssembleTool(workspace)
    
    a = _pdf_with_pages(project / "a.pdf", ["ALPHA"])
    b = _pdf_with_pages(project / "b.pdf", ["BRAVO"])
    
    result = await tool.run(action="merge", paths=[str(a), str(b)])
    assert result.ok, result.output
    
    sources = result.data["sources"]
    assert len(sources) == 2
    
    for source in sources:
        assert not Path(source).is_absolute(), f"source {source} should be workspace-relative"
