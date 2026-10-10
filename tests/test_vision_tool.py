"""Chat-model looks shrink a pasted screenshot before it is sent."""

from __future__ import annotations

import base64
import io
from typing import Any

import pytest

from arelis.tools.vision import VisionTool
from arelis.workspace import WorkspaceRoots


def _png(path, size: tuple[int, int]) -> str:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (20, 80, 140)).save(path, format="PNG")
    return str(path)


class _Runner:
    def __init__(self, *, chat_sees: bool) -> None:
        self.chat_sees = chat_sees
        self.images: list[str] = []

    async def chat_sees_images(self) -> bool:
        return self.chat_sees

    async def run_vision(
        self,
        prompt: str,
        images_b64: list[str],
        **_kwargs: Any,
    ) -> str:
        del prompt
        self.images.extend(images_b64)
        return "a screenshot of a window"


def _long_edge(payload: str) -> int:
    from PIL import Image

    raw = base64.b64decode(payload)
    with Image.open(io.BytesIO(raw)) as opened:
        return max(opened.size)


@pytest.mark.asyncio
async def test_chat_sees_look_uses_1024_edge(tmp_path) -> None:
    path = _png(tmp_path / "paste.png", size=(1837, 1116))
    runner = _Runner(chat_sees=True)
    tool = VisionTool(WorkspaceRoots.from_paths([str(tmp_path)]), runner)
    result = await tool.run(path=path, question="what is on screen")
    assert result.ok
    assert runner.images
    assert _long_edge(runner.images[0]) <= 1024
