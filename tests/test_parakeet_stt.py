"""Parakeet is opt-in: first use downloads with progress, failure uses Whisper."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import yaml

from arelis.config import DEFAULT_CONFIG_PATH
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.voice import VoiceService
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

    # Whisper transcribe publishes no progress event. A clear in finally
    # would hide a visible "making a picture" line on the default path.
    async def _whisper_ingest() -> list[Event]:
        bus = EventBus()
        events: list[Event] = []

        async def capture(event: Event) -> None:
            events.append(event)

        bus.subscribe(None, capture)
        runner = asyncio.create_task(bus.run())
        voice = VoiceService(
            bus,
            {
                "voice": {
                    "enabled": True,
                    "keep_recordings": True,
                    "stt": {
                        "enabled": True,
                        "engine": "whisper",
                        "backend": "faster-whisper",
                    },
                    "tts": {"enabled": False},
                }
            },
        )
        monkeypatch.setattr(voice.stt, "_whisper_installed", lambda: True)
        monkeypatch.setattr(
            voice.stt,
            "_transcribe_whisper",
            lambda path, purpose="turn": "hello from whisper",
        )
        try:
            text = await voice.ingest_audio(clip)
            await bus.drain()
        finally:
            bus.stop()
            runner.cancel()
        assert text == "hello from whisper"
        return events

    whisper_events = asyncio.run(_whisper_ingest())
    assert not any(
        ev.type == EventType.STATUS and ev.payload.get("progress") is not None
        for ev in whisper_events
    ), "Whisper transcribe must publish no progress event"

    # A VoiceService Stop during a fake first-use download aborts it and
    # falls back to Whisper. The next clip can retry.
    started = threading.Event()
    saw_cancel = threading.Event()
    download_calls: list[str] = []

    def waiting_download(
        url: str,
        dest: Path,
        *,
        expected_bytes: int,
        sha256: str,
        progress=None,
        cancelled=None,
    ) -> Path:
        del dest, expected_bytes, sha256, progress
        download_calls.append(url)
        if len(download_calls) == 1:
            started.set()
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if cancelled is not None and cancelled():
                    saw_cancel.set()
                    raise RuntimeError("The download was stopped.")
                time.sleep(0.01)
            raise AssertionError("VoiceService stop did not abort the download")
        if cancelled is not None and cancelled():
            raise AssertionError("cancel flag was not reset for the next clip")
        raise RuntimeError("Arelis could not download the chat model.")

    monkeypatch.setattr("arelis.setup.download.download_file", waiting_download)

    async def _stopped_ingest() -> tuple[str, bool, str, list[Event]]:
        bus = EventBus()
        events: list[Event] = []

        async def capture(event: Event) -> None:
            events.append(event)

        bus.subscribe(None, capture)
        runner = asyncio.create_task(bus.run())
        voice = VoiceService(
            bus,
            {
                "voice": {
                    "enabled": True,
                    "keep_recordings": True,
                    "stt": {
                        "enabled": True,
                        "engine": "parakeet",
                        "parakeet_dir": str(tmp_path / "parakeet-svc"),
                        "allow_download": True,
                        "backend": "faster-whisper",
                    },
                    "tts": {"enabled": False},
                }
            },
        )
        monkeypatch.setattr(
            "arelis.voice.parakeet_stt.parakeet_package_available", lambda: True
        )
        monkeypatch.setattr(voice.stt, "_whisper_installed", lambda: True)
        monkeypatch.setattr(
            voice.stt,
            "_transcribe_whisper",
            lambda path, purpose="turn": "hello from whisper",
        )
        try:
            task = asyncio.create_task(voice.ingest_audio(clip))
            await asyncio.to_thread(started.wait, 5.0)
            assert started.is_set(), "fake download did not start"
            voice.cancel_speech()
            first = await asyncio.wait_for(task, timeout=5.0)
            failed_after_stop = bool(voice.stt._parakeet_failed)
            second = await asyncio.wait_for(voice.ingest_audio(clip), timeout=5.0)
            await bus.drain()
        finally:
            bus.stop()
            runner.cancel()
        return first, failed_after_stop, second, events

    first, failed_after_stop, second, stop_events = asyncio.run(_stopped_ingest())
    assert first == "hello from whisper"
    assert saw_cancel.is_set(), "Stop must abort the in-flight download"
    notices = [
        str(ev.payload.get("message") or "")
        for ev in stop_events
        if ev.type == EventType.STATUS
    ]
    assert any("stopped" in msg.lower() and "Whisper" in msg for msg in notices)
    assert second == "hello from whisper"
    assert download_calls == [MODEL_URL, MODEL_URL]
    assert not failed_after_stop, "a stopped download must let the next Parakeet use retry"
