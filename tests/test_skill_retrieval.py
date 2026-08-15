"""Paraphrase skill-card retrieval scoreboard."""

from __future__ import annotations

from arelis.eval.skill_retrieval import (
    RETRIEVAL_CASES,
    evaluate_retrieval_case,
    run_retrieval_board,
)


def test_every_retrieval_case_passes() -> None:
    failed = []
    for case in RETRIEVAL_CASES:
        result = evaluate_retrieval_case(case)
        if not result.ok:
            failed.append(f"{case.id}: {', '.join(result.reasons)}")
    assert not failed, "; ".join(failed)


def test_retrieval_board_is_complete() -> None:
    board = run_retrieval_board()
    assert board["total"] == len(RETRIEVAL_CASES)
    assert board["passed"] == board["total"]
    assert board["macro_recall"] == 1.0
    assert board["false_positive_rate"] == 0.0
