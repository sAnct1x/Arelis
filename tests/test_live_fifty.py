"""Structural checks for the tell-her live board."""

from __future__ import annotations

from arelis.core.compact_prompt import _SHORT_DESC
from arelis.eval.live_fifty import (
    BOARD_ID,
    BOARD_SKIP_TOOLS,
    FORBIDDEN_TOOLS,
    LIVE_FIFTY,
    live_fifty_turns,
)

PRODUCT_N = 163
MATH_N = 163


def test_live_fifty_has_unique_turns() -> None:
    turns = live_fifty_turns()
    assert len(turns) == PRODUCT_N + MATH_N
    ids = [t.id for t in turns]
    assert len(set(ids)) == PRODUCT_N + MATH_N
    assert ids == [t.id for t in LIVE_FIFTY]


def test_live_fifty_has_no_mail_or_sms() -> None:
    for turn in LIVE_FIFTY:
        assert "send_email" not in turn.expect_tools
        assert "send_sms" not in turn.expect_tools
        blob = turn.user.lower()
        assert "email me" not in blob
        assert "text my" not in blob
        assert "text me" not in blob


def test_live_fifty_covers_image_reality_earth() -> None:
    by_id = {t.id: t for t in LIVE_FIFTY}
    assert "image" in by_id["T17_img_bike"].expect_tools
    assert "image" in by_id["T21_img_cat"].expect_tools
    assert "enter Earth" in by_id["T37_enter"].user
    assert "take me to Mars" in by_id["T29_mars"].user
    assert "ride the ISS" in by_id["T41_iss"].user
    assert "zoom out to space" in by_id["T63_space"].user
    assert by_id["T163_wrap"].id == "T163_wrap"
    assert BOARD_ID in by_id["T09_lunch"].user
    assert not FORBIDDEN_TOOLS.intersection(by_id["T17_img_bike"].expect_tools)
    chats = [t.id for t in LIVE_FIFTY if t.new_chat]
    assert chats[0] == "T01_math"
    assert "T147_browser" in chats
    assert "T152_solar" in chats
    assert "T157_inspect" in chats
    assert len(chats) >= 8


def test_live_fifty_math_board_is_163_distinct_prompts() -> None:
    math = [t for t in live_fifty_turns() if t.id.startswith("M")]
    assert len(math) == MATH_N
    assert len({t.user for t in math}) == MATH_N
    assert math[0].id == "M001_add"
    assert math[-1].id == "M163_gauss"
    assert math[0].new_chat
    assert all(t.new_chat for t in math)
    for turn in math:
        assert turn.expect_answer_contains or turn.expect_answer_any, turn.id
        assert "gold=" in (turn.notes or ""), turn.id


def test_fold_answer_reads_latex_sqrt_pi() -> None:
    from arelis.eval.conversation import _fold_answer

    folded = _fold_answer(r"exactly $\sqrt{\pi}$")
    assert "sqrt(pi)" in folded
    assert "1/x" in _fold_answer(r"\frac{1}{x}")
    assert "1/2" in _fold_answer(r"\frac{1}{2}")
    assert "2^100" in _fold_answer(r"2475 \cdot 2^{100}")
    assert "5sqrt(2)" in _fold_answer(r"$5\sqrt{2}$")


def test_even_odd_parity_is_not_a_calculator_ask() -> None:
    from arelis.core.claims import detect_exactness_need, detect_math_ask

    ask = "is x^2 + 1 even, odd, or neither as a function of x"
    assert not detect_math_ask(ask)
    assert not detect_exactness_need(ask).needs_calculator


def test_score_turn_gold_beats_failed_first_tool() -> None:
    from arelis.eval.conversation import ConversationTurn, ToolCallRecord, _score_turn

    turn = ConversationTurn(
        id="M009_fact7",
        user="what's 7 factorial",
        expect_tools=("calculator", "python", "cas"),
        expect_tools_any=True,
        expect_answer_contains=("5040",),
        notes="gold=5040",
    )
    ok, reasons = _score_turn(
        turn,
        tools_called=["calculator", "python"],
        tool_records=[
            ToolCallRecord(name="calculator", args={"expression": "7!"}, ok=False),
            ToolCallRecord(
                name="python",
                args={"code": "print(5040)"},
                ok=True,
                output_head="5040",
            ),
        ],
        final_text="7! is 5040.",
    )
    assert ok, reasons


def test_cas_success_also_warrants_calculator() -> None:
    from arelis.core.evidence import EvidenceLedger

    ledger = EvidenceLedger()
    ledger.record_tool("cas", ok=True, output="1", data={"result": "1"})
    assert ledger.has_ok("cas")
    assert ledger.has_ok("calc")


def test_calculator_reads_factorial_bang() -> None:
    from arelis.tools.calculator import evaluate_expression

    assert evaluate_expression("7!") == 5040
    assert evaluate_expression("factorial(7)") == 5040


def test_arcsin_and_log10_are_not_git() -> None:
    from arelis.core.claims import detect_cas_ask, detect_git_ask, detect_math_ask

    assert detect_cas_ask("what's arcsin of 1")
    assert detect_cas_ask("what's arctan of 1")
    assert not detect_git_ask("what's log base 10 of 1000")
    assert detect_math_ask("what's log base 10 of 1000")


def test_board_cleanup_drops_token_junk_only(tmp_path) -> None:
    from datetime import UTC, datetime, timedelta

    from arelis.calendar.models import CachedEvent
    from arelis.calendar.store import CalendarStore
    from arelis.eval.board_cleanup import cleanup_board_token
    from arelis.memory import MemoryStore

    cal = CalendarStore(tmp_path / "cal.db")
    mem = MemoryStore(tmp_path / "mem.db")
    now = datetime.now(UTC)
    cal.put(
        CachedEvent(
            id="local:keep-dinner",
            provider="local",
            calendar_id="primary",
            summary="Dinner keep",
            starts_at=now + timedelta(days=1),
            ends_at=now + timedelta(days=1, hours=1),
            all_day=False,
            raw_id="keep-dinner",
        )
    )
    cal.put(
        CachedEvent(
            id="local:f50-stay",
            provider="local",
            calendar_id="primary",
            summary="stay F50-TEST99",
            starts_at=now + timedelta(days=1, hours=2),
            ends_at=now + timedelta(days=1, hours=3),
            all_day=False,
            raw_id="f50-stay",
        )
    )
    cal.put(
        CachedEvent(
            id="local:lb-keep",
            provider="local",
            calendar_id="primary",
            summary="Arelis live-board keep LB-1255",
            starts_at=now + timedelta(days=1, hours=4),
            ends_at=now + timedelta(days=1, hours=5),
            all_day=False,
            raw_id="lb-keep",
        )
    )
    mem.add_task("sort the F50-TEST99 coverage notes")
    mem.add_task("buy milk")
    files = tmp_path / "out"
    files.mkdir()
    (files / "f50-test99-note.md").write_text("junk", encoding="utf-8")
    (files / "report.md").write_text("keep", encoding="utf-8")
    (files / "real-notes.md").write_text("keep", encoding="utf-8")

    counts = cleanup_board_token(
        "F50-TEST99", calendar=cal, memory=mem, files_root=files
    )
    assert counts["events"] == 2
    assert counts["tasks"] == 1
    leftover = [
        ev.summary
        for ev in cal.list_range(now.date(), now.date() + timedelta(days=7))
    ]
    assert "Dinner keep" in leftover
    assert all("F50" not in title for title in leftover)
    titles = [row["title"] for row in mem.list_tasks(status=None)]
    assert "buy milk" in titles
    assert all("F50" not in title for title in titles)
    assert (files / "report.md").exists()
    assert (files / "real-notes.md").exists()
    assert not (files / "f50-test99-note.md").exists()


def test_live_fifty_covers_every_callable_tool() -> None:
    mentioned: set[str] = set()
    for turn in live_fifty_turns():
        mentioned.update(turn.expect_tools)
    missing = set(_SHORT_DESC) - mentioned - BOARD_SKIP_TOOLS
    assert not missing, f"board never asks for {sorted(missing)}"
    assert FORBIDDEN_TOOLS <= BOARD_SKIP_TOOLS
