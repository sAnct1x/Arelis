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


_PLAIN_MISSING = "The vision model qwen2.5vl:3b isn't downloaded yet."


def _assert_plain_missing(text: str) -> None:
    assert text == _PLAIN_MISSING
    assert "`" not in text
    assert "\u2014" not in text
    assert "\u2013" not in text


@pytest.mark.asyncio
async def test_missing_vision_model_is_plain_speech(tmp_path) -> None:
    path = _png(tmp_path / "shot.png", size=(32, 32))

    async def not_downloaded() -> bool:
        return False

    tool = VisionTool(
        WorkspaceRoots.from_paths([str(tmp_path)]),
        _Runner(chat_sees=False),
        model="qwen2.5vl:3b",
        model_available=not_downloaded,
    )
    result = await tool.run(path=path)
    assert result.ok is False
    assert result.data.get("code") == "MODEL_MISSING"
    _assert_plain_missing(result.output)


def test_vision_runtime_miss_is_the_same_plain_line() -> None:
    tool = VisionTool(
        WorkspaceRoots.from_paths(["."]),
        object(),
        model="qwen2.5vl:3b",
    )
    result = tool._vision_error(
        RuntimeError("model 'qwen2.5vl:3b' not found"),
        {"sent_px": "32x32"},
    )
    assert result.ok is False
    assert result.data.get("code") == "MODEL_MISSING"
    assert result.data.get("model") == "qwen2.5vl:3b"
    _assert_plain_missing(result.output)
