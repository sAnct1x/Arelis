"""Parakeet is opt-in: first use downloads with progress, failure uses Whisper."""

from __future__ import annotations

from pathlib import Path

import yaml

from arelis.config import DEFAULT_CONFIG_PATH
from arelis.voice.parakeet_stt import (
    ARCHIVE_BYTES,
    ARCHIVE_SHA256,
    MODEL_URL,
)
from arelis.voice.stt import SpeechToText


def test_parakeet_missing_model_downloads_with_progress_and_failed_download_falls_back_to_whisper(
    tmp_path: Path, monkeypatch
) -> None:
    shipped = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    assert shipped["voice"]["stt"]["engine"] == "whisper"
    assert SpeechToText({}).requested_engine() == "whisper"
    assert SpeechToText({"voice": {"stt": {}}}).resolved_backend() != "parakeet"

    root = tmp_path / "parakeet"
    stt = SpeechToText(
        {
            "voice": {
                "stt": {
                    "engine": "parakeet",
                    "parakeet_dir": str(root),
                    "allow_download": True,
                    "backend": "faster-whisper",
                }
            }
        }
    )
    assert stt.requested_engine() == "parakeet"

    progress: list[tuple[str, int, int]] = []
    stt.set_progress(lambda status, done, total: progress.append((status, done, total)))

    downloads: list[tuple[str, int, str]] = []

    def fake_download(
        url: str,
        dest: Path,
        *,
        expected_bytes: int,
        sha256: str,
        progress=None,
        cancelled=None,
    ) -> Path:
        downloads.append((url, expected_bytes, sha256))
        if cancelled is not None and cancelled():
            raise RuntimeError("The download was stopped.")
        if progress is not None:
            progress("Downloading the chat model…", 0, expected_bytes)
            progress("Downloading the chat model…", expected_bytes // 2, expected_bytes)
        raise RuntimeError("Arelis could not download the chat model.")

    monkeypatch.setattr("arelis.setup.download.download_file", fake_download)
    monkeypatch.setattr(
        "arelis.voice.parakeet_stt.parakeet_package_available", lambda: True
    )
    monkeypatch.setattr(stt, "_whisper_installed", lambda: True)
    monkeypatch.setattr(stt, "_transcribe_whisper", lambda path, purpose="turn": "hello from whisper")

    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"RIFF")

    text = stt._transcribe_blocking(str(clip), "turn")

    assert text == "hello from whisper"
    assert downloads == [(MODEL_URL, ARCHIVE_BYTES, ARCHIVE_SHA256)]
    assert progress, "first-use download must report a progress line"
    assert any("Parakeet" in status for status, _done, _total in progress)
    assert stt.resolved_backend(purpose="turn") == "faster-whisper"
    notice = stt.take_fallback_notice()
    assert notice is not None
    assert "Whisper" in notice
    assert stt.take_fallback_notice() is None

    # A stopped download is the same fallback, not a hang or a retry loop.
    stt._parakeet_failed = False
    stt._parakeet = None
    stt.set_cancelled(lambda: True)
    stt.set_progress(lambda status, done, total: progress.append((status, done, total)))
    stopped = stt._transcribe_blocking(str(clip), "turn")
    assert stopped == "hello from whisper"
    assert "stopped" in (stt.take_fallback_notice() or "").lower()

    # The real pack is never fetched in this test.
    assert not root.exists() or not any(root.rglob("*.onnx"))
