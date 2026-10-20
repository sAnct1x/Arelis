"""llama-server provider: OpenAI SSE in, Ollama-shaped chunks out. Fake HTTP only."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx

from arelis.core.turn_prepare import _context_limits
from arelis.llm import build_router
from arelis.llm.errors import (
    LLAMACPP_DOWN_NOTICE,
    LLAMACPP_MODEL_NOTICE,
    OLLAMA_REJECT_NOTICE,
    classify_ollama_failure,
    classify_turn_failure,
)
from arelis.llm.llamacpp import LlamaCppProvider
from arelis.llm.ollama import OllamaProvider
from arelis.memory.indexer import MemoryIndexer


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

    # Leftover ids from an earlier tool_calls row must not pair after a
    # non-tool message. The unused clock id dies at the user turn.
    async for _item in provider.stream_chat(
        "qwen",
        [
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
            {"role": "user", "content": "thanks"},
            {"role": "tool", "tool_name": "clock", "content": "later"},
        ],
        think=False,
    ):
        pass
    stray = seen[-1]["messages"]
    unused = stray[0]["tool_calls"][1]["id"]
    assert stray[1]["tool_call_id"] == stray[0]["tool_calls"][0]["id"]
    assert stray[3]["tool_call_id"] != unused
    assert stray[3]["name"] == "clock"

    assert "embedding" not in await provider.capabilities("nomic-embed-text")

    # Exercise the indexer gate. Checking the class attribute is not enough:
    # deleting `_provider_embeds` in model_available must fail this.
    list_calls = {"n": 0}
    embed_calls = {"n": 0}
    orig_list = provider.list_models
    orig_embed = provider.embed

    async def counting_list() -> list[str]:
        list_calls["n"] += 1
        return ["nomic-embed-text"]

    async def counting_embed(model: str, texts: list[str]) -> list[list[float]]:
        del model, texts
        embed_calls["n"] += 1
        return [[0.1, 0.2]]

    provider.list_models = counting_list  # type: ignore[method-assign]
    provider.embed = counting_embed  # type: ignore[method-assign]
    indexer = MemoryIndexer(  # type: ignore[arg-type]
        _PendingEmbedStore(), provider, index_docs=False
    )
    skipped = await indexer.run_batch()
    assert skipped == 0
    assert list_calls["n"] == 0
    assert embed_calls["n"] == 0
    provider.list_models = orig_list  # type: ignore[method-assign]
    provider.embed = orig_embed  # type: ignore[method-assign]

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
    chosen = build_router(
        {
            **shipped,
            "llm": {"provider": "llamacpp"},
            "llamacpp": {"base_url": "http://127.0.0.1:8080"},
        }
    )
    assert isinstance(chosen.provider, LlamaCppProvider)
    assert chosen.provider.base_url == "http://127.0.0.1:8080"
    defaulted = build_router({**shipped, "llm": {"provider": "llamacpp"}})
    assert isinstance(defaulted.provider, LlamaCppProvider)
    assert defaulted.provider.base_url == "http://127.0.0.1:8080"
    bare = LlamaCppProvider()
    assert bare.base_url == "http://127.0.0.1:8080"
    await provider.close()
    await chosen.provider.close()
    await defaulted.provider.close()
    await bare.close()


class _PendingEmbedStore:
    """One pending chat row so a missing embeds gate would call embed."""

    def unembedded_messages(self, *, limit: int) -> list[dict[str, Any]]:
        del limit
        return [{"id": 1, "content": "hello"}]

    def upsert_embedding(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AssertionError("llama.cpp indexer must not write embeddings")

    def unembedded_document_chunks(self, *, limit: int) -> list[dict[str, Any]]:
        del limit
        return []

    def unembedded_mail(self, *, limit: int) -> list[dict[str, Any]]:
        del limit
        return []


async def test_llamacpp_history_budget_uses_server_n_ctx_and_cap() -> None:
    """64k config must not win over the server window or the per-model cap."""
    probe_timeouts: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/props", "/slots"}:
            timeout = request.extensions.get("timeout")
            read = None
            if isinstance(timeout, dict):
                read = timeout.get("read")
            elif timeout is not None:
                read = getattr(timeout, "read", None)
            if isinstance(read, (int, float)):
                probe_timeouts.append(float(read))
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
    assert probe_timeouts
    assert all(value == 5.0 for value in probe_timeouts)

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
        overflow_fail = classify_turn_failure(
            exc,
            config={"llm": {"provider": "llamacpp"}},
            backend=shifting,
        )
        assert overflow_fail.skip_tool_fallback is True
        assert "ollama" not in overflow_fail.chat.lower()
    # Ollama overflow 400 must still take JSON-tool fallback, same as main.
    ollama_overflow = classify_turn_failure(
        RuntimeError(
            "Ollama returned HTTP 400 for model `qwen`: "
            "request exceeds the available context size"
        ),
        config={"llm": {"provider": "ollama"}},
    )
    assert ollama_overflow.chat == OLLAMA_REJECT_NOTICE
    assert ollama_overflow.skip_tool_fallback is False
    assert await shifting.context_tokens("qwen") == 4096

    down = classify_ollama_failure(
        httpx.ConnectError("connection refused"),
        provider="llamacpp",
    )
    assert down.chat == LLAMACPP_DOWN_NOTICE
    assert "the local model server stopped responding" in down.chat.lower()
    assert "—" not in down.chat
    assert down.skip_tool_fallback is True
    http500 = classify_ollama_failure(
        RuntimeError("llama-server returned HTTP 503 for model `qwen`"),
        provider="llamacpp",
    )
    assert http500.chat == LLAMACPP_DOWN_NOTICE
    assert http500.skip_tool_fallback is True
    missing = classify_turn_failure(
        RuntimeError("llama-server returned HTTP 404 for model `qwen`"),
        config={"llm": {"provider": "llamacpp"}},
    )
    assert missing.chat == LLAMACPP_MODEL_NOTICE
    assert "ollama" not in missing.chat.lower()
    assert "—" not in missing.chat
    assert missing.skip_tool_fallback is True
    await provider.close()
    await bare.close()
    await dead.close()
    await shifting.close()
