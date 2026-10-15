"""Structural checks for the 20-prompt live glass board."""

from __future__ import annotations

from arelis.eval.live_board import LIVE_BOARD


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


