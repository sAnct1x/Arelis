"""The embed request must not cold-load nomic-embed-text onto the GPU."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import yaml

from arelis.config import DEFAULT_CONFIG_PATH
from arelis.llm import build_router
from arelis.llm.ollama import OllamaProvider, same_ollama_model


async def test_embed_request_keeps_the_model_off_the_gpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shipped = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    assert isinstance(shipped, dict)
    memory = shipped["memory"]
    captured: dict[str, Any] = {}
    real_init = OllamaProvider.__init__

    def _capture_init(self, *args, **kwargs):
        captured.update(kwargs)
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(OllamaProvider, "__init__", _capture_init)
    # The settle sleep is 3s and this test only cares who was asked to leave.
    monkeypatch.setattr("arelis.llm.router._VRAM_SETTLE_S", 0)
    router = build_router(shipped)
    provider = router.provider
    # Shipped memory.embed_num_gpu has to arrive through build_router.
    assert captured.get("embed_num_gpu") == memory["embed_num_gpu"] == 0
    assert captured.get("embed_keep_alive") == memory["embed_keep_alive"]

    posted: list[dict] = []
    unloaded: list[str] = []
    resident: list[dict[str, Any]] = [
        {"name": "qwen3.5:9b", "size_vram": 8_000_000_000},
        {"name": "nomic-embed-text", "size_vram": 0},
        {"name": "other:7b", "size_vram": 4_000_000_000},
        {"name": "mystery:3b"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/embed":
            posted.append(json.loads(request.content))
            return httpx.Response(200, json={"embeddings": [[0.25, 0.5]]})
        if path == "/api/ps":
            return httpx.Response(200, json={"models": resident})
        if path in {"/api/generate", "/api/chat"}:
            body = json.loads(request.content)
            model = str(body.get("model") or "")
            if body.get("keep_alive") == 0 and model:
                unloaded.append(model)
                resident[:] = [
                    row
                    for row in resident
                    if not same_ollama_model(str(row.get("name") or ""), model)
                ]
            return httpx.Response(200, json={})
        return httpx.Response(404)

    original = provider._client
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=provider.base_url,
    )
    try:
        vectors = await provider.embed("nomic-embed-text", ["one line"])
        body = posted[0]
        assert vectors == [[0.25, 0.5]]
        assert body["keep_alive"] != 0
        assert body["keep_alive"] == memory["embed_keep_alive"]
        assert body["options"]["num_gpu"] == memory["embed_num_gpu"] == 0
        await router._evict_others(keep="qwen3.5:9b")
        # nomic holds no VRAM and stays. mystery has no size_vram, so it
        # is still evicted. other holds VRAM and is not the chat model.
        assert set(unloaded) == {"other:7b", "mystery:3b"}
    finally:
        await provider.close()
        await original.aclose()
