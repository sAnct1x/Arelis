"""Spoken transcripts stay usable: fillers drop, recent names land."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from arelis.voice.stt import (
    recent_stt_vocab,
    repair_stt_from_recent,
    scrub_transcript,
)


def test_isolated_fillers_are_stripped() -> None:
    assert scrub_transcript("Yet indeed it does ah and that i said ah what") == (
        "Yet indeed it does and that i said what"
    )
    assert scrub_transcript("No do no plans ah i do think") == "No do no plans i do think"


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


def test_arelis_and_archaic_splits_are_repaired() -> None:
    assert scrub_transcript(
        "I am actually just showing somebody a relic for the first time"
    ) == "I am actually just showing somebody Arelis for the first time"
    assert scrub_transcript(
        "HULLO to morrow and to night we test a sign wave with some one"
    ) == "Hello tomorrow and tonight we test a sine wave with someone"


def test_recent_vocab_never_corrupts_common_lowercase_words() -> None:
    history = [
        SimpleNamespace(
            role="assistant",
            content="The middle model has a simple system part and port.",
        )
    ]
    heard = "the mode is fast and I will test my part"
    assert repair_stt_from_recent(heard, history) == heard





def test_please_between_numbers_is_repaired_to_plus() -> None:
    """Whisper-base greedy heard 'plus' as 'Please' on the 11-09 barge clip."""
    assert scrub_transcript("What's 2 Please 2?") == "What's 2 plus 2?"
    assert scrub_transcript("what's two please two") == "what's two plus two"
    # Ordinary politeness is left alone.
    assert scrub_transcript("Can you help me please") == "Can you help me please"
    assert scrub_transcript("Me too please ten more") == "Me too please ten more"


def test_whisper_uses_a_beam_and_plus_hotwords(tmp_path: Path) -> None:
    """Official 11-09 barge-in was decoded at beam_size 1 with no hotwords."""
    import yaml

    from arelis.config import DEFAULT_CONFIG_PATH
    from arelis.voice.stt import SpeechToText

    shipped = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text())
    stt_cfg = shipped["voice"]["stt"]
    assert int(stt_cfg["beam_size"]) > 1
    assert "plus" in str(stt_cfg.get("hotwords") or "").lower()

    captured: dict[str, object] = {}

    class _Model:
        def transcribe(self, audio, **kwargs):
            del audio
            captured.update(kwargs)
            return iter((SimpleNamespace(text="What's two plus two?"),)), None

    import struct
    import wave as _wave

    wav = tmp_path / "clip.wav"

    with _wave.open(str(wav), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(16000)
        fh.writeframes(struct.pack("<" + "h" * 1600, *([0] * 1600)))

    ear = SpeechToText(shipped)
    ear._model = _Model()
    text = ear._transcribe_whisper(str(wav), purpose="turn")
    assert "plus" in text.lower()
    assert int(captured["beam_size"]) > 1
    assert "plus" in str(captured.get("hotwords") or "").lower()
