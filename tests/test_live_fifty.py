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


def test_live_fifty_has_unique_turns() -> None:
    turns = live_fifty_turns()
    assert len(turns) == 163
    ids = [t.id for t in turns]
    assert len(set(ids)) == 163
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


def test_live_fifty_covers_every_callable_tool() -> None:
    mentioned: set[str] = set()
    for turn in live_fifty_turns():
        mentioned.update(turn.expect_tools)
    missing = set(_SHORT_DESC) - mentioned - BOARD_SKIP_TOOLS
    assert not missing, f"board never asks for {sorted(missing)}"
    assert FORBIDDEN_TOOLS <= BOARD_SKIP_TOOLS
