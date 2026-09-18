"""Conversation export writes the transcript, not a title page.

Roadmap 6.5. Per-reply copy already exists; this is the whole session as
markdown. Tests drive `export_transcript` with role/text dicts — no Qt.

Mutants this file is supposed to catch:

1. export that only writes titles (`# Conversation`, `## You`) and drops
   the actual turns.
2. empty session that still writes a file (or fails with a vague error).
3. a secret that survives into the markdown (`password: hunter2`).
4. raw tool JSON dumped next to a notice that already cleaned it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.core.transcript import (
    EmptyTranscript,
    default_export_filename,
    export_transcript,
    render_transcript,
)


def _turns(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"role": role, "text": text} for role, text in pairs]


def test_export_writes_real_markdown(tmp_path: Path) -> None:
    """Bodies must land. A titles-only write fails this test."""
    dest = tmp_path / "lab.md"
    written = export_transcript(
        _turns(
            ("user", "what did we decide about the sodium cell"),
            ("assistant", "keep the native disc as fallback only"),
        ),
        dest,
    )
    assert written == dest
    assert dest.is_file()
    page = dest.read_text(encoding="utf-8")
    assert page.lstrip().startswith("# ")
    assert "what did we decide about the sodium cell" in page
    assert "keep the native disc as fallback only" in page
    assert page.count("## You") == 1
    assert page.count("## Arelis") == 1


def test_empty_session_fails_clearly(tmp_path: Path) -> None:
    dest = tmp_path / "empty.md"
    with pytest.raises(EmptyTranscript, match="empty"):
        export_transcript([], dest)
    assert not dest.exists()


def test_whitespace_only_session_is_empty(tmp_path: Path) -> None:
    dest = tmp_path / "blank.md"
    with pytest.raises(EmptyTranscript, match="empty"):
        export_transcript(_turns(("user", "   "), ("assistant", "")), dest)
    assert not dest.exists()


def test_empty_error_is_readable() -> None:
    with pytest.raises(ValueError, match="Nothing to export"):
        render_transcript([])


def test_redacted_secret_does_not_appear(tmp_path: Path) -> None:
    dest = tmp_path / "secret.md"
    export_transcript(
        _turns(
            ("user", "the wifi password: hunter2 stays off the dump"),
            ("assistant", "got it"),
        ),
        dest,
    )
    page = dest.read_text(encoding="utf-8")
    assert "hunter2" not in page
    assert "[redacted]" in page
    assert "got it" in page


def test_skips_tool_json_when_a_notice_already_cleaned_it(tmp_path: Path) -> None:
    dest = tmp_path / "tools.md"
    export_transcript(
        [
            {"role": "user", "text": "check the inbox"},
            {
                "role": "tool",
                "text": '{"ok": true, "messages": [{"from": "robin", "body": "hi"}]}',
            },
            {"role": "notice", "text": "inbox listed 3 messages"},
            {"role": "assistant", "text": "three new, none urgent"},
        ],
        dest,
    )
    page = dest.read_text(encoding="utf-8")
    assert '{"ok": true' not in page
    assert '"messages"' not in page
    assert "inbox listed 3 messages" in page
    assert "three new, none urgent" in page
    assert "check the inbox" in page


def test_tool_json_alone_does_not_count_as_a_session(tmp_path: Path) -> None:
    dest = tmp_path / "json-only.md"
    with pytest.raises(EmptyTranscript, match="empty"):
        export_transcript(
            [
                {
                    "role": "tool",
                    "content": '{"ok": true, "output": "raw dump"}',
                }
            ],
            dest,
        )
    assert not dest.exists()


def test_store_content_key_works_too(tmp_path: Path) -> None:
    dest = tmp_path / "store.md"
    export_transcript(
        [
            {"role": "user", "content": "ping"},
            {"role": "assistant", "content": "pong"},
        ],
        dest,
    )
    page = dest.read_text(encoding="utf-8")
    assert "ping" in page
    assert "pong" in page


def test_default_filename_is_safe() -> None:
    assert default_export_filename("lab notes?") == "lab-notes.md"
    assert default_export_filename("") == "conversation.md"
    assert default_export_filename("con") == "conversation.md"
