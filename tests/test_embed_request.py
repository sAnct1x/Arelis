"""The embed request must not cold-load nomic-embed-text onto the GPU."""

from __future__ import annotations

import json

import httpx

from arelis.llm.ollama import OllamaProvider


async def test_embed_request_keeps_the_model_off_the_gpu() -> None:
    posted: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embed"
        posted.append(json.loads(request.content))
        return httpx.Response(200, json={"embeddings": [[0.25, 0.5]]})

    provider = OllamaProvider("http://127.0.0.1:9", timeout_s=1)
    original = provider._client
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:9",
    )
    try:
        vectors = await provider.embed("nomic-embed-text", ["one line"])
    finally:
        await provider.close()
        await original.aclose()

    assert vectors == [[0.25, 0.5]]
    body = posted[0]
    assert body["keep_alive"] != 0
    assert body["options"]["num_gpu"] == 0
