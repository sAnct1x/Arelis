"""The path a document reports has to open in analyze."""

from __future__ import annotations

import asyncio
from pathlib import Path

from arelis.tools.analyze import AnalyzeTool
from arelis.tools.document import DocumentTool
from arelis.tools.plot import PlotTool
from arelis.workspace import WorkspaceRoots


def test_analyze_summarizes_the_csv_path_document_reports(tmp_path, monkeypatch) -> None:
    data = tmp_path / "data"
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setenv("ARELIS_DATA_DIR", str(data))

    writer = DocumentTool(WorkspaceRoots.from_paths([str(project)]))
    written = asyncio.run(
        writer.run(
            format="csv",
            filename="mini.csv",
            rows='[["fruit","price"],["apple","1.00"],["pear","2.00"],["plum","3.00"]]',
        )
    )
    assert written.ok, written.output
    reported = str((written.data or {}).get("path") or "")
    assert reported

    reader = AnalyzeTool(WorkspaceRoots.from_paths([str(project)]))
    summary = reader._analyze(reported, "summary", 5)
    assert summary.ok, summary.output
    assert "fruit" in summary.output
    assert "price" in summary.output
    assert "3 rows" in summary.output

    outside = tmp_path / "secret.csv"
    outside.write_text("secret,yes\n1,1\n", encoding="utf-8")
    escaped = reader._analyze("outputs/documents/../../secret.csv", "summary", 5)
    assert escaped.ok is False or "secret" not in escaped.output


def test_analyze_and_plot_open_drop_csv_via_workspace_path(
    tmp_path, monkeypatch
) -> None:
    """C19: document writes mini.csv, then analyze/plot are called with work/mini.csv.

    Workspace resolve joins that onto the project and used to miss the drop-tray
    file, so both tools returned ok=False even though mini.csv existed.
    """
    data = tmp_path / "data"
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setenv("ARELIS_DATA_DIR", str(data))
    roots = WorkspaceRoots.from_paths([str(project)])

    wrote = asyncio.run(
        DocumentTool(roots).run(
            format="csv",
            filename="mini.csv",
            rows="x,y\n1,2\n2,4\n3,6",
            replace=True,
        )
    )
    assert wrote.ok, wrote.output
    assert not (project / "work" / "mini.csv").exists()

    summed = AnalyzeTool(roots)._analyze(
        "work/mini.csv", "query", 5, {"on": "y", "agg": "sum"}
    )
    assert summed.ok, summed.output
    assert "12" in summed.output

    chart = asyncio.run(
        PlotTool(roots).run(action="line", path="work/mini.csv", x="x", y="y")
    )
    assert chart.ok, chart.output
    assert Path(chart.data["abs_path"]).is_file()
