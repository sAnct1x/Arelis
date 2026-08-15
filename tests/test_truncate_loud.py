"""Loud truncation metadata (Wave 0)."""

from __future__ import annotations

from arelis.tools.safety import TruncationInfo, truncate_tool_output


def test_no_truncate_short() -> None:
    text, info = truncate_tool_output("hello", 100)
    assert text == "hello"
    assert info == TruncationInfo(truncated=False, original_chars=5, kept_chars=5)


def test_truncate_marks_and_meta() -> None:
    text, info = truncate_tool_output("abcdefghij", 4)
    assert text.startswith("abcd")
    assert "[truncated to 4 chars]" in text
    assert info.truncated
    assert info.original_chars == 10
    assert info.kept_chars == 4
