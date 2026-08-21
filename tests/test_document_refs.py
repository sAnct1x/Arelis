"""Last-file memory for documents — open that / email that / export that."""

from __future__ import annotations

from pathlib import Path

from arelis.core.document_refs import (
    _PATH_MENTION,
    detect_document_another,
    detect_document_export,
    detect_document_revise,
    files_in_turn,
    fill_doc_extract_args,
    fill_document_args,
    latest_document_path,
    latest_openable_path,
    match_open_last_document,
    match_reveal_last_document,
    mentions_recent_document,
)


def test_open_that_is_narrow() -> None:
    assert match_open_last_document("open that")
    assert match_open_last_document("open it")
    assert match_open_last_document("open the file")
    assert match_open_last_document("open that chart")
    assert match_open_last_document("open the plot")
    assert not match_open_last_document("show that in explorer")
    assert match_reveal_last_document("show that in explorer")
    assert match_reveal_last_document("show that in the folder")
    assert match_reveal_last_document("show that chart in explorer")
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


def test_files_in_turn_rebuilds_from_the_note(tmp_path: Path) -> None:
    dest = tmp_path / "note.pdf"
    dest.write_bytes(b"%PDF-1.4")
    note = f"[tools used this turn: document {dest}]"
    files = files_in_turn("Wrote the file.", note)
    assert len(files) == 1
    assert files[0][0] == "note.pdf"
    assert Path(files[0][1]).resolve() == dest.resolve()


def test_files_in_turn_skips_a_missing_file(tmp_path: Path) -> None:
    gone = tmp_path / "gone.pdf"
    assert files_in_turn("", f"document {gone}") == []


def test_latest_path_survives_in_the_note(tmp_path: Path) -> None:
    dest = tmp_path / "keep.md"
    dest.write_text("hi\n", encoding="utf-8")
    history = [
        {
            "role": "assistant",
            "content": "Wrote keep.md.",
            "note": f"[tools used this turn: document {dest}]",
        }
    ]
    assert Path(latest_document_path(history)).resolve() == dest.resolve()


def test_a_posix_absolute_path_in_the_note_is_still_a_path() -> None:
    """Drive-letter matching is not the product. Linux CI tmp_path is /tmp/..."""
    note = "[tools used this turn: document /tmp/pytest-of-runner/keep.md]"
    match = _PATH_MENTION.search(note)
    assert match is not None
    assert match.group(1).endswith("keep.md")
    plot = "[tools used this turn: plot /tmp/pytest-of-runner/plot-line.png]"
    assert _PATH_MENTION.search(plot) is not None
    assert _PATH_MENTION.search("https://example.com/keep.md") is None


def test_files_in_turn_rebuilds_a_plot(tmp_path: Path) -> None:
    dest = tmp_path / "plot-line.png"
    dest.write_bytes(b"\x89PNG\r\n\x1a\n")
    note = f"[tools used this turn: plot {dest}]"
    files = files_in_turn("Wrote the chart.", note)
    assert len(files) == 1
    assert files[0][0] == "plot-line.png"
    assert Path(files[0][1]).resolve() == dest.resolve()


def test_open_that_after_a_plot_uses_the_png(tmp_path: Path) -> None:
    dest = tmp_path / "plot-line.png"
    dest.write_bytes(b"\x89PNG\r\n\x1a\n")
    receipts = [{"tool": "plot", "abs_path": str(dest), "path": str(dest)}]
    assert Path(latest_openable_path(receipts=receipts)).resolve() == dest.resolve()
    assert latest_document_path(receipts=receipts) == ""
