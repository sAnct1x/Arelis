"""Last-file memory for documents — open that / email that / export that."""

from __future__ import annotations

from pathlib import Path

from arelis.core.document_refs import (
    detect_document_another,
    detect_document_export,
    detect_document_revise,
    fill_doc_extract_args,
    fill_document_args,
    latest_document_path,
    match_open_last_document,
    mentions_recent_document,
)


def test_open_that_is_narrow() -> None:
    assert match_open_last_document("open that")
    assert match_open_last_document("open it")
    assert match_open_last_document("open the file")
    assert match_open_last_document("show that in explorer")
    assert not match_open_last_document("open the physics room")
    assert not match_open_last_document("open youtube")


def test_revise_and_another() -> None:
    assert detect_document_revise("fix section 3")
    assert detect_document_revise("make it longer")
    assert detect_document_export("export that as a pdf")
    assert detect_document_another("make another pdf")
    assert not detect_document_revise("make another pdf")


def test_fill_replace_from_last_file(tmp_path: Path) -> None:
    dest = tmp_path / "dirac.md"
    dest.write_text("# Dirac\n", encoding="utf-8")
    receipts = [{"tool": "document", "abs_path": str(dest), "path": str(dest)}]
    filled = fill_document_args(
        {"format": "pdf"},
        user_text="export that as a pdf",
        receipts=receipts,
    )
    assert filled["replace"] == "true"
    assert filled["from_path"] == str(dest.resolve())
    assert filled["filename"].startswith("dirac.")


def test_writing_room_defaults_to_markdown() -> None:
    filled = fill_document_args({}, user_text="write this up", room_kind="writing")
    assert filled["format"] == "md"


def test_latest_path_and_extract(tmp_path: Path) -> None:
    pdf = tmp_path / "note.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    receipts = [{"tool": "document", "abs_path": str(pdf)}]
    assert Path(latest_document_path(receipts=receipts)).name == "note.pdf"
    filled = fill_doc_extract_args(
        {},
        user_text="what does that document say",
        receipts=receipts,
    )
    assert Path(filled["path"]).name == "note.pdf"
    assert mentions_recent_document("what does that document say")
