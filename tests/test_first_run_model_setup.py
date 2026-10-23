"""First-run download resume, model pin, and llama-server args from config."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml

from arelis.llm.llama_launch import llama_server_args
from arelis.setup.catalog import Q3_FILENAME, Q4_FILENAME
from arelis.setup.download import (
    _READ,
    _SLACK_BYTES,
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
        if calls["n"] > 8:
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


def test_download_stop_cancels_running_download_and_keeps_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
