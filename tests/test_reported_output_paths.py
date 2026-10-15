"""The path document and research_report return has to open in the file tools.

Those tools write under the data folder (outputs/documents, outputs/research)
and name the file from that root. pdf, workspace, and doc_extract join a
relative path onto the workspace. When the two roots differ, the returned
path comes back as not found. Traversal and paths outside both the workspace
and those output folders stay refused, and a write still cannot land in the
data folder by reusing the reported path.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from arelis.paths import display_path
from arelis.tools.base import ToolResult
from arelis.tools.code_workspace import CodeWorkspaceTool
from arelis.tools.doc_extract import DocExtractTool, build_simple_pdf_bytes
from arelis.tools.document import DocumentTool
from arelis.tools.pdf_assemble import PdfAssembleTool
from arelis.tools.research_report import ResearchReportTool
from arelis.workspace import RootEntry, WorkspaceRoots

_PDF_MARKER = "Marker 4419 lives in this pdf."
_REPORT_MARKER = "The codename is FALCON-77."
_VAULT = "VAULT9911"
_DATA_SECRET = "DATASECRET8821"


def _split(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, WorkspaceRoots]:
    """Data folder and workspace folder as siblings, the installed layout."""
    data = tmp_path / "data"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("ARELIS_DATA_DIR", str(data))
    roots = WorkspaceRoots([RootEntry(name="project", path=project.resolve())])
    return data, project, roots


def _page(path: Path, text: str) -> None:
    writer = PdfWriter()
    reader = PdfReader(BytesIO(build_simple_pdf_bytes(text)))
    writer.add_page(reader.pages[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        writer.write(handle)


def _texts(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


async def _search(**kwargs: object) -> ToolResult:
    del kwargs
    return ToolResult(
        ok=True,
        output="URL: https://example.com/src",
        data={
            "results": [
                {
                    "url": "https://example.com/src",
                    "title": "Source",
                }
            ]
        },
    )


async def _scrape(**kwargs: object) -> ToolResult:
    return ToolResult(
        ok=True,
        output=_REPORT_MARKER,
        data={"title": "Source", "url": kwargs.get("url") or "https://example.com/src"},
    )


@pytest.mark.asyncio
async def test_document_path_opens_in_pdf_workspace_and_doc_extract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reported pdf path opens in pdf and doc_extract.

    workspace read of that same path must not return the bytes as text.
    It refuses and names doc_extract, once the file has been found.
    """
    data, project, roots = _split(tmp_path, monkeypatch)
    wrote = await DocumentTool(roots).run(
        format="pdf",
        title="Conversion Source",
        body=_PDF_MARKER,
    )
    assert wrote.ok, wrote.output
    reported = str((wrote.data or {})["path"])
    assert reported.startswith("outputs/documents/"), reported
    assert reported in wrote.output
    real = Path(str((wrote.data or {})["abs_path"]))
    assert real.is_file()
    assert data in real.parents
    assert project not in real.parents

    split = await PdfAssembleTool(roots).run(action="split", path=reported, pages="1")
    assert split.ok, split.output
    dest = Path(str((split.data or {})["abs_path"]))
    assert _PDF_MARKER in _texts(dest)
    assert dest.resolve() != real.resolve()
    assert project in dest.parents

    listed = await CodeWorkspaceTool(roots).run(action="list", path=reported)
    assert listed.ok, listed.output
    assert "Not found" not in listed.output
    assert Path(str((listed.data or {})["abs_path"])).resolve() == real.resolve()

    read = await CodeWorkspaceTool(roots).run(action="read", path=reported)
    assert read.ok is False
    assert "is not text" in read.output
    assert "Call doc_extract path=" in read.output
    assert _PDF_MARKER not in read.output
    assert not read.output.startswith("%PDF")
    assert (read.data or {}).get("next_tool") == "doc_extract"
    assert Path(str((read.data or {})["abs_path"])).resolve() == real.resolve()
    named = read.output.split("path=", 1)[1].strip().rstrip(".")
    pointed = await DocExtractTool(roots).run(path=named)
    assert pointed.ok, pointed.output
    assert "4419" in pointed.output

    extracted = await DocExtractTool(roots).run(path=reported)
    assert extracted.ok, extracted.output
    assert "4419" in extracted.output


@pytest.mark.asyncio
async def test_research_report_path_opens_in_workspace_pdf_and_doc_extract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail-before: the path research_report returns is outside the workspace."""
    _data, project, roots = _split(tmp_path, monkeypatch)
    report = ResearchReportTool(_search, _scrape, max_sources=1)
    wrote = await report.run(query="where the marker lives")
    assert wrote.ok, wrote.output
    reported = str((wrote.data or {})["path"])
    assert reported in wrote.output
    real = Path(reported)
    assert real.is_file()
    assert project not in real.resolve().parents
    assert _REPORT_MARKER in real.read_text(encoding="utf-8")

    read = await CodeWorkspaceTool(roots).run(action="read", path=reported)
    assert read.ok, read.output
    assert _REPORT_MARKER in read.output
    assert Path(str((read.data or {})["abs_path"])).resolve() == real.resolve()

    shown = display_path(real)
    assert shown.startswith("outputs/research/"), shown
    by_data_path = await CodeWorkspaceTool(roots).run(action="read", path=shown)
    assert by_data_path.ok, by_data_path.output
    assert _REPORT_MARKER in by_data_path.output

    listed = await CodeWorkspaceTool(roots).run(action="list", path=reported)
    assert listed.ok, listed.output
    assert Path(str((listed.data or {})["abs_path"])).resolve() == real.resolve()

    # The file is markdown. Finding it is the fix; pdf still refuses the type.
    as_pdf = await PdfAssembleTool(roots).run(action="split", path=reported, pages="1")
    assert as_pdf.ok is False
    assert "not a PDF" in as_pdf.output
    assert "No PDF" not in as_pdf.output

    extracted = await DocExtractTool(roots).run(path=reported)
    assert extracted.ok is False
    assert "Unsupported file type" in extracted.output
    assert ".md" in extracted.output

    follow = await DocumentTool(roots).run(
        format="pdf",
        title="From the report",
        from_path=reported,
    )
    assert follow.ok, follow.output
    follow_path = Path(str((follow.data or {})["abs_path"]))
    assert _REPORT_MARKER in _texts(follow_path)


@pytest.mark.asyncio
async def test_traversal_and_outside_paths_stay_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data, _project, roots = _split(tmp_path, monkeypatch)
    vault = tmp_path / "vault.pdf"
    nested = data / "secret.pdf"
    _page(vault, _VAULT)
    _page(nested, _DATA_SECRET)
    assert vault.is_file() and nested.is_file()

    climbs = (
        "outputs/documents/../../vault.pdf",
        "outputs/documents/../../secret.pdf",
        "outputs/research/../../../vault.pdf",
        "outputs/documents/foo/../../../secret.pdf",
    )
    pdf = PdfAssembleTool(roots)
    workspace = CodeWorkspaceTool(roots)
    extract = DocExtractTool(roots)
    for climb in climbs:
        for result in (
            await pdf.run(action="split", path=climb, pages="1"),
            await workspace.run(action="read", path=climb),
            await workspace.run(action="list", path=climb),
            await extract.run(path=climb),
        ):
            assert result.ok is False, (climb, result.output)
            assert _VAULT not in result.output
            assert _DATA_SECRET not in result.output

    escape = data / "escape.md"
    escape.write_text(_DATA_SECRET + "\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        DocumentTool(roots)._read_source("outputs/documents/../../escape.md")
    assert _DATA_SECRET not in str(exc.value)
    assert "allowed root" in str(exc.value)

    for outside in (str(vault), str(nested)):
        for result in (
            await pdf.run(action="split", path=outside, pages="1"),
            await workspace.run(action="read", path=outside),
            await workspace.run(action="list", path=outside),
            await extract.run(path=outside),
        ):
            assert result.ok is False, (outside, result.output)
            assert _VAULT not in result.output
            assert _DATA_SECRET not in result.output
            assert "outside" in result.output.lower() or "allowed" in result.output.lower()


