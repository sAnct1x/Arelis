"""PDF assembly: merge / split / rotate under a temp workspace.

Roadmap 5.8. Tiny PDFs are built with pypdf + doc_extract's one-page fixture
so page text is extractable. The mutants this file is supposed to catch:

1. merge concatenates in the wrong order (B then A, or sorted by name).
2. split of 1-3 includes page 4 (off-by-one / slice inclusive-wrong).
3. rotate 0 or 45 is accepted.
4. path escape (`../` or an absolute outside the root) is allowed.
5. dest omitted overwrites the source.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from arelis.tools.doc_extract import build_simple_pdf_bytes
from arelis.tools.pdf_assemble import (
    MAX_FILE_BYTES,
    MAX_SOURCE_PAGES,
    PDF_WRITE_ACTIONS,
    PdfAssembleTool,
    parse_pages,
)
from arelis.workspace import RootEntry, WorkspaceRoots


def _workspace(tmp_path: Path) -> tuple[WorkspaceRoots, Path]:
    project = tmp_path / "project"
    project.mkdir()
    workspace = WorkspaceRoots([RootEntry(name="project", path=project.resolve())])
    return workspace, project


def _tool(tmp_path: Path) -> tuple[PdfAssembleTool, Path]:
    workspace, project = _workspace(tmp_path)
    return PdfAssembleTool(workspace), project


def _pdf_with_pages(path: Path, texts: list[str]) -> Path:
    writer = PdfWriter()
    for text in texts:
        reader = PdfReader(BytesIO(build_simple_pdf_bytes(text)))
        writer.add_page(reader.pages[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _page_texts(path: Path) -> list[str]:
    reader = PdfReader(str(path))
    return [(page.extract_text() or "").strip() for page in reader.pages]


def test_pages_spec_is_1_based_inclusive() -> None:
    assert parse_pages("1-3,5") == [1, 2, 3, 5]
    assert parse_pages("3,1") == [3, 1]


def test_write_actions_are_the_three_verbs() -> None:
    assert PDF_WRITE_ACTIONS == {"merge", "split", "rotate"}
    assert PdfAssembleTool.risk == "write"
    assert PdfAssembleTool.name == "pdf"


@pytest.mark.asyncio
async def test_merge_keeps_path_order(tmp_path: Path) -> None:
    """Mutant: merge writes B then A, or sorts the filenames."""
    tool, project = _tool(tmp_path)
    later = _pdf_with_pages(project / "z-last.pdf", ["ALPHA"])
    earlier = _pdf_with_pages(project / "a-first.pdf", ["BRAVO"])

    result = await tool.run(
        action="merge",
        paths=[str(later), str(earlier)],
    )
    assert result.ok, result.output
    dest = Path(result.data["abs_path"])
    assert dest.is_file()
    assert dest.parent == (project / "outputs").resolve()
    assert _page_texts(dest) == ["ALPHA", "BRAVO"]
    assert dest.resolve() != later.resolve()
    assert dest.resolve() != earlier.resolve()


@pytest.mark.asyncio
async def test_split_1_to_3_does_not_include_page_4(tmp_path: Path) -> None:
    """Mutant: pages=1-3 copies pages[0:4] or range(1, 5) and keeps PAGEFOUR."""
    tool, project = _tool(tmp_path)
    source = _pdf_with_pages(
        project / "pack.pdf",
        ["PAGEONE", "PAGETWO", "PAGETHREE", "PAGEFOUR"],
    )

    result = await tool.run(action="split", path=str(source), pages="1-3")
    assert result.ok, result.output
    dest = Path(result.data["abs_path"])
    texts = _page_texts(dest)
    assert texts == ["PAGEONE", "PAGETWO", "PAGETHREE"]
    assert "PAGEFOUR" not in "".join(texts)
    assert result.data["n_pages"] == 3
    assert _page_texts(source)[-1] == "PAGEFOUR"


@pytest.mark.asyncio
async def test_rotate_90_writes_a_new_file(tmp_path: Path) -> None:
    tool, project = _tool(tmp_path)
    source = _pdf_with_pages(project / "up.pdf", ["NORTH", "SOUTH"])
    before = source.read_bytes()

    result = await tool.run(action="rotate", path=str(source), degrees=90)
    assert result.ok, result.output
    dest = Path(result.data["abs_path"])
    assert dest.resolve() != source.resolve()
    reader = PdfReader(str(dest))
    assert [page.rotation % 360 for page in reader.pages] == [90, 90]
    assert source.read_bytes() == before
    assert _page_texts(dest) == ["NORTH", "SOUTH"]


@pytest.mark.parametrize("degrees", [0, 45, 360, -90, 1])
@pytest.mark.asyncio
async def test_rotate_rejects_non_right_angles(tmp_path: Path, degrees: int) -> None:
    """Mutant: 0 (identity) or 45 (arbitrary) is treated as a valid rotate."""
    tool, project = _tool(tmp_path)
    source = _pdf_with_pages(project / "tilt.pdf", ["ONLY"])
    before = source.read_bytes()

    result = await tool.run(action="rotate", path=str(source), degrees=degrees)
    assert not result.ok, result.output
    assert "90" in result.output
    assert source.read_bytes() == before
    outputs = project / "outputs"
    assert not outputs.exists() or not list(outputs.glob("*.pdf"))


@pytest.mark.asyncio
async def test_path_escape_is_refused(tmp_path: Path) -> None:
    """Mutant: Path(root / raw).resolve() without WorkspaceRoots.resolve_read."""
    tool, project = _tool(tmp_path)
    secret = tmp_path / "secret.pdf"
    _pdf_with_pages(secret, ["VAULT9911"])
    _pdf_with_pages(project / "inside.pdf", ["SAFE"])

    escaped = await tool.run(
        action="split",
        path="../secret.pdf",
        pages="1",
    )
    assert not escaped.ok, escaped.output
    assert "VAULT9911" not in escaped.output

    absolute = await tool.run(
        action="merge",
        paths=[str(secret)],
    )
    assert not absolute.ok, absolute.output
    assert "VAULT9911" not in absolute.output

    dest_out = tmp_path / "escaped.pdf"
    blocked = await tool.run(
        action="split",
        path="inside.pdf",
        pages="1",
        dest=str(dest_out),
    )
    assert not blocked.ok, blocked.output
    assert not dest_out.exists()


@pytest.mark.asyncio
async def test_omitted_dest_does_not_overwrite_source(tmp_path: Path) -> None:
    """Mutant: dest defaults to the source path and rotate/split clobber it."""
    tool, project = _tool(tmp_path)
    source = _pdf_with_pages(
        project / "homework.pdf",
        ["ONE", "TWO", "THREE", "FOUR"],
    )
    before = source.read_bytes()

    rotated = await tool.run(action="rotate", path="homework.pdf", degrees=180)
    assert rotated.ok, rotated.output
    dest = Path(rotated.data["abs_path"])
    assert dest.resolve() != source.resolve()
    assert dest.parent == (project / "outputs").resolve()
    assert source.read_bytes() == before
    assert PdfReader(str(source)).pages[0].rotation % 360 == 0

    split = await tool.run(action="split", path="homework.pdf", pages="1-3")
    assert split.ok, split.output
    split_dest = Path(split.data["abs_path"])
    assert split_dest.resolve() != source.resolve()
    assert source.read_bytes() == before
    assert _page_texts(source) == ["ONE", "TWO", "THREE", "FOUR"]


@pytest.mark.asyncio
async def test_explicit_dest_equal_to_source_is_refused(tmp_path: Path) -> None:
    tool, project = _tool(tmp_path)
    source = _pdf_with_pages(project / "same.pdf", ["KEEP"])
    before = source.read_bytes()

    result = await tool.run(
        action="rotate",
        path="same.pdf",
        degrees=90,
        dest="same.pdf",
    )
    assert not result.ok, result.output
    assert "overwrite" in result.output.lower()
    assert source.read_bytes() == before


@pytest.mark.asyncio
async def test_explicit_dest_under_workspace_is_used(tmp_path: Path) -> None:
    tool, project = _tool(tmp_path)
    _pdf_with_pages(project / "a.pdf", ["A"])
    _pdf_with_pages(project / "b.pdf", ["B"])

    result = await tool.run(
        action="merge",
        paths="a.pdf,b.pdf",
        dest="outputs/stack.pdf",
    )
    assert result.ok, result.output
    dest = project / "outputs" / "stack.pdf"
    assert dest.is_file()
    assert Path(result.data["abs_path"]) == dest.resolve()
    assert _page_texts(dest) == ["A", "B"]


@pytest.mark.asyncio
async def test_page_cap_refuses_a_fat_merge(tmp_path: Path) -> None:
    tool, project = _tool(tmp_path)
    writer = PdfWriter()
    for _ in range(MAX_SOURCE_PAGES + 1):
        writer.add_blank_page(width=72, height=72)
    fat = project / "fat.pdf"
    with fat.open("wb") as handle:
        writer.write(handle)

    result = await tool.run(action="merge", paths="fat.pdf")
    assert not result.ok, result.output
    assert str(MAX_SOURCE_PAGES) in result.output
    outputs = project / "outputs"
    assert not outputs.exists() or not list(outputs.glob("*.pdf"))


@pytest.mark.asyncio
async def test_file_size_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool, project = _tool(tmp_path)
    source = _pdf_with_pages(project / "chunky.pdf", ["BIG"])
    monkeypatch.setattr(
        "arelis.tools.pdf_assemble.MAX_FILE_BYTES",
        max(1, source.stat().st_size - 1),
    )

    result = await tool.run(action="split", path="chunky.pdf", pages="1")
    assert not result.ok, result.output
    assert "MB" in result.output or "over" in result.output.lower()


@pytest.mark.asyncio
async def test_form_fill_is_not_an_action(tmp_path: Path) -> None:
    tool, _project = _tool(tmp_path)
    for action in ("fill", "write", "form"):
        result = await tool.run(action=action, path="x.pdf")
        assert not result.ok
        assert "form fill" in result.output.lower()


def test_max_caps_are_the_ones_the_description_claims() -> None:
    assert MAX_SOURCE_PAGES == 50
    assert MAX_FILE_BYTES == 8 * 1024 * 1024
