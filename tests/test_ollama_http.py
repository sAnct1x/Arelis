"""OllamaProvider against httpx.MockTransport — no live server required."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from arelis.llm.ollama import OllamaProvider, same_ollama_model
from arelis.llm.preflight import missing_models, model_is_available
from arelis.llm.router import ModelRouter


async def _with_transport(handler):
    provider = OllamaProvider(base_url="http://test")
    await provider.close()
    provider._client = httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    )
    return provider


@pytest.mark.asyncio
async def test_stream_chat_yields_tokens_then_metrics() -> None:
    lines = [
        json.dumps({"message": {"role": "assistant", "content": "Hel"}, "done": False}),
        json.dumps({"message": {"role": "assistant", "content": "lo"}, "done": False}),
        json.dumps(
            {
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "prompt_eval_count": 11,
                "eval_count": 2,
            }
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        return httpx.Response(200, text="\n".join(lines) + "\n")

    provider = await _with_transport(handler)
    try:
        events = [item async for item in provider.stream_chat("m", [{"role": "user", "content": "hi"}])]
    finally:
        await provider.close()

    assert events == [
        ("token", "Hel"),
        ("token", "lo"),
        ("metrics", {"prompt_eval_count": 11, "eval_count": 2}),
    ]


@pytest.mark.asyncio
async def test_missing_model_is_a_runtime_error_not_a_bare_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text='{"error":"model not found"}')

    provider = await _with_transport(handler)
    try:
        with pytest.raises(RuntimeError, match="HTTP 404"):
            async for _ in provider.stream_chat("missing", [{"role": "user", "content": "hi"}]):
                pass
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_connection_refused_surfaces_as_connect_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = await _with_transport(handler)
    try:
        with pytest.raises(httpx.ConnectError):
            async for _ in provider.stream_chat("m", [{"role": "user", "content": "hi"}]):
                pass
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_malformed_json_lines_are_skipped() -> None:
    body = "\n".join(
        [
            "not-json",
            json.dumps({"message": {"role": "assistant", "content": "ok"}, "done": False}),
            json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}),
        ]
    ) + "\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    provider = await _with_transport(handler)
    try:
        events = [item async for item in provider.stream_chat("m", [{"role": "user", "content": "hi"}])]
    finally:
        await provider.close()

    assert ("token", "ok") in events


@pytest.mark.asyncio
async def test_split_tool_call_chunks_are_merged() -> None:
    """OpenAI-style deltas: name first, then argument fragments with an index."""
    lines = [
        json.dumps(
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "index": 0,
                            "type": "function",
                            "function": {"name": "workspace", "arguments": ""},
                        }
                    ],
                },
                "done": False,
            }
        ),
        json.dumps(
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "index": 0,
                            "function": {"arguments": '{"action":'},
                        }
                    ],
                },
                "done": False,
            }
        ),
        json.dumps(
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "index": 0,
                            "function": {"arguments": '"list"}'},
                        }
                    ],
                },
                "done": True,
            }
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="\n".join(lines) + "\n")

    provider = await _with_transport(handler)
    try:
        events = [item async for item in provider.stream_chat("m", [{"role": "user", "content": "hi"}])]
    finally:
        await provider.close()

    calls = [payload for kind, payload in events if kind == "tool_calls"]
    assert len(calls) == 1
    assert calls[0][0]["function"]["name"] == "workspace"
    assert calls[0][0]["function"]["arguments"] == {"action": "list"}


@pytest.mark.asyncio
async def test_router_retries_connect_errors_before_the_first_chunk() -> None:
    class Flaky:
        def __init__(self) -> None:
            self.attempts = 0

        async def stream_chat(self, model, messages, **kwargs):
            self.attempts += 1
            if self.attempts < 3:
                raise httpx.ConnectError("down", request=httpx.Request("POST", "http://test"))
            yield ("token", "hi")

        async def unload(self, model: str) -> None:
            return None

        async def close(self) -> None:
            return None

    flaky = Flaky()
    router = ModelRouter(flaky, {"fast": "m"}, keep_alive="0")  # type: ignore[arg-type]
    events = [item async for item in router.stream("fast", [{"role": "user", "content": "x"}])]
    assert events == [("token", "hi")]
    assert flaky.attempts == 3


@pytest.mark.asyncio
async def test_router_does_not_retry_after_yielding_a_chunk() -> None:
    class MidFail:
        def __init__(self) -> None:
            self.attempts = 0

        async def stream_chat(self, model, messages, **kwargs):
            self.attempts += 1
            yield ("token", "partial")
            raise httpx.ConnectError("dropped", request=httpx.Request("POST", "http://test"))

        async def unload(self, model: str) -> None:
            return None

    provider = MidFail()
    router = ModelRouter(provider, {"fast": "m"}, keep_alive="0")  # type: ignore[arg-type]
    with pytest.raises(httpx.ConnectError):
        async for _ in router.stream("fast", [{"role": "user", "content": "x"}]):
            pass
    assert provider.attempts == 1


@pytest.mark.asyncio
async def test_router_does_not_retry_a_missing_model_runtime_error() -> None:
    class Missing:
        def __init__(self) -> None:
            self.attempts = 0

        async def stream_chat(self, model, messages, **kwargs):
            self.attempts += 1
            raise RuntimeError("Ollama returned HTTP 404 for model `gone`")
            yield  # pragma: no cover — make this an async generator

        async def unload(self, model: str) -> None:
            return None

    provider = Missing()
    router = ModelRouter(provider, {"fast": "gone"}, keep_alive="0")  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="404"):
        async for _ in router.stream("fast", [{"role": "user", "content": "x"}]):
            pass
    assert provider.attempts == 1


def test_preflight_detects_missing_configured_models() -> None:
    available = ["qwen2.5:7b", "deepseek-r1:8b-instruct"]
    assert model_is_available(available, "qwen2.5:7b")
    assert model_is_available(available, "deepseek-r1:8b")
    assert not model_is_available(available, "qwen2.5:14b")
    assert missing_models(
        available, {"fast": "qwen2.5:7b", "research": "qwen2.5:14b"}
    ) == [("research", "qwen2.5:14b")]


@pytest.mark.asyncio
async def test_embed_posts_keep_alive_zero() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})

    provider = await _with_transport(handler)
    try:
        vectors = await provider.embed("nomic-embed-text", ["hello"])
    finally:
        await provider.close()

    assert seen["path"] == "/api/embed"
    assert seen["body"]["keep_alive"] == 0
    assert vectors == [[0.1, 0.2]]


def test_same_ollama_model_matches_tags_not_sizes() -> None:
    assert same_ollama_model("qwen2.5:7b", "qwen2.5:7b")
    assert same_ollama_model("qwen2.5:7b:latest", "qwen2.5:7b")
    assert same_ollama_model("qwen2.5:7b-instruct", "qwen2.5:7b")
    assert not same_ollama_model("qwen2.5:14b", "qwen2.5:7b")
    assert not same_ollama_model("qwen2.5:7b", "qwen2.5:14b")


@pytest.mark.asyncio
async def test_pin_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/generate"
        return httpx.Response(500, text='{"error":"busy"}')

    provider = await _with_transport(handler)
    try:
        with pytest.raises(RuntimeError, match="HTTP 500"):
            await provider.pin("qwen2.5:7b", keep_alive=0)
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_running_models_reads_api_ps() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/ps"
        return httpx.Response(
            200,
            json={"models": [{"name": "qwen2.5:7b"}, {"model": "nomic-embed-text"}]},
        )

    provider = await _with_transport(handler)
    try:
        assert await provider.running_models() == ["qwen2.5:7b", "nomic-embed-text"]
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_wait_until_unloaded_returns_leftovers() -> None:
    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/ps"
        hits["n"] += 1
        return httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}]})

    provider = await _with_transport(handler)
    try:
        still = await provider.wait_until_unloaded(["qwen2.5:7b"], timeout_s=0.2)
    finally:
        await provider.close()

    assert still == ["qwen2.5:7b"]
    assert hits["n"] >= 1
