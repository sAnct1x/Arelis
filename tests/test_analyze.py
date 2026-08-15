"""AnalyzeTool — real CSV/JSON tables under a temp root."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.tools.analyze import AnalyzeTool


@pytest.mark.asyncio
async def test_analyze_csv_summary_head_describe(tmp_path: Path) -> None:
    table = tmp_path / "sales.csv"
    table.write_text("item,qty,price\na,2,1.5\nb,3,2.0\n", encoding="utf-8")
    tool = AnalyzeTool([str(tmp_path)])

    summary = await tool.run(path=str(table), action="summary")
    assert summary.ok
    assert "2 rows" in summary.output
    assert "item" in summary.output

    head = await tool.run(path=str(table), action="head", rows=1)
    assert head.ok
    assert "a" in head.output

    describe = await tool.run(path=str(table), action="describe")
    assert describe.ok
    assert "qty" in describe.output or "price" in describe.output


@pytest.mark.asyncio
async def test_analyze_json_and_bad_action(tmp_path: Path) -> None:
    rows = tmp_path / "rows.json"
    rows.write_text('[{"x": 1}, {"x": 2}]', encoding="utf-8")
    tool = AnalyzeTool([str(tmp_path)])
    result = await tool.run(path=str(rows), action="summary")
    assert result.ok
    assert "2 rows" in result.output

    bad = await tool.run(path=str(rows), action="explode")
    assert not bad.ok
    missing = await tool.run(action="summary")
    assert not missing.ok


@pytest.mark.asyncio
async def test_the_wrong_file_type_names_the_tool_that_can_read_it(
    tmp_path: Path,
) -> None:
    """The user says "analyze" about photos and PDFs, so this path gets walked.

    "Unsupported file type: .png" is a dead end; naming vision turns it into one
    more round.
    """
    tool = AnalyzeTool([str(tmp_path)])

    for name, wanted in (
        ("shot.png", "vision"),
        ("photo.jpg", "vision"),
        ("report.pdf", "doc_extract"),
        ("notes.md", "workspace"),
    ):
        target = tmp_path / name
        target.write_bytes(b"not really a table")
        result = await tool.run(path=str(target))
        assert not result.ok, name
        assert wanted in result.output, f"{name} should point at {wanted}: {result.output}"


def test_the_description_admits_it_only_reads_tables() -> None:
    text = AnalyzeTool.description.lower()
    assert "vision" in text and "doc_extract" in text
    for fmt in ("csv", "excel"):
        assert fmt in text
