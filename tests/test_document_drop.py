"""Drop-tray files live under outputs/documents, often outside workspace roots."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from arelis.core.document_refs import fill_doc_extract_args, resolve_drop_file
from arelis.tools.analyze import AnalyzeTool
from arelis.workspace import WorkspaceRoots


def _outside_drop_name(docs: Path, outside: Path) -> str:
    """Plant a drop-tray name whose realpath sits outside documents."""
    link = docs / "evil.csv"
    try:
        link.symlink_to(outside)
        return link.name
    except OSError:
        pass
    boxed = outside.parent / "boxed"
    boxed.mkdir(exist_ok=True)
    secret = boxed / "secret.csv"
    secret.write_text(outside.read_text(encoding="utf-8"), encoding="utf-8")
    junction = docs / "outbox"
    if sys.platform == "win32":
        made = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(boxed)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert made.returncode == 0, made.stderr
    else:
        junction.symlink_to(boxed, target_is_directory=True)
    return secret.name


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

    target.unlink()
    one = docs / "inbox" / "board-check.csv"
    two = docs / "archive" / "board-check.csv"
    one.parent.mkdir()
    two.parent.mkdir()
    one.write_text("a,b\n1,2\n", encoding="utf-8")
    two.write_text("a,b\n3,4\n", encoding="utf-8")
    with pytest.raises(ValueError, match="more than one drop file") as caught:
        resolve_drop_file("board-check.csv", suffixes={".csv"})
    msg = str(caught.value)
    assert "inbox/board-check.csv" in msg
    assert "archive/board-check.csv" in msg
    assert str(one.resolve()) not in msg
    assert str(two.resolve()) not in msg
    picked = resolve_drop_file("inbox/board-check.csv", suffixes={".csv"})
    assert Path(picked).resolve() == one.resolve()

    decoy = docs / "mini.csv"
    decoy.write_text("a,b\n0,0\n", encoding="utf-8")
    outside = tmp_path / "secret.csv"
    outside.write_text("secret,yes\n1,1\n", encoding="utf-8")
    sneak = _outside_drop_name(docs, outside)
    assert not resolve_drop_file(sneak, suffixes={".csv"})
    assert not resolve_drop_file("../secret.csv", suffixes={".csv"})
    assert not resolve_drop_file(str(outside), suffixes={".csv"})
    assert not resolve_drop_file(r"C:\Users\you\secret.csv", suffixes={".csv"})
    assert not resolve_drop_file(r"\\server\share\secret.csv", suffixes={".csv"})
    assert not resolve_drop_file("no-such.csv", suffixes={".csv"})
    via_workspace = resolve_drop_file("work/mini.csv", suffixes={".csv"})
    assert Path(via_workspace).resolve() == decoy.resolve()


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
