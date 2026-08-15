"""Unit tests for local PDF doc_extract (T4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.core.evidence import EvidenceLedger
from arelis.core.skills import select_skill_ids
from arelis.tools.doc_extract import DocExtractTool, build_simple_pdf_bytes
from arelis.workspace import WorkspaceRoots

FIXTURES = Path(__file__).parent / "fixtures"
QUOTE_PDF = FIXTURES / "quote.pdf"
QUOTE_TEXT = "Arelis fixture quote ALPHA"


def _ensure_fixture() -> Path:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    if not QUOTE_PDF.exists():
        QUOTE_PDF.write_bytes(build_simple_pdf_bytes(QUOTE_TEXT))
    return QUOTE_PDF


@pytest.fixture
def workspace(tmp_path: Path) -> WorkspaceRoots:
    root = tmp_path / "proj"
    root.mkdir()
    fixture = _ensure_fixture()
    target = root / "quote.pdf"
    target.write_bytes(fixture.read_bytes())
    return WorkspaceRoots.from_paths([str(root)])


@pytest.mark.asyncio
async def test_doc_extract_reads_fixture_text(workspace: WorkspaceRoots) -> None:
    tool = DocExtractTool(workspace)
    result = await tool.run(path="quote.pdf")
    assert result.ok, result.output
    assert QUOTE_TEXT in result.output
    assert result.data["path"] == "quote.pdf"
    assert result.data["pages"] == [1]
    assert result.data["chars"] >= len(QUOTE_TEXT)


@pytest.mark.asyncio
async def test_doc_extract_page_range(workspace: WorkspaceRoots) -> None:
    tool = DocExtractTool(workspace)
    result = await tool.run(path="quote.pdf", page_start=1, page_end=1)
    assert result.ok, result.output
    assert result.data["pages"] == [1]


@pytest.mark.asyncio
async def test_doc_extract_refuses_path_escape(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "secret.pdf"
    outside.write_bytes(build_simple_pdf_bytes("SECRET"))
    ws = WorkspaceRoots.from_paths([str(root)])
    tool = DocExtractTool(ws)
    result = await tool.run(path="../secret.pdf")
    assert not result.ok
    assert "outside allowed workspace roots" in result.output.lower() or "[fail:" in result.output


@pytest.mark.asyncio
async def test_doc_extract_empty_page_fail_tag(tmp_path: Path) -> None:
    from pypdf import PdfWriter

    root = tmp_path / "proj"
    root.mkdir()
    blank = root / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with blank.open("wb") as fh:
        writer.write(fh)
    tool = DocExtractTool(WorkspaceRoots.from_paths([str(root)]))
    result = await tool.run(path="blank.pdf")
    assert not result.ok
    assert "[fail:empty]" in result.output
    assert result.data.get("fail_class") == "fail:empty"


@pytest.mark.asyncio
async def test_doc_extract_encrypted_fail_tag(tmp_path: Path) -> None:
    from pypdf import PdfWriter

    root = tmp_path / "proj"
    root.mkdir()
    locked = root / "locked.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("not-the-empty-password")
    with locked.open("wb") as fh:
        writer.write(fh)
    tool = DocExtractTool(WorkspaceRoots.from_paths([str(root)]))
    result = await tool.run(path="locked.pdf")
    assert not result.ok
    assert "[fail:encrypted]" in result.output


def test_evidence_maps_doc_extract_warrant() -> None:
    ledger = EvidenceLedger()
    ledger.record_tool(
        "doc_extract",
        ok=True,
        output="path: note.pdf\nArelis fixture quote ALPHA",
        data={"path": "note.pdf", "pages": [1], "chars": 26},
        args={"path": "note.pdf"},
    )
    assert ledger.has_ok("doc")
    assert any(w.kind == "doc" and "note.pdf" in w.source for w in ledger.items)


def test_docs_skill_card_selected_for_pdf_ask() -> None:
    ids = select_skill_ids(
        "What does this PDF say on page 1?",
        available_tools={"doc_extract", "workspace", "analyze"},
    )
    assert "docs" in ids
