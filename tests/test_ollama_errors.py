"""Human copy when Ollama dies mid-turn — exception stays out of chat."""

from __future__ import annotations

import httpx

from arelis.llm.errors import (
    OLLAMA_DOWN_NOTICE,
    OLLAMA_GENERIC_NOTICE,
    OLLAMA_MODEL_NOTICE,
    OLLAMA_REJECT_NOTICE,
    OLLAMA_VRAM_NOTICE,
    classify_ollama_failure,
)


def test_connect_error_is_down_copy() -> None:
    fail = classify_ollama_failure(
        httpx.ConnectError("connection refused"),
        model="qwen2.5:7b",
        base_url="http://127.0.0.1:11434",
    )
    assert fail.chat == OLLAMA_DOWN_NOTICE
    assert "LLM error" not in fail.chat
    assert "ConnectError" in fail.detail
    assert "qwen2.5:7b" in fail.detail
    assert "11434" in fail.detail
    assert fail.skip_tool_fallback is True


def test_timeout_is_down_copy() -> None:
    fail = classify_ollama_failure(httpx.ReadTimeout("timed out"))
    assert fail.chat == OLLAMA_DOWN_NOTICE
    assert fail.skip_tool_fallback is True


def test_missing_model_names_the_tag() -> None:
    fail = classify_ollama_failure(
        RuntimeError("Ollama returned HTTP 404 for model `qwen2.5:7b`: not found"),
        model="qwen2.5:7b",
    )
    assert fail.chat == OLLAMA_MODEL_NOTICE.format(model="qwen2.5:7b")
    assert "qwen2.5:7b" in fail.chat
    assert fail.skip_tool_fallback is True


def test_http_500_is_down_not_tool_fallback() -> None:
    fail = classify_ollama_failure(
        RuntimeError("Ollama returned HTTP 502 for model `qwen2.5:7b`")
    )
    assert fail.chat == OLLAMA_DOWN_NOTICE
    assert fail.skip_tool_fallback is True


def test_http_400_may_still_json_fallback() -> None:
    fail = classify_ollama_failure(
        RuntimeError("Ollama returned HTTP 400 for model `qwen2.5:7b`: invalid tools")
    )
    assert fail.chat == OLLAMA_REJECT_NOTICE
    assert fail.skip_tool_fallback is False


def test_vram_lock_skips_json_fallback() -> None:
    fail = classify_ollama_failure(
        RuntimeError(
            "Could not load `qwen2.5:14b` in 90s. The 12 GB card needs the "
            "previous model fully unloaded first."
        ),
        model="qwen2.5:14b",
    )
    assert fail.chat == OLLAMA_VRAM_NOTICE
    assert fail.skip_tool_fallback is True
    assert "ComfyUI, games" not in fail.chat
    again = classify_ollama_failure(
        RuntimeError("GPU still has 11.0 GB dedicated in use after unloading Ollama."),
        role="research",
    )
    assert "research model" in again.chat


def test_unknown_exception_stays_generic() -> None:
    fail = classify_ollama_failure(ValueError("broken pipe in fitter"))
    assert fail.chat == OLLAMA_GENERIC_NOTICE
    assert fail.skip_tool_fallback is False
    assert "ValueError" in fail.detail
