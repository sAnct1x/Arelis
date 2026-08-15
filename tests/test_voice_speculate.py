"""Provisional STT intent helpers (conversation overlap Phase E)."""

from arelis.voice.speculate import provisional_intents, speculation_matches_final


def test_provisional_weather() -> None:
    intent = provisional_intents("What's the weather today?")
    assert intent is not None
    assert "weather" in intent.kinds
    assert "weather" in intent.summary.lower()


def test_provisional_ignores_chitchat() -> None:
    assert provisional_intents("hello there how are you") is None


def test_speculation_cancel_when_final_differs() -> None:
    prov = provisional_intents("Text Brian that I'm late")
    assert prov is not None
    assert not speculation_matches_final(prov, "never mind what is two plus two")
    assert speculation_matches_final(prov, "Text Brian: running late")
