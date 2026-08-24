"""Chat attachment staging under data/drops/."""

from __future__ import annotations

from pathlib import Path

from arelis.attachments import (
    MAX_BYTES,
    attachment_kinds_from_turn,
    continue_prior_attachment_ask,
    detect_kind,
    format_attachments_block,
    is_short_affirmation,
    route_tool,
    session_title_from_turn,
    stage_files,
    stage_image_bytes,
    wants_image_edit,
    wants_image_text,
)


def test_detect_kind() -> None:
    assert detect_kind("a.txt") == "text"
    assert detect_kind("a.MD") == "text"
    assert detect_kind("ui_launch.log") == "text"
    assert detect_kind("app.LOG") == "text"
    assert detect_kind("config.yaml") == "text"
    assert detect_kind("t.csv") == "data"
    assert detect_kind("t.xlsx") == "data"
    assert detect_kind("doc.pdf") == "pdf"
    assert detect_kind("x.png") == "image"
    assert detect_kind("x.docx") == "other"


def test_route_log_uses_workspace_read() -> None:
    assert route_tool("text", "summarize this log") == "workspace read"
    block = format_attachments_block(
        [{"path": "data/drops/20260810/ui_launch.log", "kind": "text"}],
        user_text="give me a short summary of this log",
    )
    assert "→ workspace read" in block
    assert "log" in block.lower()


def test_stage_files_copies_and_kinds(tmp_path: Path) -> None:
    src = tmp_path / "outside"
    src.mkdir()
    note = src / "hello.md"
    note.write_text("# hi", encoding="utf-8")
    drops = tmp_path / "drops"
    result = stage_files([note], drops_root=drops)
    assert not result.errors
    assert len(result.ok) == 1
    att = result.ok[0]
    assert att.kind == "text"
    assert att.name == "hello.md"
    assert att.source_path == str(note.resolve())
    day_dirs = list(drops.iterdir())
    assert len(day_dirs) == 1
    copied = day_dirs[0] / "hello.md"
    assert copied.is_file()
    assert copied.read_text(encoding="utf-8") == "# hi"


def test_stage_rejects_oversized(tmp_path: Path) -> None:
    big = tmp_path / "huge.bin"
    big.write_bytes(b"x" * (MAX_BYTES + 1))
    result = stage_files([big], drops_root=tmp_path / "drops", max_bytes=1024)
    assert not result.ok
    assert result.errors
    assert "larger" in result.errors[0].lower()


def test_stage_collision_suffix(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    src.write_text("one", encoding="utf-8")
    drops = tmp_path / "drops"
    first = stage_files([src], drops_root=drops)
    second = stage_files([src], drops_root=drops)
    assert first.ok and second.ok
    assert first.ok[0].name == "a.txt"
    assert second.ok[0].name == "a-2.txt"


def test_stage_image_bytes(tmp_path: Path) -> None:
    result = stage_image_bytes(b"\x89PNG\r\n", drops_root=tmp_path / "drops")
    assert result.ok
    assert result.ok[0].kind == "image"
    assert result.ok[0].name.startswith("paste-")


def test_stage_bytes_keeps_the_given_name(tmp_path: Path) -> None:
    from arelis.attachments import stage_bytes

    result = stage_bytes(b"%PDF-1.4 notes", "notes.pdf", drops_root=tmp_path / "drops")
    assert result.ok
    assert result.ok[0].name == "notes.pdf"
    assert result.ok[0].kind == "pdf"


def test_format_attachments_block() -> None:
    block = format_attachments_block(
        [
            {
                "path": "data/drops/20260810/report.pdf",
                "kind": "pdf",
                "source_path": r"C:\Users\x\report.pdf",
            }
        ]
    )
    assert "doc_extract" in block
    assert "report.pdf" in block


def test_route_image_describe_uses_vision() -> None:
    assert route_tool("image", "describe this photo") == "vision"
    assert not wants_image_text("describe this photo")


def test_route_image_text_ask_uses_ocr() -> None:
    assert route_tool("image", "extract text from this image") == "ocr"
    assert wants_image_text("read the text in this screenshot")


def test_route_image_edit_ask_uses_image_edit() -> None:
    """An instruction about the file, not a question about it.

    Routing these to vision is what sent the thumbnail ask hunting: vision can
    only look, so she worked down to the image generator and produced a
    different picture at the right size.
    """
    for ask in (
        "make this image more vibrant and resize it for a youtube thumbnail",
        "resize this to 1280 x 720",
        "crop this to 16:9",
        "make it brighter",
        "sharpen this screenshot",
        "can you saturate this a bit",
    ):
        assert route_tool("image", ask) == "image_edit", ask
        assert wants_image_edit(ask), ask

    # Describing is still describing, and reading glyphs is still OCR.
    assert not wants_image_edit("describe this photo")
    assert route_tool("image", "what is in this picture") == "vision"
    assert route_tool("image", "read the text in this screenshot") == "ocr"


def test_the_edit_rule_names_the_three_tools_that_were_tried_instead() -> None:
    block = format_attachments_block(
        [{"path": "data/drops/20260817/paste.png", "kind": "image"}],
        user_text="make this more vibrant and resize it to 1280 x 720",
    )
    assert "→ image_edit" in block
    assert "data/drops/20260817/paste.png" in block
    lowered = block.lower()
    assert "do not call image " in lowered
    assert "do not call vision" in lowered
    assert "calculator" in lowered


def test_format_attachments_image_forbids_doc_extract() -> None:
    block = format_attachments_block(
        [{"path": "data/drops/20260810/shot.png", "kind": "image"}],
        user_text="describe this photo i have attached",
    )
    assert "→ vision" in block
    assert "Never call doc_extract" in block or "Do not call doc_extract" in block
    kinds = attachment_kinds_from_turn(block + "\n\ndescribe this photo")
    assert kinds == {"image"}


def test_short_affirmation_continues_prior_log_attachment() -> None:
    assert is_short_affirmation("yea")
    assert is_short_affirmation("yes please")
    assert not is_short_affirmation("yea, but also check email")

    # Prior turn mislabeled .log as other (pre-fix history); continue re-detects.
    prior = (
        "Attachments for this turn (call the listed tool; do not invent contents):\n"
        "- data/drops/20260810/ui_launch.log (other) → (unsupported — say what you can)\n\n"
        "give me a very short summary of the .log file"
    )
    history = [
        {"role": "user", "content": prior},
        {
            "role": "assistant",
            "content": (
                "The .log file is not supported for text extraction. "
                "Would you like me to summarize it line by line?"
            ),
        },
    ]
    expanded = continue_prior_attachment_ask("yea", history)
    assert expanded is not None
    assert "ui_launch.log" in expanded
    assert "(text)" in expanded
    assert "→ workspace read" in expanded
    assert "User affirmed: yea" in expanded
    assert "Prior ask:" in expanded
    assert continue_prior_attachment_ask("good morning", history) is None


def test_session_title_prefers_ask_over_attachments_block() -> None:
    block = format_attachments_block(
        [{"path": "data/drops/20260811/Beam Diagram-2.png", "kind": "image"}],
        user_text="describe this image to me",
    )
    turn = f"{block}\n\ndescribe this image to me"
    assert session_title_from_turn(turn) == "describe this image to me"
    assert session_title_from_turn(block) == "Attached Beam Diagram-2.png"
    assert session_title_from_turn("hello there") == "hello there"
