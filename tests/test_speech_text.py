"""Spoken clips are breaths, not a WAV per period."""

from __future__ import annotations

from arelis.voice.speech_text import next_speakable_units, split_sentences


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


def test_a_one_sentence_answer_starts_without_waiting_for_done() -> None:
    line = "Doing well, thanks for asking."
    clips, already = next_speakable_units(line, 0, finalize=False)
    assert clips == [line]
    assert already == 1


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


def test_split_still_breaks_on_periods() -> None:
    parts = split_sentences("One. Two. Three.")
    assert parts == ["One.", "Two.", "Three."]
