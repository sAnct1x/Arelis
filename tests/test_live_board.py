"""Structural checks for the 20-prompt live glass board."""

from __future__ import annotations

from arelis.eval.live_board import BOARD_ID, FORBIDDEN_TOOLS, LIVE_BOARD, live_board_turns


def test_live_board_has_twenty_unique_turns() -> None:
    turns = live_board_turns()
    assert len(turns) == 20
    ids = [t.id for t in turns]
    assert len(set(ids)) == 20
    assert ids == [t.id for t in LIVE_BOARD]


def test_live_board_covers_required_surfaces() -> None:
    by_id = {t.id: t for t in LIVE_BOARD}
    assert {"workspace", "document"} & set(by_id["T06_csv_write"].expect_tools)
    assert "python" in by_id["T07_sqrt"].expect_tools
    assert "send_email" in by_id["T08_email_me"].expect_tools
    assert by_id["T09_cal_keep"].expect_args.get("action") == "create"
    assert by_id["T09_cal_keep"].expect_args.get("summary") == "stay"
    assert by_id["T11_cal_delete"].expect_args.get("action") == "delete"
    assert {"workspace", "document"} & set(by_id["T12_file_write"].expect_tools)
    assert "document" in by_id["T14_doc_convert"].expect_tools
    assert "research_report" in by_id["T17_deep_research"].expect_tools
    assert "calculator" in by_id["T01_math_easy"].expect_tools
    assert "cas" in by_id["T04_cas_integral"].expect_tools


def test_live_board_skips_image_and_earth() -> None:
    for turn in LIVE_BOARD:
        assert not FORBIDDEN_TOOLS.intersection(turn.expect_tools)
        blob = f"{turn.user} {turn.notes}".lower()
        assert "generate an image" not in blob
        assert "enter earth" not in blob
        assert "text my wife" not in blob
        assert "text me:" not in blob


def test_side_effect_prompts_carry_the_search_token() -> None:
    for turn_id in (
        "T06_csv_write",
        "T08_email_me",
        "T09_cal_keep",
        "T10_cal_scratch",
        "T11_cal_delete",
        "T12_file_write",
        "T13_doc_create",
        "T20_tasks",
    ):
        turn = next(t for t in LIVE_BOARD if t.id == turn_id)
        assert BOARD_ID in turn.user
