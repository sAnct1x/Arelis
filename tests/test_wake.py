"""Idle wake matches the spellings Whisper actually writes for this desk."""

from __future__ import annotations

from arelis.voice.wake import classify_wake, looks_like_wake_attempt, match_wake


def test_hey_arelis_wakes() -> None:
    assert match_wake("Hey Arelis") == ""
    assert match_wake("Hey Arelis, what's the weather") == "what's the weather"


def test_whisper_misspellings_from_the_log_wake() -> None:
    """These are real idle clips. Two of them used to miss."""
    assert classify_wake("Hey Arilis, use your browser").matched
    assert classify_wake("Hey Rellis, take me to x.com").matched
    assert classify_wake("Hey, Arrelas").matched
    assert classify_wake("Hey, Aurelis, what is the weather").matched
    assert classify_wake("Pay a relus").matched
    # Bare doorbell, tonight: Whisper wrote this and we sat on wake.
    assert classify_wake("Hair Relus").matched
    assert classify_wake("Hair Relus").remainder == ""
    assert classify_wake("HAY Are relus").matched
    assert classify_wake("Hayer relus").matched
    assert classify_wake("Haigha relus").matched
    assert classify_wake("Hier relus").matched
    assert classify_wake("Here relus").matched
    assert classify_wake("Her relus").matched
    assert classify_wake("Hair relics").matched
    assert classify_wake("Hey arrellis").matched
    assert classify_wake("Hierrallus").matched
    assert classify_wake("Hayorellus").matched
    assert classify_wake("Harlus").matched


def test_ordinary_talk_does_not_wake() -> None:
    assert match_wake("Why am I not listening to anything?") is None
    assert match_wake("hahaha") is None
    assert match_wake("Arelis") is None
    # "here" is a start-greeting only when her name follows.
    assert match_wake("Here we go") is None
    assert match_wake("Here are different culprits that I've talked to") is None
    assert match_wake("her dog") is None
    assert not looks_like_wake_attempt("Yeah, that's funny")
