"""Point-and-Ask LookGrant — speech-act, cascade, non-transfer, exactness."""

from __future__ import annotations

from arelis.core.look import (
    LOOK_NO_TRANSFER,
    LOOK_TOOL_SUBSET,
    classify_look,
    look_answer_refuse,
    look_call_blocked,
)


def test_read_and_translate_and_freshness() -> None:
    assert classify_look("look at the camera and read this to me").act == "read"
    tr = classify_look("look at the webcam and translate this to spanish")
    assert tr is not None
    assert tr.act == "translate"
    assert tr.target_lang == "spanish"
    assert classify_look("look at the camera — is this still good?").act == "freshness"


def test_look_grant_blocks_sms() -> None:
    notice = look_call_blocked("send_sms", {"to": "brian", "body": "hi"})
    assert notice is not None
    assert "can_act=false" in notice
    assert look_call_blocked("ocr") is None
    assert look_call_blocked("calculator") is None
    assert look_call_blocked("python") is None
    assert "ocr" in LOOK_TOOL_SUBSET
    assert "send_sms" in LOOK_NO_TRANSFER


def test_freshness_verdict_is_refused() -> None:
    refuse = look_answer_refuse(
        "It's safe to eat, throw it out if you want.",
        act="freshness",
        record=None,
    )
    assert refuse is not None
    assert "verdict" in refuse.lower() or "safe/unsafe" in refuse.lower()
    ok = look_answer_refuse(
        "I will not say it is safe to eat. The cut edge is brown.",
        act="freshness",
        record=None,
    )
    assert ok is None


