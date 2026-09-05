"""Drop-tray files live under outputs/documents, often outside workspace roots."""

from __future__ import annotations

from pathlib import Path

from arelis.core.document_refs import fill_doc_extract_args, resolve_drop_file
from arelis.tools.analyze import AnalyzeTool
from arelis.workspace import WorkspaceRoots


def test_resolve_drop_file_finds_basename(tmp_path, monkeypatch) -> None:
    from arelis.core import document_refs

    docs = tmp_path / "documents"
    docs.mkdir()
    target = docs / "board-check.csv"
    target.write_text("a,b\n1,2\n", encoding="utf-8")
    monkeypatch.setattr(document_refs, "outputs_dir", lambda: tmp_path)

    hit = resolve_drop_file("board-check.csv", suffixes={".csv"})
    assert hit
    assert Path(hit).name == "board-check.csv"


def test_analyze_reads_drop_tray_outside_roots(tmp_path, monkeypatch) -> None:
    from arelis.core import document_refs

    project = tmp_path / "proj"
    project.mkdir()
    docs = tmp_path / "outputs" / "documents"
    docs.mkdir(parents=True)
    csv = docs / "f50-check.csv"
    csv.write_text("check,token\n1,F50\n", encoding="utf-8")
    monkeypatch.setattr(document_refs, "outputs_dir", lambda: tmp_path / "outputs")

    tool = AnalyzeTool(WorkspaceRoots.from_paths([str(project)]))
    result = tool._analyze(str(csv), "summary", 5)
    assert result.ok, result.output
    assert "check" in result.output


def test_doc_extract_prefers_newer_drop_pdf(tmp_path, monkeypatch) -> None:
    from arelis.core import document_refs

    docs = tmp_path / "documents"
    docs.mkdir()
    old = docs / "yesterday.pdf"
    new = docs / "tonight.pdf"
    old.write_bytes(b"%PDF-1.4 old")
    new.write_bytes(b"%PDF-1.4 new")
    old.touch()
    import time

    time.sleep(0.05)
    new.touch()
    monkeypatch.setattr(document_refs, "outputs_dir", lambda: tmp_path)

    filled = fill_doc_extract_args(
        {},
        user_text="quote from the pdf you made of that board note",
        history=[],
        receipts=[],
    )
    assert Path(str(filled.get("path") or "")).name == "tonight.pdf"
