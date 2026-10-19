"""A picture question stays on the hot chat call.

A long chat, then a question about a picture, then a later turn. The hot
model is called once per round. The picture rides on that chat. A later
turn still sends the same picture message. A one-shot look on the same
model is a separate call and does not count.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from PIL import Image

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory
from arelis.llm.ollama import OllamaProvider
from arelis.llm.router import ModelRouter
from arelis.tools.base import ToolRegistry
from arelis.tools.vision import VisionTool
from arelis.workspace import WorkspaceRoots
from tests.hardening_helpers import _collect

HOT = "qwen3.5:9b"
_KILN = "The kiln schedule stays on Tuesday."


class _ChatServer(OllamaProvider):
    """Ollama stand-in. Records each chat the way the server would see it."""

    def __init__(self, picture: str) -> None:
        super().__init__("http://127.0.0.1:9", timeout_s=5)
        self.guard_host_vram = False
        self.picture = picture
        self.calls: list[dict[str, Any]] = []

    async def sees_images(self, model: str) -> bool:
        return model == HOT

    async def running_ps(self) -> list[dict[str, Any]]:
        return []

    async def pin(self, model: str, **kwargs: Any) -> None:
        del model, kwargs

    async def unload(self, model: str) -> None:
        del model

    async def close(self) -> None:
        await self._client.aclose()

    async def stream_chat(self, model: str, messages: list[dict[str, Any]], **kwargs: Any):
        del kwargs
        sent = copy.deepcopy(messages)
        self.calls.append({"model": model, "messages": sent})
        if _is_lone_picture(sent):
            yield ("token", "blue square")
            return
        if any(item.get("role") == "tool" for item in sent):
            yield ("token", "A blue square.")
            return
        yield (
            "tool_calls",
            [
                {
                    "type": "function",
                    "function": {
                        "name": "vision",
                        "arguments": {
                            "path": self.picture,
                            "question": "what color is the square",
                        },
                    },
                }
            ],
        )


def _is_lone_picture(messages: list[dict[str, Any]]) -> bool:
    if len(messages) != 1:
        return False
    only = messages[0]
    return only.get("role") == "user" and bool(only.get("images"))


def _config() -> dict[str, Any]:
    return {
        "agent": {
            "max_rounds": 4,
            "json_fallback": False,
            "confirm_vision": False,
            "chat_fast_path": False,
            "native_tool_calling": True,
        },
        "ollama": {"num_ctx": 8192},
        "models": {
            "fast": HOT,
            "research": HOT,
            "vision": "qwen2.5vl:3b",
        },
        "voice": {"enabled": False},
        "_persona_path": "does-not-exist.md",
    }


def _loop(server: _ChatServer, root: str) -> AgentLoop:
    router = ModelRouter(
        server,
        {"fast": HOT, "research": HOT},
        warm_on_start=False,
        rewarm_after_switch=False,
    )
    tools = ToolRegistry()
    tools.register(
        VisionTool(
            WorkspaceRoots.from_paths([root]),
            router,
            model="qwen2.5vl:3b",
        )
    )
    return AgentLoop(
        EventBus(),
        router,
        tools,
        SessionMemory(),
        "persona",
        _config(),
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )


async def _allow(*_args: Any, **_kwargs: Any) -> str:
    return "allow"


def _seed(memory: SessionMemory) -> None:
    for index in range(16):
        memory.add("user", f"Note {index}. {_KILN}")
        memory.add("assistant", f"Kept note {index}. Tuesday still stands.")


def _round_count(events: list[Any]) -> int:
    count = 0
    for event in events:
        if event.type != EventType.THINKING:
            continue
        text = str(event.payload.get("text") or "")
        if text.startswith("round ") and text.endswith("model step"):
            count += 1
    return count


def _picture_message(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in messages:
        images = item.get("images")
        if isinstance(images, list) and images:
            return {
                "role": item.get("role"),
                "content": item.get("content"),
                "images": list(images),
            }
    return None


def _separate_image_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A same-model look whose prompt is not the running chat."""
    found = []
    for call in calls:
        if call["model"] != HOT:
            continue
        messages = call["messages"]
        has_picture = _picture_message(messages) is not None
        in_chat = any(_KILN in str(item.get("content") or "") for item in messages)
        if has_picture and not in_chat:
            found.append(call)
    return found


@pytest.mark.asyncio
async def test_long_chat_picture_stays_on_the_hot_model(tmp_path) -> None:
    picture = tmp_path / "square.png"
    Image.new("RGB", (8, 8), (0, 0, 255)).save(picture)
    server = _ChatServer(str(picture))
    loop = _loop(server, str(tmp_path))
    _seed(loop.memory)

    before = len(server.calls)
    picture_events = await _collect(
        loop.bus,
        loop.run("what is in this picture? the file is the blue square I saved", "fast"),
    )
    picture_calls = server.calls[before:]
    rounds = _round_count(picture_events)
    separate = _separate_image_calls(picture_calls)
    assert not separate, (
        "picture question made a separate same-model image call "
        f"({len(separate)} of {len(picture_calls)} calls, {rounds} rounds) "
        "instead of attaching the picture to the chat"
    )
    assert rounds >= 1
    assert len(picture_calls) == rounds, (
        f"{len(picture_calls)} model calls for {rounds} rounds on {HOT}"
    )
    assert {call["model"] for call in picture_calls} == {HOT}

    attached = [
        message
        for call in picture_calls
        if any(_KILN in str(item.get("content") or "") for item in call["messages"])
        for message in call["messages"]
        if _picture_message([message]) is not None
    ]
    assert len(attached) == 1
    saved = _picture_message([attached[0]])
    assert saved is not None
    assert saved["role"] == "user"
    assert saved["images"]

    before = len(server.calls)
    await _collect(
        loop.bus,
        loop.run("what day did we keep for the kiln schedule?", "fast"),
    )
    later_calls = server.calls[before:]
    assert later_calls
    assert _separate_image_calls(later_calls) == []
    later_pictures = [
        _picture_message([item])
        for call in later_calls
        for item in call["messages"]
        if _picture_message([item]) is not None
    ]
    assert later_pictures == [saved]
