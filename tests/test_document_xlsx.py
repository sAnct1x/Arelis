"""document format=xlsx: real cells, live formulas, charts, and safe edits."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Font
from openpyxl.worksheet.table import Table

from arelis.core.plan_nudge import select_plan
from arelis.tools.document import DocumentTool


@pytest.fixture
def docs(tmp_path, monkeypatch):
    data = tmp_path / "data"
    outputs = data / "outputs"
    (outputs / "documents").mkdir(parents=True)
    import arelis.paths as paths_mod
    import arelis.tools.document as document_mod

    monkeypatch.setattr(paths_mod, "user_data_dir", lambda: data)
    monkeypatch.setattr(paths_mod, "outputs_dir", lambda: outputs)
    monkeypatch.setattr(document_mod, "user_data_dir", lambda: data, raising=False)
    monkeypatch.setattr(document_mod, "outputs_dir", lambda: outputs)
    return DocumentTool(), outputs / "documents"


def _lab_book(path) -> None:
    book = Workbook()
    runs = book.active
    runs.title = "Runs"
    for row in (["Run", "Temp (K)", "Flux"], [1, 300.5, 12], [2, 310.25, 14]):
        runs.append(row)
    runs["A1"].font = Font(bold=True, color="FFFF0000")
    runs["C3"].number_format = "0.0"
    runs["E1"] = "=SUM(C2:C3)"
    runs.add_table(Table(displayName="RunsT", ref="A1:C3"))
    chart = BarChart()
    chart.add_data(Reference(runs, min_col=3, min_row=1, max_row=3), titles_from_data=True)
    runs.add_chart(chart, "G2")
    book.create_sheet("Notes")["A1"] = "keep me"
    book.save(path)


async def test_new_sheet_has_typed_cells_live_formulas_and_a_chart(docs) -> None:
    tool, _folder = docs
    rows = [
        ["Month", "Revenue ($)", "Share"],
        ["2026-01-01", "$1,200.50", "12.5%"],
        ["2026-02-01", "1350", "=B3/SUM(B2:B3)"],
        ["Total", "=SUM(B2:B3)", "=STDEV.S(B2:B3)"],
    ]
    result = await tool.run(
        format="xlsx",
        title="Q1",
        rows=json.dumps(rows),
        body="chart: line x=A y=B Revenue\nformat: B=#,##0.00",
    )
    assert result.ok, result.output
    book = load_workbook(result.data["abs_path"])
    sheet = book["Q1"]
    assert sheet["B2"].value == 1200.5 and sheet["C2"].value == 0.125
    assert sheet["C2"].number_format == "0.0%" and sheet["B2"].number_format == "#,##0.00"
    assert sheet["B4"].value == "=SUM(B2:B3)"
    assert sheet["C4"].value == "=_xlfn.STDEV.S(B2:B3)"
    assert sheet["A1"].font.b and sheet.freeze_panes == "A2"
    assert len(sheet._charts) == 1
    assert book.calculation.fullCalcOnLoad
    assert "3 formula(s)" in result.output


async def test_edit_writes_a_copy_and_keeps_the_rest_of_the_workbook(docs) -> None:
    tool, folder = docs
    source = folder / "lab.xlsx"
    _lab_book(source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    result = await tool.run(
        format="xlsx",
        from_path=str(source),
        rows=json.dumps([["Run", "Temp (K)", "Flux"], [3, "320.125", "=C3+2"]]),
    )
    assert result.ok, result.output
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    edited = load_workbook(result.data["abs_path"])
    runs = edited["Runs"]
    assert edited.sheetnames == ["Runs", "Notes"]
    assert edited["Notes"]["A1"].value == "keep me"
    assert [c.value for c in runs[4]][:3] == [3, 320.125, "=C3+2"]
    assert runs["C4"].number_format == "0.0"
    assert runs["A1"].font.color.rgb == "FFFF0000"
    assert runs["E1"].value == "=SUM(C2:C3)"
    assert runs.tables["RunsT"].ref == "A1:C4"
    assert len(runs._charts) == 1

    again = await tool.run(
        format="xlsx",
        from_path=str(source),
        filename="lab.xlsx",
        replace="true",
        rows='[["Notes!B2", "checked"]]',
    )
    assert again.ok, again.output
    assert load_workbook(source)["Notes"]["B2"].value == "checked"
    backup = again.data["backup"]
    assert backup and hashlib.sha256(Path(backup).read_bytes()).hexdigest() == before


async def test_edit_refuses_when_saving_would_drop_content(docs) -> None:
    tool, folder = docs
    plain = folder / "plain.xlsx"
    _lab_book(plain)
    threaded = folder / "threaded.xlsx"
    with zipfile.ZipFile(plain) as src, zipfile.ZipFile(threaded, "w") as out:
        for item in src.infolist():
            out.writestr(item, src.read(item.filename))
        out.writestr("xl/threadedComments/threadedComment1.xml", "<ThreadedComments/>")
    result = await tool.run(format="xlsx", from_path=str(threaded), rows='[["A9", "x"]]')
    assert not result.ok
    assert "threaded comments" in result.output
    assert sorted(p.name for p in folder.iterdir()) == ["plain.xlsx", "threaded.xlsx"]


def test_spreadsheet_ask_gets_the_sheet_plan() -> None:
    sheet = select_plan("make me a spreadsheet of Q1 revenue with a chart")
    pdf = select_plan("create a pdf about the transit")
    assert sheet is not None and "chart: line" in sheet.message
    assert pdf is not None and "chart:" not in pdf.message
