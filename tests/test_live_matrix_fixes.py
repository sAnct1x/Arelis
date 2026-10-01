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


@pytest.mark.asyncio
async def test_doc_ask_matches_read_content_of_docx() -> None:
    """Issue 4 (S37b): DOC_ASK should match 'read content of file.docx' phrasing.
    
    The reworded docx extract ask "Read the content of work/memo.docx" was not
    matching DOC_ASK because it only looked for "read ... document/pdf" but not
    "read ... file.docx" or "read the content of file.docx".
    """
    from arelis.core.intent_catalog import DOC_ASK
    
    # Original phrasing (already worked)
    assert DOC_ASK.search("Extract the text of work/memo.docx")
    
    # Reworded phrasing that was failing
    assert DOC_ASK.search("Read the content of work/memo.docx")
    assert DOC_ASK.search("Get the text from work/report.pdf")
    assert DOC_ASK.search("Show me work/slides.pptx")
    
    # Generic document asks (already worked)
    assert DOC_ASK.search("What does this document say")
    assert DOC_ASK.search("Analyze the PDF")


@pytest.mark.asyncio
async def test_run_script_intent_matches_run_it_and_call_run_script() -> None:
    """Issue 5 (C05, P05): RUN_SCRIPT intent should match 'run it' and 'call run_script'.
    
    The write→run chains in C05 and P05 say "run it with run_script" and 
    "call run_script on work/sq2.py" but weren't matching RUN_SCRIPT intent.
    Note: bare "run it" requires script context to avoid false positives.
    """
    from arelis.core.intent_catalog import RUN_SCRIPT
    
    # Explicit mentions that were working in C05/P05 (with script context)
    assert RUN_SCRIPT.matches("run it with run_script")
    assert RUN_SCRIPT.matches("call run_script on work/sq.py")
    
    # Original patterns (already worked)
    assert RUN_SCRIPT.matches("run work/hello.py")
    assert RUN_SCRIPT.matches("execute the script")
    assert RUN_SCRIPT.matches("run it again")
    
    # Context-dependent: "run it" only matches with script context
    assert RUN_SCRIPT.matches("write test.py then run it")
    assert not RUN_SCRIPT.matches("then run it")  # No script context
    assert not RUN_SCRIPT.matches("and run it")   # No script context


@pytest.mark.asyncio
async def test_write_run_script_plan_matches_chains() -> None:
    """Issue 6 (C05, P05): write→run_script plan should guide multi-step chains.
    
    The plan nudge helps the model understand it needs to write first, then
    run_script (not run_task or python), then optionally read the file back.
    """
    from arelis.core.plan_nudge import select_plan
    
    # C05-style: "Write a script ... run it with run_script ... read it back"
    plan = select_plan(
        "Write a Python script work/sq.py that prints the square of 12, "
        "run it with run_script, then read work/sq.py back and show me its contents."
    )
    assert plan is not None
    assert plan.id == "write_run_script"
    assert "workspace" in plan.steps
    assert "run_script" in plan.steps
    
    # P05-style: "Use workspace ... Then call run_script ..."
    plan = select_plan(
        "Use workspace action=write to create work/sq2.py containing exactly: print(12*12). "
        "Then call run_script on work/sq2.py. Then tell me the output."
    )
    assert plan is not None
    assert plan.id == "write_run_script"
    assert "workspace" in plan.steps
    assert "run_script" in plan.steps


@pytest.mark.asyncio
async def test_run_it_requires_script_context() -> None:
    """Issue 7 (S37b): bare 'run it' should only match RUN_SCRIPT with script context.
    
    The _RUN_IT pattern now requires the same message to also mention script
    context (.py file, 'script', or 'run_script') to avoid false positives on
    non-script phrases like 'run it by me', 'run it past the team'.
    """
    from arelis.core.intent_catalog import RUN_SCRIPT
    
    # Negative cases: "run it" without script context should NOT match
    assert not RUN_SCRIPT.matches("run it by me")
    assert not RUN_SCRIPT.matches("run it past the team tomorrow")
    assert not RUN_SCRIPT.matches("can you run it")
    assert not RUN_SCRIPT.matches("let me run it by the manager")
    assert not RUN_SCRIPT.matches("I'll run it past Legal first")
    
    # Positive cases: "run it" WITH script context SHOULD match
    assert RUN_SCRIPT.matches("write work/sq.py then run it")
    assert RUN_SCRIPT.matches("I created a script, now run it")
    assert RUN_SCRIPT.matches("after writing the .py file, run it")
    assert RUN_SCRIPT.matches("use run_script to run it")
    
    # Edge case: "run it" far from script context still matches (same message)
    assert RUN_SCRIPT.matches("I have a Python script in work/test.py. Can you run it?")
    
    # Other patterns should still work as before
    assert RUN_SCRIPT.matches("run work/hello.py")
    assert RUN_SCRIPT.matches("execute the script")
    assert RUN_SCRIPT.matches("call run_script on work/sq.py")
