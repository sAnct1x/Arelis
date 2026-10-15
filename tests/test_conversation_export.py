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
    export_transcript,
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


