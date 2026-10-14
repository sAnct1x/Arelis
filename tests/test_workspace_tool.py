import io
import zipfile
from pathlib import Path

import pytest

from arelis.tools.code_workspace import CodeWorkspaceTool


@pytest.mark.asyncio
async def test_workspace_write_read(tmp_path):
    tool = CodeWorkspaceTool([str(tmp_path)])
    target = tmp_path / "note.txt"
    w = await tool.run(action="write", path=str(target), content="hello arelis")
    assert w.ok
    r = await tool.run(action="read", path=str(target))
    assert r.ok
    assert "hello arelis" in r.output


@pytest.mark.asyncio
async def test_workspace_list_edit_and_python_file(tmp_path):
    tool = CodeWorkspaceTool([str(tmp_path)])
    py = tmp_path / "hello.py"
    written = await tool.run(
        action="write",
        path=str(py),
        content="def n():\n    return 1\n",
    )
    assert written.ok
    listed = await tool.run(action="list", path=".")
    assert listed.ok
    assert "hello.py" in listed.output
    edited = await tool.run(
        action="edit",
        path=str(py),
        old="return 1",
        new="return 2",
    )
    assert edited.ok
    read_back = await tool.run(action="read", path=str(py))
    assert read_back.ok
    assert "return 2" in read_back.output
    assert "return 1" not in read_back.output


def _zip_office(path: Path, member: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(member, body)
    path.write_bytes(buf.getvalue())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "member"),
    [
        ("work/memo.docx", "word/document.xml"),
        ("work/sheet.xlsx", "xl/workbook.xml"),
        ("work/deck.pptx", "ppt/slides/slide1.xml"),
    ],
)
async def test_read_refuses_office_containers(tmp_path: Path, name: str, member: str) -> None:
    """A docx is a zip. ok=True used to hand the model the raw PK bytes."""
    tool = CodeWorkspaceTool([str(tmp_path)])
    _zip_office(tmp_path / name, member, "<document>Project codename: FALCON-77</document>")
    result = await tool.run(action="read", path=name)
    assert result.ok is False
    assert "doc_extract" in result.output
    assert f"path={name}" in result.output
    assert not result.output.startswith("PK")


@pytest.mark.asyncio
async def test_read_refuses_a_pdf_that_has_no_nul(tmp_path: Path) -> None:
    """A short PDF can look like text. The suffix still has to refuse it."""
    tool = CodeWorkspaceTool([str(tmp_path)])
    pdf = tmp_path / "notes.pdf"
    pdf.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n")
    result = await tool.run(action="read", path="notes.pdf")
    assert result.ok is False
    assert "doc_extract" in result.output
    assert "path=notes.pdf" in result.output
    assert not result.output.startswith("%PDF")


@pytest.mark.asyncio
async def test_read_refuses_other_binaries_without_doc_extract(tmp_path: Path) -> None:
    """A png is not text, and doc_extract cannot read it."""
    tool = CodeWorkspaceTool([str(tmp_path)])
    blob = tmp_path / "shot.png"
    blob.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    result = await tool.run(action="read", path="shot.png")
    assert result.ok is False
    assert result.output == "shot.png is not text."
    assert "doc_extract" not in result.output
    assert "next_tool" not in (result.data or {})


@pytest.mark.asyncio
async def test_read_still_returns_plain_text(tmp_path: Path) -> None:
    tool = CodeWorkspaceTool([str(tmp_path)])
    note = tmp_path / "work" / "memo.txt"
    note.parent.mkdir()
    note.write_text("Project codename: FALCON-77\n", encoding="utf-8")
    result = await tool.run(action="read", path="work/memo.txt")
    assert result.ok is True
    assert "FALCON-77" in result.output
