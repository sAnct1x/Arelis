"""llama-server provider: OpenAI SSE in, Ollama-shaped chunks out. Fake HTTP only."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx

from arelis.core.turn_prepare import _context_limits
from arelis.llm import build_router
from arelis.llm.llamacpp import LlamaCppProvider
from arelis.llm.ollama import OllamaProvider


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://llama.test",
    )


def _sse(events: list[dict[str, Any]]) -> bytes:
    lines = [f"data: {json.dumps(event)}" for event in events]
    lines.append("data: [DONE]")
    return ("\n".join(lines) + "\n").encode()


async def test_llamacpp_stream_maps_sse_and_refuses_pictures_and_embeddings() -> None:
    """One chat round: thinking, text, a tool call, and usage. Pictures stay off."""
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/chat/completions":
            seen.append(json.loads(request.content))
            body = _sse(
                [
                    {
                        "choices": [
                            {
                                "delta": {"reasoning_content": "look"},
                                "finish_reason": None,
                            }
                        ]
                    },
                    {
                        "choices": [
                            {"delta": {"content": "hi"}, "finish_reason": None}
                        ]
                    },
                    {
                        "choices": [
                            {
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "function": {
                                                "name": "weather",
                                                "arguments": '{"city":"X"}',
                                            },
                                        }
                                    ]
                                },
                                "finish_reason": "tool_calls",
                            }
                        ],
                        "usage": {"prompt_tokens": 12, "completion_tokens": 3},
                    },
                ]
            )
            return httpx.Response(200, content=body)
        return httpx.Response(404)

    provider = LlamaCppProvider(
        base_url="http://llama.test",
        client=_client(handler),
    )
    kinds: list[tuple[str, Any]] = []
    async for item in provider.stream_chat(
        "qwen",
        [{"role": "tool", "tool_name": "weather", "content": "cold"}],
        options={"temperature": 0.1, "num_ctx": 65536, "num_predict": 1},
        tools=[{"type": "function", "function": {"name": "weather"}}],
        think=False,
    ):
        kinds.append(item)

    assert [kind for kind, _ in kinds] == ["thinking", "token", "metrics", "tool_calls"]
    assert kinds[0][1] == "look"
    assert kinds[1][1] == "hi"
    assert kinds[2][1]["prompt_eval_count"] == 12
    assert kinds[2][1]["eval_count"] == 3
    assert kinds[3][1][0]["function"]["name"] == "weather"
    assert kinds[3][1][0]["function"]["arguments"] == {"city": "X"}

    posted = seen[0]
    assert posted["chat_template_kwargs"] == {"enable_thinking": False}
    assert posted["temperature"] == 0.1
    assert posted["max_tokens"] == 1
    assert "num_ctx" not in posted
    assert "keep_alive" not in posted
    assert posted["messages"][0]["name"] == "weather"
    assert posted["tools"][0]["function"]["name"] == "weather"

    assert await provider.sees_images("qwen") is False
    try:
        await provider.chat_with_images("qwen", "what", ["aaaa"])
        raise AssertionError("pictures should be off")
    except RuntimeError as exc:
        assert "Pictures are off" in str(exc)
    try:
        await provider.embed("nomic-embed-text", ["hello"])
        raise AssertionError("embeddings should be off")
    except RuntimeError as exc:
        assert "Embeddings are off" in str(exc)

    shipped = {
        "ollama": {"base_url": "http://127.0.0.1:11434"},
        "models": {"fast": "qwen3.5:9b"},
        "router": {},
        "memory": {},
    }
    assert isinstance(build_router(shipped).provider, OllamaProvider)
    chosen = build_router({**shipped, "llm": {"provider": "llamacpp"}})
    assert isinstance(chosen.provider, LlamaCppProvider)
    await provider.close()
    await chosen.provider.close()


async def test_llamacpp_history_budget_uses_server_n_ctx_and_cap() -> None:
    """64k config must not win over the server window or the per-model cap."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/props":
            return httpx.Response(200, json={"default_generation_settings": {}})
        if request.url.path == "/slots":
            return httpx.Response(200, json=[{"id": 0, "n_ctx": 32768}])
        return httpx.Response(404)

    provider = LlamaCppProvider(
        base_url="http://llama.test",
        client=_client(handler),
        context_caps={"qwen3.6": 30000},
        default_cap=32768,
    )
    loop = SimpleNamespace(
        config={"ollama": {"num_ctx": 65536, "research_num_ctx": 65536}},
        router=SimpleNamespace(provider=provider, model_for=lambda role: "qwen3.6"),
        tool_output_chars=1000,
        _expected_tools=[],
    )
    num_ctx, _reserve = await _context_limits(
        loop, "fast", speak=False, skill_ids=[]
    )
    assert num_ctx == 30000
    assert loop._turn_num_ctx == 30000

    research, _ = await _context_limits(
        loop, "research", speak=False, skill_ids=[]
    )
    assert research == 30000

    bare = LlamaCppProvider(
        base_url="http://llama.test",
        client=_client(handler),
        default_cap=32768,
    )
    other = SimpleNamespace(
        config={"ollama": {"num_ctx": 65536}},
        router=SimpleNamespace(provider=bare, model_for=lambda role: "other"),
        tool_output_chars=1000,
        _expected_tools=[],
    )
    # props has no n_ctx, so the second client reads /slots (32768) and the cap.
    # Fresh provider: cache is empty, so it probes again.
    measured, _ = await _context_limits(
        other, "fast", speak=False, skill_ids=[]
    )
    assert measured == 32768

    ollama_loop = SimpleNamespace(
        config={"ollama": {"num_ctx": 65536, "research_num_ctx": 8192}},
        router=SimpleNamespace(provider=object(), model_for=lambda role: "qwen3.5:9b"),
        tool_output_chars=1000,
        _expected_tools=[],
    )
    kept, _ = await _context_limits(
        ollama_loop, "fast", speak=False, skill_ids=[]
    )
    assert kept == 65536
    research_ollama, _ = await _context_limits(
        ollama_loop, "research", speak=False, skill_ids=[]
    )
    assert research_ollama == 8192
    await provider.close()
    await bare.close()
