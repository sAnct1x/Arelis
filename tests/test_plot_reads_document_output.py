"""Fail-first: plot must open the path document reports (10Q Q4, bench C19)."""
from __future__ import annotations

import asyncio
from pathlib import Path

from arelis.tools.document import DocumentTool
from arelis.tools.plot import PlotTool
from arelis.workspace import RootEntry, WorkspaceRoots


def _roots(tmp_path: Path) -> WorkspaceRoots:
    root = tmp_path / "proj"
    root.mkdir()
    return WorkspaceRoots([RootEntry(name="proj", path=root.resolve())])


def test_plot_line_reads_csv_written_by_document(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    wrote = asyncio.run(DocumentTool(roots).run(
        format="csv", title="plants", filename="plants_c19",
        rows="day,height\n1,2.0\n2,2.6\n3,3.1\n4,3.9", replace=True,
    ))
    assert wrote.ok, wrote.output
    reported = wrote.data["path"]
    assert reported.startswith("outputs/documents/"), reported
    out = asyncio.run(PlotTool(roots).run(action="line", path=reported, x="day", y="height"))
    assert out.ok, out.output
    assert Path(out.data["abs_path"]).is_file()


def test_plot_bar_reads_csv_written_by_document(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    wrote = asyncio.run(DocumentTool(roots).run(
        format="csv", title="fruit", filename="fruit_c19",
        rows="name,count\napple,1\npear,5\nfig,10", replace=True,
    ))
    assert wrote.ok, wrote.output
    out = asyncio.run(PlotTool(roots).run(action="bar", path=wrote.data["path"], x="name", y="count"))
    assert out.ok, out.output


def test_plot_refuses_a_document_path_that_climbs_out(tmp_path, monkeypatch) -> None:
    """A .. climb out of the drop tray must not open the file it lands on."""
    data = tmp_path / "data"
    (data / "outputs" / "documents").mkdir(parents=True)
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setenv("ARELIS_DATA_DIR", str(data))
    escape = data / "escape.csv"
    escape.write_text("day,height\n1,2.0\n2,2.6\n", encoding="utf-8")
    climbed = (data / "outputs" / "documents" / ".." / ".." / "escape.csv").resolve()
    assert climbed == escape.resolve()
    assert climbed.is_file()
    roots = WorkspaceRoots([RootEntry(name="proj", path=project.resolve())])
    out = asyncio.run(
        PlotTool(roots).run(
            action="line",
            path="outputs/documents/../../escape.csv",
            x="day",
            y="height",
        )
    )
    assert out.ok is False
