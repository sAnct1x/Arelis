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

    # Second round: Arelis stores arguments as a dict and no id, and the tool
    # row has tool_name but no tool_call_id. The wire has to fix all three.
    async for _item in provider.stream_chat(
        "qwen",
        [
            {"role": "user", "content": "weather?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": "weather",
                            "arguments": {"city": "X"},
                        },
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "clock",
                            "arguments": {"tz": "UTC"},
                        },
                    },
                ],
            },
            {"role": "tool", "tool_name": "weather", "content": "cold"},
            {"role": "tool", "tool_name": "clock", "content": "noon"},
        ],
        think=False,
    ):
        pass

    follow = seen[-1]["messages"]
    calls = follow[1]["tool_calls"]
    assert len(calls) == 2
    assert isinstance(calls[0]["function"]["arguments"], str)
    assert json.loads(calls[0]["function"]["arguments"]) == {"city": "X"}
    assert isinstance(calls[1]["function"]["arguments"], str)
    assert json.loads(calls[1]["function"]["arguments"]) == {"tz": "UTC"}
    assert isinstance(calls[0]["id"], str) and calls[0]["id"]
    assert isinstance(calls[1]["id"], str) and calls[1]["id"]
    assert calls[0]["id"] != calls[1]["id"]
    assert follow[2]["tool_call_id"] == calls[0]["id"]
    assert follow[3]["tool_call_id"] == calls[1]["id"]
    assert follow[2]["name"] == "weather"
    assert "embedding" not in await provider.capabilities("nomic-embed-text")

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

    def down(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="down")

    dead = LlamaCppProvider(
        base_url="http://llama.test",
        client=_client(down),
    )
    assert await dead.context_tokens("qwen") == 8192
    dead_loop = SimpleNamespace(
        config={"ollama": {"num_ctx": 65536}},
        router=SimpleNamespace(provider=dead, model_for=lambda role: "qwen"),
        tool_output_chars=1000,
        _expected_tools=[],
    )
    limited, _ = await _context_limits(
        dead_loop, "fast", speak=False, skill_ids=[]
    )
    assert limited == 8192

    probes = {"n": 0}

    def overflow(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(
                400,
                text="request exceeds the available context size (n_ctx = 4096)",
            )
        if request.url.path == "/props":
            probes["n"] += 1
            window = 32768 if probes["n"] == 1 else 4096
            return httpx.Response(200, json={"n_ctx": window})
        return httpx.Response(404)

    shifting = LlamaCppProvider(
        base_url="http://llama.test",
        client=_client(overflow),
        default_cap=32768,
    )
    assert await shifting.context_tokens("qwen") == 32768
    try:
        async for _item in shifting.stream_chat(
            "qwen", [{"role": "user", "content": "hi"}]
        ):
            pass
        raise AssertionError("overflow should fail the request")
    except RuntimeError as exc:
        assert "context" in str(exc).lower()
    assert await shifting.context_tokens("qwen") == 4096
    await provider.close()
    await bare.close()
    await dead.close()
    await shifting.close()
