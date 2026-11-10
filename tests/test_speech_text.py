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
    clause = "I don't have personal preferences,"
    rest = (
        "but from a scientific standpoint Titan is fascinating because "
        "of those methane lakes."
    )
    assert len(long) >= 72
    clips, already = next_speakable_units(long, 0, finalize=False)
    assert clips[0] == clause
    # The remainder is already complete and long, so it is queued behind
    # the opening clause in the same call, not packed into the first clip.
    assert clips == [clause, rest]
    assert already == 2


def test_already_does_not_reglue_a_spoken_sentence() -> None:
    first = (
        "I don't have personal preferences, but from a scientific "
        "standpoint Titan is fascinating because of those methane lakes."
    )
    clips, already = next_speakable_units(first, 0, finalize=False)
    assert already == 2
    more = first + " Europa is the other one people talk about."
    clips, already = next_speakable_units(more, already, finalize=False)
    assert clips == []
    clips, already = next_speakable_units(more, already, finalize=True)
    assert clips == ["Europa is the other one people talk about."]
    assert first not in clips[0]


def test_first_unit_of_a_reply_is_a_clause_later_units_stay_sentences() -> None:
    """First audio can start on a short opening clause, not the full sentence.

    Later units stay whole sentences. Numbers, decimals, abbreviations,
    URLs, and units are not valid split points.
    """
    long = (
        "I don't have personal preferences, but from a scientific "
        "standpoint Titan is fascinating because of those methane lakes."
    )
    clause = "I don't have personal preferences,"
    rest = (
        "but from a scientific standpoint Titan is fascinating because "
        "of those methane lakes."
    )

    # A clause is enough to start, even while the first sentence is still
    # streaming and has no period yet.
    growing = "I don't have personal preferences, but from a scientific"
    clips, already = next_speakable_units(growing, 0, finalize=False)
    assert clips == [clause]
    assert already == 1
    clips, already = next_speakable_units(long, already, finalize=False)
    assert clips == [rest]
    assert already == 2

    # A later sentence with a comma stays one unit so prosody is not choppy.
    later = long + " Europa, the icy moon, is the other one people talk about."
    clips, already = next_speakable_units(later, already, finalize=True)
    assert clips == ["Europa, the icy moon, is the other one people talk about."]

    # Safe clause punctuation after a protected number or unit.
    clips, _ = next_speakable_units(
        "The air is 27.22°C, which is mild tonight.", 0, finalize=False
    )
    assert clips[0] == "The air is 27.22°C,"
    clips, _ = next_speakable_units(
        "3.2 km west of town, then we turn.", 0, finalize=False
    )
    assert clips[0] == "3.2 km west of town,"
    clips, _ = next_speakable_units(
        "The distance is 1,200 km, according to the sign.", 0, finalize=False
    )
    assert clips[0] == "The distance is 1,200 km,"
    clips, _ = next_speakable_units(
        "See e.g., the catalog for Saturn, then ask again.", 0, finalize=False
    )
    assert clips[0] == "See e.g., the catalog for Saturn,"
    clips, _ = next_speakable_units(
        "The notes are at https://example.com/path/weather, and then we wait.",
        0,
        finalize=False,
    )
    assert clips[0] == "The notes are at https://example.com/path/weather,"

    # A comma inside a URL or a thousands group is not a clause break, and
    # a short first sentence with a one-word "Yeah," stays whole.
    long_url = (
        "The notes are at https://example.com/foo,bar/baz tonight and also "
        "tomorrow after that extra padding words here."
    )
    clips, _ = next_speakable_units(long_url, 0, finalize=False)
    assert "foo,bar/baz" in clips[0]
    assert not clips[0].endswith("foo,")
    clips, already = next_speakable_units(
        "Take 1,200 km of rope with you today.", 0, finalize=False
    )
    assert clips == ["Take 1,200 km of rope with you today."]
    assert already == 1
    clips, _ = next_speakable_units("Yeah, Titan is pretty cool.", 0, finalize=False)
    assert clips == ["Yeah, Titan is pretty cool."]

    # No punctuation: cap the first unit at about 72 characters.
    long_plain = (
        "This is a fairly long opening without any comma semicolon colon "
        "or dash in the first eighty characters of the reply at all."
    )
    clips, already = next_speakable_units(long_plain, 0, finalize=False)
    assert clips[0] == (
        "This is a fairly long opening without any comma semicolon colon or dash"
    )
    assert already >= 1
    assert len(clips[0]) <= 72


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


