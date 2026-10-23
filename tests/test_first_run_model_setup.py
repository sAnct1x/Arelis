"""First-run download resume, model pin, and llama-server args from config."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest
import yaml

from arelis.llm.llama_launch import llama_server_args
from arelis.setup.catalog import Q3_FILENAME
from arelis.setup.download import download_file
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
    ranges: list[str] = []
    wave = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        header = request.headers.get("range") or request.headers.get("Range") or ""
        ranges.append(header)
        wave["n"] += 1
        if wave["n"] == 1:
            return httpx.Response(200, content=payload[:10])
        assert header == "bytes=10-"
        return httpx.Response(
            206,
            content=payload[10:],
            headers={"Content-Range": "bytes 10-25/26"},
        )

    _patch_client(monkeypatch, handler)

    with pytest.raises(RuntimeError):
        download_file(
            "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/chat.gguf",
            dest,
            expected_bytes=len(payload),
            sha256=digest,
        )
    partial = dest.with_name(dest.name + ".partial")
    assert not dest.exists()
    assert partial.is_file()
    assert partial.read_bytes() == payload[:10]

    download_file(
        "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/chat.gguf",
        dest,
        expected_bytes=len(payload),
        sha256=digest,
    )
    assert dest.is_file()
    assert dest.read_bytes() == payload
    assert hashlib.sha256(dest.read_bytes()).hexdigest() == digest
    assert not partial.exists()
    assert ranges == ["", "bytes=10-"]


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
