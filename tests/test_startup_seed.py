"""A chat-model look reseeds the prefix. A separate vision model does not."""

from __future__ import annotations

import base64
import io
from typing import Any

import pytest

from arelis.llm.startup import PrefixWarmup
from arelis.tools.vision import VisionTool
from arelis.workspace import WorkspaceRoots


def _png(path) -> str:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), (10, 20, 30)).save(path, format="PNG")
    return str(path)


class _Bus:
    async def publish(self, event: Any) -> None:
        del event


class _Provider:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def stream_chat(self, model, messages, **kwargs):
        self.calls.append((model, messages, kwargs))
        yield ("token", "x")


class _Router:
    def __init__(self, *, warm: bool, prefix: PrefixWarmup) -> None:
        self.warm_on_start = warm
        self.prefix_warmup = prefix
        self.bus = _Bus()
        self.provider = _Provider()
        self.active_model = "probe-chat"
        self.default_role = "fast"
        self.default_keep_alive = "30m"
        self.images: list[str] = []
        self._sees = True

    def model_for(self, role=None):
        del role
        return self.active_model

    async def chat_sees_images(self) -> bool:
        return self._sees

    async def run_vision(self, prompt, images_b64, **_kwargs):
        del prompt
        self.images.extend(images_b64)
        return "seen"


def _prefix() -> PrefixWarmup:
    return PrefixWarmup(
        messages=[
            {"role": "system", "content": "PERSONA"},
            {"role": "system", "content": "POLICY"},
        ],
        tools=[{"type": "function", "function": {"name": "weather"}}],
        num_ctx=4096,
    )


async def _settle() -> None:
    """Let a reseed scheduled after the tool result actually run."""
    from arelis.llm import startup as startup_mod

    task = startup_mod._reseed_task
    if task is not None and not task.done():
        await task


@pytest.mark.asyncio
async def test_vision_on_chat_model_reseeds_prefix(tmp_path) -> None:
    prefix = _prefix()
    router = _Router(warm=True, prefix=prefix)
    tool = VisionTool(WorkspaceRoots.from_paths([str(tmp_path)]), router)
    result = await tool.run(path=_png(tmp_path / "shot.png"), question="what is this")
    assert result.ok
    await _settle()
    assert router.provider.calls
    _model, messages, kwargs = router.provider.calls[0]
    assert messages == prefix.messages
    assert kwargs.get("tools") == prefix.tools

    cold = _Router(warm=False, prefix=prefix)
    cold_tool = VisionTool(WorkspaceRoots.from_paths([str(tmp_path)]), cold)
    cold_result = await cold_tool.run(
        path=_png(tmp_path / "cold.png"), question="what is this"
    )
    assert cold_result.ok
    await _settle()
    assert cold.provider.calls == []

    separate = _Router(warm=True, prefix=prefix)
    separate._sees = False
    separate_tool_edge = 768
    tool = VisionTool(
        WorkspaceRoots.from_paths([str(tmp_path)]),
        separate,
        max_edge=separate_tool_edge,
        chat_max_edge=1024,
    )
    wide = tmp_path / "wide.png"
    from PIL import Image

    Image.new("RGB", (1837, 400), (1, 2, 3)).save(wide, format="PNG")
    result = await tool.run(path=str(wide), question="what is this")
    assert result.ok
    await _settle()
    assert separate.provider.calls == []
    raw = base64.b64decode(separate.images[0])
    with Image.open(io.BytesIO(raw)) as opened:
        assert max(opened.size) == separate_tool_edge
