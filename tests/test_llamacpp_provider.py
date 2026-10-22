"""llama-server provider: OpenAI SSE in, chat chunks out. Fake HTTP only."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import yaml

from arelis.config import DEFAULT_CONFIG_PATH
from arelis.core.memory import SessionMemory
from arelis.core.turn_prepare import _context_limits
from arelis.llm import build_router
from arelis.llm.errors import (
    LLAMACPP_DEVICE_NOTICE,
    LLAMACPP_DOWN_NOTICE,
    LLAMACPP_MODEL_NOTICE,
    LLAMACPP_RESTART_NOTICE,
    classify_model_failure,
    classify_turn_failure,
)
from arelis.llm.llama_launch import ensure_server, launch_args_for
from arelis.llm.llamacpp import (
    _EMBED_PROBE_RETRY_S,
    _PROBE_TIMEOUT_S,
    LlamaCppProvider,
)
from arelis.memory.indexer import MemoryIndexer
from arelis.memory.store import MemoryStore
from arelis.tools.recall import RecallTool

_CPU_EMBED_TOKEN = "ZXQ_CPU_EMBED_DOWN_325"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://llama.test",
    )


def _sse(events: list[dict[str, Any]]) -> bytes:
    lines = [f"data: {json.dumps(event)}" for event in events]
    lines.append("data: [DONE]")
    return ("\n".join(lines) + "\n").encode()


def _probe_read_timeout(request: httpx.Request) -> float | None:
    timeout = request.extensions.get("timeout")
    read = None
    if isinstance(timeout, dict):
        read = timeout.get("read")
    elif timeout is not None:
        read = getattr(timeout, "read", None)
    if isinstance(read, (int, float)):
        return float(read)
    return None


async def test_llamacpp_stream_maps_sse_and_refuses_pictures_and_embeddings(
    tmp_path: Path,
) -> None:
    """One chat round: thinking, text, a tool call, and usage.

    Pictures stay off until /props reports vision. The 35B launch line
    loads the Q8 mmproj and keeps 32 MoE layers on the CPU.
    """
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
        "models": {"fast": "qwen3.5:9b"},
        "router": {},
        "memory": {},
    }
    assert isinstance(build_router(shipped).provider, LlamaCppProvider)
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

    vision_seen: list[dict[str, Any]] = []

    def vision_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/props":
            return httpx.Response(200, json={"modalities": {"vision": True}})
        if request.url.path == "/v1/chat/completions":
            vision_seen.append(json.loads(request.content))
            body = _sse(
                [
                    {
                        "choices": [
                            {"delta": {"content": "yellow"}, "finish_reason": "stop"}
                        ]
                    }
                ]
            )
            return httpx.Response(200, content=body)
        return httpx.Response(404)

    vision_client = _client(vision_handler)
    vision = LlamaCppProvider(
        base_url="http://llama.test",
        client=vision_client,
    )
    assert await vision.sees_images("qwen") is True
    assert await vision.chat_with_images("qwen", "which bar", ["aaaa"]) == "yellow"
    posted_image = vision_seen[0]["messages"][0]["content"]
    assert posted_image[0] == {"type": "text", "text": "which bar"}
    assert posted_image[1]["type"] == "image_url"
    assert posted_image[1]["image_url"]["url"] == "data:image/jpeg;base64,aaaa"
    await vision_client.aclose()

    model = tmp_path / "Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
    model.write_bytes(b"gguf")
    template = tmp_path / "qwen36_35b_insys.jinja"
    template.write_text("{# patched #}", encoding="utf-8")
    args = launch_args_for(
        {
            "llamacpp": {
                "model": str(model),
                "binary": "llama-server",
                "base_url": "http://127.0.0.1:8080",
            }
        }
    )
    assert args is not None
    assert (
        args[args.index("--mmproj") + 1]
        == str((tmp_path / "mmproj-Qwen3.6-35B-A3B-Q8_0.gguf").resolve())
    )
    assert args[args.index("--n-cpu-moe") + 1] == "32"
    assert args[args.index("--image-max-tokens") + 1] == "1024"
    assert args[args.index("-fa") + 1] == "off"
    assert args[args.index("--cache-type-k") + 1] == "f16"
    assert args[args.index("--cache-type-v") + 1] == "f16"
    assert args[args.index("-c") + 1] == "32768"
    assert args[args.index("-b") + 1] == "4096"
    assert args[args.index("-ub") + 1] == "512"
    assert args[args.index("--jinja") + 1] == "--chat-template-file"
    assert args[args.index("--chat-template-file") + 1] == str(template.resolve())
    assert args[args.index("--host") + 1] == "127.0.0.1"
    assert args[args.index("--port") + 1] == "8080"
    assert args[args.index("-ngl") + 1] == "99"
    assert args[args.index("-np") + 1] == "1"

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


class _RecordingEmbedStore(_PendingEmbedStore):
    """Same pending row, but records a successful write."""

    def __init__(self) -> None:
        self.writes: list[tuple[int, str, list[float]]] = []

    def upsert_embedding(self, row_id: int, model: str, vector: list[float]) -> None:
        self.writes.append((row_id, model, vector))


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
        config={"llamacpp": {"default_cap": 65536}},
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
        config={"llamacpp": {"default_cap": 65536}},
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

    plain_loop = SimpleNamespace(
        config={"llamacpp": {"default_cap": 65536}},
        router=SimpleNamespace(provider=object(), model_for=lambda role: "qwen3.5:9b"),
        tool_output_chars=1000,
        _expected_tools=[],
    )
    kept, _ = await _context_limits(
        plain_loop, "fast", speak=False, skill_ids=[]
    )
    assert kept == 65536
    research_kept, _ = await _context_limits(
        plain_loop, "research", speak=False, skill_ids=[]
    )
    assert research_kept == 65536

    def down(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="down")

    dead = LlamaCppProvider(
        base_url="http://llama.test",
        client=_client(down),
    )
    assert await dead.context_tokens("qwen") == 8192
    dead_loop = SimpleNamespace(
        config={"llamacpp": {"default_cap": 65536}},
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
    assert await shifting.context_tokens("qwen") == 4096

    down = classify_model_failure(
        httpx.ConnectError("connection refused"),
        provider="llamacpp",
    )
    assert down.chat == LLAMACPP_DOWN_NOTICE
    assert "the local model stopped responding" in down.chat.lower()
    assert "—" not in down.chat
    assert down.skip_tool_fallback is True
    http500 = classify_model_failure(
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
    assert "—" not in missing.chat
    assert missing.skip_tool_fallback is True
    await provider.close()
    await bare.close()
    await dead.close()
    await shifting.close()


async def test_llamacpp_cpu_embeddings_follow_embed_url_and_stay_off_when_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Root cause: the 35B llama-server owns the card, so nomic-embed-text
    has to live on a second CPU llama-server. Reason: POST /v1/embeddings
    at llamacpp.embed_url, and embeds is True only while
    that server answers; otherwise recall stays on keywords. A failed
    probe retries after a cooldown so a later-started embed server is
    picked up without restarting Arelis. The indexer asks the provider
    each batch instead of latching the first False.
    """
    clock = {"t": 1_000.0}
    monkeypatch.setattr(
        "arelis.llm.llamacpp.time.monotonic", lambda: clock["t"]
    )
    chat_paths: list[str] = []
    embed_posts: list[tuple[str, dict[str, Any]]] = []
    probe_timeouts: list[float] = []
    embed_live = {"ok": False}
    down_probes = {"n": 0}

    def chat_handler(request: httpx.Request) -> httpx.Response:
        chat_paths.append(request.url.path)
        if request.url.path in {"/v1/embeddings", "/api/embed", "/api/tags"}:
            raise AssertionError(f"chat server must not handle {request.url.path}")
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(200, content=_sse([]))
        return httpx.Response(404)

    def embed_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/embed":
            raise AssertionError("legacy embed path must not be used")
        if request.url.path != "/v1/embeddings":
            return httpx.Response(404)
        body = json.loads(request.content)
        embed_posts.append((str(request.url), body))
        if body.get("input") == ["ok"]:
            read = _probe_read_timeout(request)
            if read is not None:
                probe_timeouts.append(read)
        texts = body.get("input")
        if not isinstance(texts, list):
            return httpx.Response(400, text="input must be a list")
        return httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": [0.25, 0.75], "index": i} for i in range(len(texts))
                ]
            },
        )

    def down_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/embeddings":
            body = json.loads(request.content) if request.content else {}
            if body.get("input") == ["ok"]:
                down_probes["n"] += 1
                read = _probe_read_timeout(request)
                if read is not None:
                    probe_timeouts.append(read)
            if not embed_live["ok"]:
                raise httpx.ConnectError("connection refused")
            return embed_handler(request)
        raise httpx.ConnectError("connection refused")

    up = LlamaCppProvider(
        base_url="http://llama.test",
        embed_url="http://embed.test",
        client=_client(chat_handler),
        embed_client=httpx.AsyncClient(
            transport=httpx.MockTransport(embed_handler),
            base_url="http://embed.test",
            timeout=300,
        ),
    )
    assert up.embeds is False
    assert await up.refresh_embeds() is True
    assert up.embeds is True
    # Probe must have hit the embed host, not the 35B chat host.
    assert embed_posts
    assert all("embed.test" in url for url, _ in embed_posts)
    assert all(body.get("input") == ["ok"] for _url, body in embed_posts)
    assert "/v1/embeddings" not in chat_paths
    assert "/api/embed" not in chat_paths

    vectors = await up.embed("nomic-embed-text", ["alpha", "beta"])
    assert vectors == [[0.25, 0.75], [0.25, 0.75]]
    assert embed_posts[-1][1]["input"] == ["alpha", "beta"]
    assert embed_posts[-1][1]["model"] == "nomic-embed-text"
    assert "embed.test" in embed_posts[-1][0]

    store = _RecordingEmbedStore()
    indexer = MemoryIndexer(store, up, index_docs=False)  # type: ignore[arg-type]
    written = await indexer.run_batch()
    assert written == 1
    assert store.writes == [(1, "nomic-embed-text", [0.25, 0.75])]

    assert await up.sees_images("qwen") is False
    try:
        await up.chat_with_images("qwen", "what", ["aaaa"])
        raise AssertionError("pictures should stay off")
    except RuntimeError as exc:
        assert "Pictures are off" in str(exc)
    assert "embedding" not in await up.capabilities("nomic-embed-text")

    down = LlamaCppProvider(
        base_url="http://llama.test",
        embed_url="http://embed.test",
        client=_client(chat_handler),
        embed_client=httpx.AsyncClient(
            transport=httpx.MockTransport(down_handler),
            base_url="http://embed.test",
            timeout=300,
        ),
    )
    assert down.embeds is False
    assert await down.refresh_embeds() is False
    assert down.embeds is False
    assert down_probes["n"] == 1
    try:
        await down.embed("nomic-embed-text", ["hello"])
        raise AssertionError("down embed server should keep embeddings off")
    except RuntimeError as exc:
        assert "Embeddings are off" in str(exc)
    assert down_probes["n"] == 1
    assert await down.refresh_embeds() is False
    assert down_probes["n"] == 1
    # Same indexer across down → up. Re-adding MemoryIndexer._available
    # must fail this: the first False would stick past the cooldown.
    down_store = _RecordingEmbedStore()
    down_indexer = MemoryIndexer(  # type: ignore[arg-type]
        down_store, down, index_docs=False
    )
    skipped = await down_indexer.run_batch()
    assert skipped == 0
    assert down_store.writes == []

    store = MemoryStore(tmp_path / "memory.db")
    embed_calls: list[tuple[str, list[str]]] = []
    try:
        store.start_session()
        SessionMemory(sink=store).add(
            "user", f"{_CPU_EMBED_TOKEN} lives in last night's chat."
        )

        async def would_embed(model: str, texts: list[str]) -> list[list[float]]:
            embed_calls.append((model, texts))
            return [[0.25, 0.75] for _ in texts]

        async def embed_available() -> bool:
            return await down.refresh_embeds()

        found = await RecallTool(
            store,
            embed=would_embed,
            embed_available=embed_available,
            embed_missing_note=" Semantic search is off; using keywords only.",
        ).run(action="search", query=_CPU_EMBED_TOKEN, source="chat")
        assert found.ok, found.output
        assert found.data.get("mode") == "keyword"
        assert found.data.get("fts") is True
        assert found.data["hits"], found.output
        assert _CPU_EMBED_TOKEN in found.output
        assert "full-text" in found.output
        assert "keyword + semantic" not in found.output
        assert embed_calls == []
        assert "Semantic search failed" not in found.output
        assert "Semantic search is off" in found.output
    finally:
        store.close()

    embed_live["ok"] = True
    clock["t"] += _EMBED_PROBE_RETRY_S
    assert await down.refresh_embeds() is True
    assert down.embeds is True
    assert down_probes["n"] == 2
    recovered = await down.embed("nomic-embed-text", ["hello"])
    assert recovered == [[0.25, 0.75]]
    recovered_batch = await down_indexer.run_batch()
    assert recovered_batch > 0
    assert down_store.writes == [(1, "nomic-embed-text", [0.25, 0.75])]
    assert probe_timeouts
    assert all(value == _PROBE_TIMEOUT_S for value in probe_timeouts)

    shipped = {
        "models": {"fast": "qwen3.5:9b"},
        "router": {},
        "memory": {},
    }
    chosen = build_router(
        {
            **shipped,
            "llm": {"provider": "llamacpp"},
            "llamacpp": {
                "base_url": "http://127.0.0.1:8080",
                "embed_url": "http://127.0.0.1:8081",
            },
        }
    )
    assert isinstance(chosen.provider, LlamaCppProvider)
    assert chosen.provider.embed_url == "http://127.0.0.1:8081"
    assert chosen.provider.embeds is False
    real = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    assert isinstance(real, dict)
    defaulted = build_router({**real, "llm": {"provider": "llamacpp"}})
    assert isinstance(defaulted.provider, LlamaCppProvider)
    assert defaulted.provider.embed_url == "http://127.0.0.1:8081"
    bare = LlamaCppProvider()
    assert bare.embed_url is None
    assert bare.embeds is False

    await up.close()
    await down.close()
    await chosen.provider.close()
    await defaulted.provider.close()
    await bare.close()


async def test_llamacpp_stream_reports_tool_arg_progress_before_tool_calls() -> None:
    """Argument slices must not stay silent until the stream ends.

    One content delta, then several tool_calls argument slices, then
    [DONE]. A progress yield has to land while those slices are still
    arriving, with the tool name and how many argument characters have
    landed so far. tool_calls stays last and parses. Partial JSON is
    not a call.
    """
    opening = '{"title":"Periodic table","body":"'
    first = opening + ("H" * 80)
    second = "e " * 40
    third = '"}'
    raw = first + second + third
    expect = json.loads(raw)
    assert len(first) > 64
    assert len(first) < len(raw)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/v1/chat/completions":
            return httpx.Response(404)
        slices = (
            {
                "index": 0,
                "function": {"name": "document", "arguments": first},
            },
            {"index": 0, "function": {"arguments": second}},
            {"index": 0, "function": {"arguments": third}},
        )
        events: list[dict[str, Any]] = [
            {
                "choices": [
                    {
                        "delta": {"content": "Here is the table."},
                        "finish_reason": None,
                    }
                ]
            }
        ]
        for piece in slices:
            events.append(
                {
                    "choices": [
                        {
                            "delta": {"tool_calls": [piece]},
                            "finish_reason": None,
                        }
                    ]
                }
            )
        return httpx.Response(200, content=_sse(events))

    provider = LlamaCppProvider(
        base_url="http://llama.test",
        client=_client(handler),
    )
    items: list[tuple[str, Any]] = []
    try:
        async for item in provider.stream_chat(
            "qwen",
            [{"role": "user", "content": "periodic table"}],
            think=False,
        ):
            items.append(item)
    finally:
        await provider.close()

    progress = [payload for kind, payload in items if kind == "tool_progress"]
    assert progress, "no progress while argument slices were still arriving"
    assert items[0] == ("token", "Here is the table.")
    assert items[-1][0] == "tool_calls"
    assert [kind for kind, _payload in items].count("tool_calls") == 1
    assert all(kind != "tool_calls" for kind, _payload in items[:-1])
    call = items[-1][1][0]["function"]
    assert call["name"] == "document"
    assert call["arguments"] == expect
    assert min(int(item["chars"]) for item in progress) < len(raw)
    assert all(item["name"] == "document" for item in progress)
    assert all(set(item) == {"name", "chars"} for item in progress)


def _compute_error_body() -> dict[str, Any]:
    """What llama-server sends when decode returns a compute failure."""
    return {
        "error": {
            "code": 500,
            "message": "Compute error.",
            "type": "server_error",
        }
    }


async def test_a_lost_graphics_device_fails_once_and_asks_for_a_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """/health stays ok after the graphics device is lost.

    Readiness is one generated token. A turn that dies the same way posts
    once. The graphics-card line is only the compute error. Any other
    HTTP 500 still needs a restart, without that line.
    """
    posts: list[dict[str, Any]] = []
    served: dict[str, Any] = {"error": _compute_error_body()}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/v1/chat/completions":
            body = json.loads(request.content)
            posts.append(body)
            if body.get("stream"):
                return httpx.Response(200, content=_sse([served["error"]]))
            return httpx.Response(500, json=served["error"])
        return httpx.Response(404)

    provider = LlamaCppProvider(
        base_url="http://llama.test",
        client=_client(handler),
    )
    try:
        async for _item in provider.stream_chat(
            "qwen",
            [{"role": "user", "content": "summarize that and email it"}],
        ):
            pass
    except Exception as exc:
        failure = classify_turn_failure(exc, model="qwen", backend=provider)
    else:
        raise AssertionError("a compute failure should fail the turn")
    assert len(posts) == 1
    assert failure.skip_tool_fallback is True
    assert failure.chat == LLAMACPP_DEVICE_NOTICE
    assert "\u2014" not in failure.chat
    assert "\u2013" not in failure.chat
    assert "HTTP" not in failure.chat

    try:
        await provider.pin("qwen")
    except Exception as exc:
        ready_failure = classify_turn_failure(exc, model="qwen", backend=provider)
    else:
        raise AssertionError("a one token check should fail when decode fails")
    assert len(posts) == 2
    assert posts[-1]["max_tokens"] == 1
    assert "tools" not in posts[-1]
    assert posts[-1].get("stream") is not True
    assert ready_failure.skip_tool_fallback is True
    assert ready_failure.chat == failure.chat

    launched = {"n": 0}

    def _get(url: str, timeout: float = 2.0, **kwargs: object) -> httpx.Response:
        del timeout, kwargs
        assert url.endswith("/health")
        return httpx.Response(200, json={"status": "ok"})

    def _post(url: str, json: dict[str, Any] | None = None, timeout: float = 60.0, **kwargs: object) -> httpx.Response:
        del timeout, kwargs
        assert url.endswith("/v1/chat/completions")
        posts.append(dict(json or {}))
        return httpx.Response(500, json=_compute_error_body())

    def _no_spawn(args: list[str]) -> None:
        del args
        launched["n"] += 1
        raise AssertionError("a dead device must not start a second server")

    monkeypatch.setattr("arelis.llm.llama_launch.httpx.get", _get)
    monkeypatch.setattr("arelis.llm.llama_launch.httpx.post", _post)
    monkeypatch.setattr("arelis.llm.llama_launch._spawn", _no_spawn)
    before = len(posts)
    try:
        ensure_server("http://127.0.0.1:8080", ["llama-server"])
    except Exception as exc:
        launch_failure = classify_turn_failure(exc, model="qwen")
    else:
        raise AssertionError("a listening server that cannot decode is not ready")
    assert launch_failure.skip_tool_fallback is True
    assert launch_failure.chat == failure.chat
    assert launched["n"] == 0
    assert len(posts) == before + 1
    assert posts[-1]["max_tokens"] == 1
    assert "tools" not in posts[-1]

    served["error"] = {
        "error": {
            "code": 500,
            "message": "boom",
            "type": "server_error",
        }
    }
    try:
        async for _item in provider.stream_chat(
            "qwen",
            [{"role": "user", "content": "again"}],
        ):
            pass
    except Exception as exc:
        other = classify_turn_failure(exc, model="qwen", backend=provider)
    else:
        raise AssertionError("a plain HTTP 500 should fail the turn")
    assert other.chat == LLAMACPP_RESTART_NOTICE
    assert other.skip_tool_fallback is True
    await provider.close()
