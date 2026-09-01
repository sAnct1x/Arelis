"""First-talk voice weights: what is missing, and what we refuse to fetch."""

from __future__ import annotations

from pathlib import Path

from arelis.voice.prepare import missing_voice_parts, prepare_voice_files


def test_missing_voice_parts_names_absent_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("arelis.voice.sherpa_stt.models_dir", lambda: tmp_path / "models")
    monkeypatch.setattr("arelis.voice.silero_vad.models_dir", lambda: tmp_path / "models")
    monkeypatch.setattr("arelis.voice.kokoro_tts.models_dir", lambda: tmp_path / "models")
    monkeypatch.setattr("arelis.voice.smart_turn.models_dir", lambda: tmp_path / "models")
    monkeypatch.setattr("arelis.paths.models_dir", lambda: tmp_path / "models")
    monkeypatch.setattr(
        "arelis.voice.sherpa_stt.resolve_model_dir",
        lambda _cfg=None: tmp_path / "models" / "sherpa",
    )
    monkeypatch.setattr(
        "arelis.voice.silero_vad.default_model_path",
        lambda: tmp_path / "models" / "silero" / "silero_vad.onnx",
    )
    monkeypatch.setattr(
        "arelis.voice.prepare.resolve_model_path",
        lambda rel: tmp_path / rel,
    )
    monkeypatch.setattr(
        "arelis.voice.smart_turn._DEFAULT_MODEL",
        tmp_path / "models" / "smart_turn" / "smart-turn.onnx",
    )

    missing = missing_voice_parts(
        {
            "voice": {
                "stt": {"allow_download": True},
                "vad": {"allow_download": True},
                "tts": {"allow_download": True},
                "conversation": {"smart_turn": {"enabled": True, "allow_download": True}},
            }
        }
    )
    assert "the ear" in missing
    assert "the pause" in missing
    assert "her voice" in missing
    assert "the turn" in missing


def test_allowed_only_hides_parts_we_will_not_fetch(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "arelis.voice.sherpa_stt.resolve_model_dir",
        lambda _cfg=None: tmp_path / "sherpa",
    )
    monkeypatch.setattr(
        "arelis.voice.silero_vad.default_model_path",
        lambda: tmp_path / "silero.onnx",
    )
    monkeypatch.setattr(
        "arelis.voice.prepare.resolve_model_path",
        lambda rel: tmp_path / Path(rel).name,
    )
    config = {
        "voice": {
            "stt": {"allow_download": False},
            "vad": {"allow_download": False},
            "tts": {"allow_download": False},
            "conversation": {"smart_turn": False},
        }
    }
    assert missing_voice_parts(config, allowed_only=True) == []
    assert "the ear" in missing_voice_parts(config)


def test_prepare_does_not_download_when_asked_not_to(tmp_path, monkeypatch) -> None:
    called = []

    def _boom(*_args, **_kwargs):
        called.append("download")
        raise AssertionError("must not fetch")

    monkeypatch.setattr("arelis.voice.sherpa_stt.ensure_sherpa_files", _boom)
    monkeypatch.setattr("arelis.voice.silero_vad.ensure_silero_model", _boom)
    monkeypatch.setattr("arelis.voice.kokoro_tts.ensure_kokoro_files", _boom)
    fetched = prepare_voice_files(
        {
            "voice": {
                "stt": {"allow_download": False},
                "vad": {"allow_download": False},
                "tts": {"allow_download": False},
                "conversation": {"smart_turn": False},
            }
        }
    )
    assert fetched == []
    assert called == []
