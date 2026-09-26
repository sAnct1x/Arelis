"""Spoken transcripts stay usable: fillers drop, recent names land."""

from __future__ import annotations

from types import SimpleNamespace

from arelis.voice.stt import (
    SpeechToText,
    recent_stt_vocab,
    repair_stt_from_recent,
    repair_stt_mail_words,
    scrub_transcript,
)


def test_isolated_fillers_are_stripped() -> None:
    assert scrub_transcript("Yet indeed it does ah and that i said ah what") == (
        "Yet indeed it does and that i said what"
    )
    assert scrub_transcript("No do no plans ah i do think") == "No do no plans i do think"


def test_mail_homophones_still_repair() -> None:
    assert repair_stt_mail_words("check my in box for an emile") == (
        "check my inbox for an email"
    )


def test_recent_names_repair_the_near_misses() -> None:
    history = [
        SimpleNamespace(
            role="assistant",
            content="Titan is pretty cool. Europa might have life under the ice.",
        )
    ]
    heard = "tighten is pretty coal and your rope i might have life"
    fixed = repair_stt_from_recent(heard, history)
    assert "Titan" in fixed
    assert "Europa" in fixed
    assert "tighten" not in fixed.lower()
    assert "rope" not in fixed.lower()


def test_repair_does_nothing_without_context() -> None:
    heard = "tighten is pretty coal"
    assert repair_stt_from_recent(heard, []) == heard


def test_vocab_skips_stopwords() -> None:
    history = [
        SimpleNamespace(role="user", content="what did you say about that"),
        SimpleNamespace(role="assistant", content="Titan has methane lakes."),
    ]
    words = {w.lower() for w in recent_stt_vocab(history)}
    assert "titan" in words
    assert "methane" in words
    assert "what" not in words
    assert "that" not in words


def test_wake_uses_sherpa_until_whisper_is_in_ram() -> None:
    stt = SpeechToText({"voice": {"stt": {"backend": "sherpa"}}})
    stt._sherpa_usable = lambda: True  # type: ignore[method-assign]
    stt._sherpa_failed = False
    assert stt.resolved_backend(purpose="wake") == "sherpa"
    stt._model = object()
    assert stt.resolved_backend(purpose="wake") == "faster-whisper"
