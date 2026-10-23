"""First-run download resume, model pin, and llama-server args from config."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml

from arelis.llm.llama_launch import llama_server_args
from arelis.setup import download as download_mod
from arelis.setup.catalog import Q3_FILENAME, Q4_FILENAME
from arelis.setup.download import (
    _READ,
    _SLACK_BYTES,
    _stream_into,
    download_file,
    hf_file_url,
)
from arelis.setup.state import record_model_choice

_REAL_CLIENT = httpx.Client


def _patch_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    transport = httpx.MockTransport(handler)

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return _REAL_CLIENT(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)


def test_download_keeps_partial_and_resumes_with_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"abcdefghijklmnopqrstuvwxyz"
    digest = hashlib.sha256(payload).hexdigest()
    dest = tmp_path / "chat.gguf"
    partial = dest.with_name(dest.name + ".partial")
    ranges: list[str] = []
    mode = {"step": "short"}
    calls = {"n": 0}
    url = "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/edc6f12e7bb90602ca1d34faecbec9844137b7fe/chat.gguf"

    def handler(request: httpx.Request) -> httpx.Response:
        header = request.headers.get("range") or request.headers.get("Range") or ""
        ranges.append(header)
        calls["n"] += 1
        if calls["n"] > 24:
            raise AssertionError("download looped")
        step = mode["step"]
        if step == "short":
            return httpx.Response(200, content=payload[:10])
        if step == "resume206":
            assert header == "bytes=10-"
            return httpx.Response(
                206,
                content=payload[10:],
                headers={"Content-Range": "bytes 10-25/26"},
            )
        if step == "ignore_range":
            assert header == "bytes=10-"
            return httpx.Response(200, content=payload)
        if step == "bad_hash":
            return httpx.Response(200, content=b"X" * len(payload))
        if step == "gone416":
            if header.startswith("bytes="):
                mode["step"] = "after416"
                return httpx.Response(416)
            return httpx.Response(200, content=payload)
        if step == "after416":
            assert header == ""
            return httpx.Response(200, content=payload)
        if step == "double416":
            return httpx.Response(416)
        raise AssertionError(step)

    _patch_client(monkeypatch, handler)

    q4 = hf_file_url(Q4_FILENAME)
    q3 = hf_file_url(Q3_FILENAME)
    assert "/resolve/main/" not in q4
    assert "/resolve/main/" not in q3
    assert "edc6f12e7bb90602ca1d34faecbec9844137b7fe" in q4
    assert "92d1611d9d709e3f5aa9820e44768d9eb78f8d9c" in q3

    with pytest.raises(RuntimeError):
        download_file(url, dest, expected_bytes=len(payload), sha256=digest)
    assert not dest.exists()
    assert partial.is_file()
    assert partial.read_bytes() == payload[:10]
    assert ranges == [""]

    mode["step"] = "resume206"
    free_for_resume = (len(payload) - 10) + _SLACK_BYTES
    monkeypatch.setattr(
        "arelis.setup.download.shutil.disk_usage",
        lambda _path: SimpleNamespace(
            free=free_for_resume, used=0, total=free_for_resume
        ),
    )
    download_file(url, dest, expected_bytes=len(payload), sha256=digest)
    monkeypatch.undo()
    _patch_client(monkeypatch, handler)
    assert dest.is_file()
    assert dest.read_bytes() == payload
    assert hashlib.sha256(dest.read_bytes()).hexdigest() == digest
    assert not partial.exists()
    assert ranges == ["", "bytes=10-"]

    dest.unlink()
    partial.write_bytes(payload[:10])
    mode["step"] = "ignore_range"
    download_file(url, dest, expected_bytes=len(payload), sha256=digest)
    assert dest.read_bytes() == payload
    assert hashlib.sha256(dest.read_bytes()).hexdigest() == digest
    assert ranges[-1] == "bytes=10-"

    dest.unlink()
    partial.unlink(missing_ok=True)
    mode["step"] = "bad_hash"
    with pytest.raises(RuntimeError, match="did not match"):
        download_file(url, dest, expected_bytes=len(payload), sha256=digest)
    assert not dest.exists()

    dest.unlink(missing_ok=True)
    partial.write_bytes(payload[:10])
    mode["step"] = "gone416"
    download_file(url, dest, expected_bytes=len(payload), sha256=digest)
    assert dest.read_bytes() == payload
    assert hashlib.sha256(dest.read_bytes()).hexdigest() == digest
    assert ranges[-1] == ""

    dest.unlink()
    partial.write_bytes(payload[:10])
    mode["step"] = "double416"
    before = calls["n"]
    with pytest.raises(RuntimeError):
        download_file(url, dest, expected_bytes=len(payload), sha256=digest)
    assert calls["n"] - before <= 2
    assert not dest.exists()

    dest.unlink(missing_ok=True)
    partial.write_bytes(payload[:10])
    mode["step"] = "stall_resume"
    stall = {"n": 0}

    def stream_or_stall(response, dest_path, **kwargs):
        if mode["step"] == "stall_resume" and stall["n"] == 0:
            stall["n"] = 1
            dest_path.write_bytes(dest_path.read_bytes() + payload[10:16])
            raise httpx.ReadTimeout("stalled")
        if mode["step"] == "silent90":
            clock["t"] = 91.0
            raise httpx.ReadTimeout("dead")
        return _stream_into(response, dest_path, **kwargs)

    monkeypatch.setattr(download_mod, "_stream_into", stream_or_stall)

    def stall_handler(request: httpx.Request) -> httpx.Response:
        header = request.headers.get("range") or request.headers.get("Range") or ""
        ranges.append(header)
        calls["n"] += 1
        if calls["n"] > 24:
            raise AssertionError("download looped")
        if mode["step"] == "stall_resume":
            if header == "bytes=16-":
                return httpx.Response(
                    206,
                    content=payload[16:],
                    headers={"Content-Range": "bytes 16-25/26"},
                )
            assert header == "bytes=10-"
            return httpx.Response(
                206,
                content=payload[10:16],
                headers={"Content-Range": "bytes 10-15/26"},
            )
        if mode["step"] == "silent90":
            return httpx.Response(206, content=b"", headers={"Content-Range": "bytes 10-9/26"})
        return handler(request)

    _patch_client(monkeypatch, stall_handler)
    download_file(url, dest, expected_bytes=len(payload), sha256=digest)
    assert dest.read_bytes() == payload
    assert ranges[-1] == "bytes=16-"

    dest.unlink()
    partial.write_bytes(payload[:10])
    mode["step"] = "silent90"
    clock = {"t": 0.0}
    monkeypatch.setattr(download_mod.time, "monotonic", lambda: clock["t"])
    with pytest.raises(RuntimeError, match="little while"):
        download_file(url, dest, expected_bytes=len(payload), sha256=digest)
    assert not dest.exists()
    assert partial.read_bytes() == payload[:10]


def test_download_stop_cancels_running_download_and_keeps_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qt_app
) -> None:
    payload = b"x" * (_READ + 32)
    digest = hashlib.sha256(payload).hexdigest()
    dest = tmp_path / "chat.gguf"
    partial = dest.with_name(dest.name + ".partial")
    wrote = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    def progress(_status: str, done: int, _total: int) -> None:
        if done > 0:
            wrote["n"] += 1

    _patch_client(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="stopped"):
        download_file(
            "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/edc6f12e7bb90602ca1d34faecbec9844137b7fe/chat.gguf",
            dest,
            expected_bytes=len(payload),
            sha256=digest,
            progress=progress,
            cancelled=lambda: wrote["n"] >= 1,
        )
    assert not dest.exists()
    assert partial.is_file()
    assert 0 < partial.stat().st_size < len(payload)

    # Stop used to zero the wizard bar even though the .partial file stayed.
    from arelis.setup.hardware import HardwareSnapshot
    from arelis.ui.setup_wizard import ModelSetupDialog

    monkeypatch.setattr(
        "arelis.ui.setup_wizard.probe_hardware",
        lambda: HardwareSnapshot(),
    )
    dialog = ModelSetupDialog()
    try:
        dialog._on_progress(
            "Downloading the chat model… 1.0 of 16.6 GB",
            1_000_000_000,
            16_600_710_112,
        )
        kept = dialog._bar.value()
        assert kept > 0
        dialog._on_failed(
            "The download was stopped. The unfinished file is still here, "
            "so the next try can continue."
        )
        assert dialog._bar.value() == kept
        assert dialog._bar.maximum() == 100
    finally:
        if dialog._probe is not None:
            dialog._probe.wait(2000)
        dialog.close()
        dialog.deleteLater()
        qt_app.processEvents()


def test_record_model_choice_pins_llamacpp_model_and_context_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = tmp_path / "config.local.yaml"
    monkeypatch.setattr("arelis.config.LOCAL_CONFIG_PATH", local)
    monkeypatch.setattr("arelis.setup.state.marker_path", lambda: tmp_path / "marker.json")
    monkeypatch.setattr("arelis.setup.state.state_dir", lambda: tmp_path)

    record_model_choice("Qwen3.6-35B-A3B-UD-Q3_K_M")
    data = yaml.safe_load(local.read_text(encoding="utf-8"))
    assert data["llamacpp"]["model"] == Q3_FILENAME
    assert data["llamacpp"]["default_cap"] == 32768
    assert "ollama" not in data


def test_llama_server_args_read_n_cpu_moe_context_and_ubatch_from_config() -> None:
    args = llama_server_args(
        binary="llama-server",
        model="m.gguf",
        mmproj="p.gguf",
        config={
            "llamacpp": {
                "n_cpu_moe": 16,
                "default_cap": 8192,
                "ubatch": 256,
            }
        },
    )
    assert args[args.index("--n-cpu-moe") + 1] == "16"
    assert args[args.index("-c") + 1] == "8192"
    assert args[args.index("-ub") + 1] == "256"
