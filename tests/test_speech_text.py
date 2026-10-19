"""Spoken clips are breaths, not a WAV per period."""

from __future__ import annotations

import logging
import re

from arelis.voice.speech_text import next_speakable_units, prepare_spoken_text


def test_first_sentence_starts_while_the_answer_is_still_growing() -> None:
    first = "Yeah, Titan is pretty cool."
    clips, already = next_speakable_units(first, 0, finalize=False)
    assert clips == [first]
    assert already == 1

    both = first + " Europa has an ocean under the ice."
    clips, already = next_speakable_units(both, already, finalize=False)
    assert clips == []
    clips, already = next_speakable_units(both, already, finalize=True)
    assert clips == ["Europa has an ocean under the ice."]
    assert already == 2

    _, heard = next_speakable_units("It is 27.", 0, finalize=False)
    clips, _ = next_speakable_units("It is 27.22°C.", heard, finalize=False)
    assert clips == ["It is 27.22°C."]

    _, heard = next_speakable_units("价格是27.", 0, finalize=False, language="zh")
    clips, _ = next_speakable_units("价格是27." + "5元。", heard, finalize=False, language="zh")
    assert clips == ["价格是27.5元。"]


def test_a_long_sentence_starts_without_waiting() -> None:
    long = (
        "I don't have personal preferences, but from a scientific "
        "standpoint Titan is fascinating because of those methane lakes."
    )
    assert len(long) >= 72
    clips, already = next_speakable_units(long, 0, finalize=False)
    assert clips == [long]
    assert already == 1


def test_already_does_not_reglue_a_spoken_sentence() -> None:
    first = (
        "I don't have personal preferences, but from a scientific "
        "standpoint Titan is fascinating because of those methane lakes."
    )
    clips, already = next_speakable_units(first, 0, finalize=False)
    assert already == 1
    more = first + " Europa is the other one people talk about."
    clips, already = next_speakable_units(more, already, finalize=False)
    assert clips == []
    clips, already = next_speakable_units(more, already, finalize=True)
    assert clips == ["Europa is the other one people talk about."]
    assert first not in clips[0]


def test_spoken_reply_says_dates_numbers_and_symbols_as_words() -> None:
    """Dates, #2, degrees, and markdown are words by the time Kokoro hears them.

    The chat line stays as written. Only prepare_spoken_text changes, which
    is the text the phonemizer sees. A raw degree or date makes espeak emit
    a different word count than phonemizer counted.
    """
    shown = (
        "**Boston:** 72°F and clear.\n"
        "- As of 2026-10-15, also Oct 15.\n"
        "Item #2, see [the note](https://example.com/wx) and `code`."
    )
    spoken = prepare_spoken_text(shown)
    assert shown.startswith("**Boston:**")
    assert "°" not in spoken
    assert "#" not in spoken
    assert "*" not in spoken
    assert "`" not in spoken
    assert "2026-10-15" not in spoken
    assert "http" not in spoken
    assert "example.com" not in spoken
    assert "degrees Fahrenheit" in spoken
    assert "number two" in spoken
    assert "October fifteenth" in spoken
    assert "twenty twenty six" in spoken
    assert re.search(r"\d", spoken) is None
    warnings = _phonemizer_mismatch_warnings(spoken)
    if warnings is not None:
        assert warnings == []


def _phonemizer_mismatch_warnings(text: str) -> list[str] | None:
    """None when the Kokoro English phonemizer is not installed."""
    try:
        import phonemizer

        from arelis.voice.kokoro_tts import _configure_espeak
    except ImportError:
        return None
    _configure_espeak()
    logger = logging.getLogger("phonemizer")
    caught: list[str] = []

    class _Grab(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            caught.append(record.getMessage())

    handler = _Grab()
    logger.addHandler(handler)
    previous = logger.level
    logger.setLevel(logging.WARNING)
    try:
        phonemizer.phonemize(text, "en-us", preserve_punctuation=True, with_stress=True)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)
    return [line for line in caught if "words count mismatch" in line]


