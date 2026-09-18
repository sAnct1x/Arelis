"""Phase 5 phrases must land on the tool that can finish the ask."""

from __future__ import annotations

from arelis.core.preflight import detect_intents


def _kinds(text: str) -> set[str]:
    return {hint.kind for hint in detect_intents(text)}


def _tools(text: str) -> set[str]:
    out: set[str] = set()
    for hint in detect_intents(text):
        out.update(hint.expected_tools)
    return out


def test_search_my_pdfs_is_recall_docs_not_extract() -> None:
    kinds = _kinds("search my pdfs for the quote about sodium")
    assert "recall_docs" in kinds
    assert "docs" not in kinds
    assert _tools("search my pdfs for the quote about sodium") == {"recall"}


def test_remind_me_in_is_timer_not_calendar() -> None:
    assert "remind" in _kinds("remind me in 20 minutes to check the oven")
    assert _tools("remind me in 20 minutes to check the oven") == {"remind"}


def test_when_am_i_free_is_agenda_free() -> None:
    assert "agenda_free" in _kinds("when am I free Thursday")
    assert "agenda" in _tools("when am I free Thursday")


def test_search_my_notes_is_notes() -> None:
    assert "notes" in _kinds("search my notes for the budget")
    assert _tools("search my notes for the budget") == {"notes"}


def test_merge_pdfs_is_pdf_not_document() -> None:
    assert "pdf_assemble" in _kinds("merge these pdfs into one handout")
    assert _tools("merge these pdfs into one handout") == {"pdf"}


def test_apply_this_diff_is_workspace_patch() -> None:
    assert "patch" in _kinds("apply this diff to hello.py")
    assert _tools("apply this diff to hello.py") == {"workspace"}
