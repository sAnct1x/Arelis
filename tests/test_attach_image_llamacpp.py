"""An attached chat picture must land as an image part on llama.cpp."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from arelis.attachments import last_user_has_pixels, matrix_turn_payload
from arelis.core.bus import EventBus
from arelis.core.claims import detect_vision_ask, unsupported_exactness_reply
from arelis.core.dash_filter import clean_dashes
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.llm.llamacpp import LlamaCppProvider
from arelis.llm.router import ModelRouter
from arelis.tools.base import ToolRegistry

_ASK = "what's in this picture"
_PATH_ASK = "Describe outputs/images/demo.png for me"
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


def _done_texts(bus: EventBus) -> list[str]:
    found: list[str] = []
    while not bus._queue.empty():
        event = bus._queue.get_nowait()
        if event.type == EventType.ASSISTANT_DONE:
            found.append(str(event.payload.get("text") or ""))
    return found


def _user_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for row in body.get("messages") or []
        if isinstance(row, dict) and row.get("role") == "user"
    ]


def _has_image_url(content: Any) -> bool:
    if not isinstance(content, list):
        return False
    return any(
        isinstance(part, dict) and part.get("type") == "image_url" for part in content
    )


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
                json={"n_ctx": 32768, "modalities": {"vision": True}},
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
    bus = EventBus()
    orch = Orchestrator(
        bus,
        router,
        ToolRegistry(),
        {
            "agent": {"max_rounds": 2, "confirm_timeout_s": 30},
            "workspace": {"roots": [str(tmp_path)]},
            "llamacpp": {"default_cap": 32768},
            "models": {"fast": "qwen", "research": "qwen"},
            "_persona_path": str(persona),
        },
        SessionMemory(),
    )
    try:
        await orch.on_user_message(Event(EventType.USER_MESSAGE, payload))

        assert seen, "llama.cpp never got a chat request"
        user_rows = _user_rows(seen[0])
        assert user_rows
        content = user_rows[-1].get("content")
        assert isinstance(content, list), content
        image_parts = [
            part
            for part in content
            if isinstance(part, dict) and part.get("type") == "image_url"
        ]
        assert image_parts
        url = str((image_parts[0].get("image_url") or {}).get("url") or "")
        assert url.startswith("data:image/")
        assert "base64," in url
        text_parts = [
            part for part in content if isinstance(part, dict) and part.get("type") == "text"
        ]
        assert text_parts
        body = str(text_parts[0].get("text") or "")
        assert _ASK in body
        assert "Images: call vision" not in body
        assert "Images: call ocr" not in body
        assert "→ vision" not in body
        assert "→ ocr" not in body
        assert "picture attached for you to see directly" in body
        assert detect_vision_ask(_ASK)
        done = _done_texts(bus)
        assert done
        assert done[-1] == "red"
        canned = clean_dashes(unsupported_exactness_reply(["vision"]))
        assert canned not in done

        # Older history keeps those image parts. This turn is path-only, so
        # the latest user line is text. A helper that scanned every user
        # line would treat the leftover pixels as a warrant.
        for message in orch.memory.messages:
            if message.role == "user":
                prior = message.content
                assert isinstance(prior, str)
                message.content = [
                    {"type": "text", "text": prior},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,xx"},
                    },
                ]
                break
        assert detect_vision_ask(_PATH_ASK)
        await orch.on_user_message(Event(EventType.USER_MESSAGE, {"text": _PATH_ASK}))
    finally:
        await client.aclose()

    assert len(seen) >= 2
    follow = _user_rows(seen[-1])
    assert follow
    assert _has_image_url(follow[0].get("content"))
    assert not _has_image_url(follow[-1].get("content"))
    assert last_user_has_pixels(seen[-1].get("messages") or []) is False
    path_done = _done_texts(bus)
    assert path_done
    assert path_done[-1] == canned
