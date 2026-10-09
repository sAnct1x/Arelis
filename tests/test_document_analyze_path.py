"""The path a document reports has to open in analyze."""

from __future__ import annotations

import asyncio

from arelis.tools.analyze import AnalyzeTool
from arelis.tools.document import DocumentTool
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
