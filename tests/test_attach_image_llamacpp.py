"""An attached chat picture must land as an image part on llama.cpp."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from arelis.attachments import matrix_turn_payload
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.llm.llamacpp import LlamaCppProvider
from arelis.llm.router import ModelRouter
from arelis.tools.base import ToolRegistry

_ASK = "what color is the circle"
# 1x1 red PNG. Same bytes as the paperclip driver test.
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _sse(events: list[dict[str, Any]]) -> bytes:
    lines = [f"data: {json.dumps(event)}" for event in events]
    lines.append("data: [DONE]")
    return ("\n".join(lines) + "\n").encode()


@pytest.mark.asyncio
async def test_attached_image_is_image_part_in_llamacpp_request(
    tmp_path: Path,
) -> None:
    """Paperclip picture becomes an image_url part on the llama.cpp POST."""
    png = tmp_path / "circle.png"
    png.write_bytes(_PNG)
    payload = matrix_turn_payload(_ASK, [png])
    assert payload.get("attachments")

    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/props", "/slots"}:
            return httpx.Response(
                200,
                json={"n_ctx": 4096, "modalities": {"vision": True}},
            )
        if request.url.path == "/v1/chat/completions":
            seen.append(json.loads(request.content))
            body = _sse(
                [
                    {
                        "choices": [
                            {"delta": {"content": "red"}, "finish_reason": "stop"}
                        ]
                    }
                ]
            )
            return httpx.Response(200, content=body)
        return httpx.Response(404)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://llama.test",
    )
    provider = LlamaCppProvider(base_url="http://llama.test", client=client)
    router = ModelRouter(
        provider,
        {"fast": "qwen", "research": "qwen"},
        warm_on_start=False,
        rewarm_after_switch=False,
    )
    persona = Path(__file__).resolve().parents[1] / "arelis" / "persona" / "arelis.md"
    orch = Orchestrator(
        EventBus(),
        router,
        ToolRegistry(),
        {
            "agent": {"max_rounds": 2, "confirm_timeout_s": 30},
            "workspace": {"roots": [str(tmp_path)]},
            "llamacpp": {"default_cap": 4096},
            "models": {"fast": "qwen", "research": "qwen"},
            "_persona_path": str(persona),
        },
        SessionMemory(),
    )
    try:
        await orch.on_user_message(Event(EventType.USER_MESSAGE, payload))
    finally:
        await client.aclose()

    assert seen, "llama.cpp never got a chat request"
    user_rows = [
        row
        for row in seen[0].get("messages") or []
        if isinstance(row, dict) and row.get("role") == "user"
    ]
    assert user_rows
    content = user_rows[-1].get("content")
    assert isinstance(content, list), content
    image_parts = [part for part in content if isinstance(part, dict) and part.get("type") == "image_url"]
    assert image_parts
    url = str((image_parts[0].get("image_url") or {}).get("url") or "")
    assert url.startswith("data:image/")
    assert "base64," in url
    text_parts = [part for part in content if isinstance(part, dict) and part.get("type") == "text"]
    assert text_parts
    body = str(text_parts[0].get("text") or "")
    assert _ASK in body
    assert "Images: call vision" not in body
    assert "Images: call ocr" not in body
    assert "→ vision" not in body
    assert "→ ocr" not in body
    assert "picture attached for you to see directly" in body
