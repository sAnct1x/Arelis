"""Vision looks stream native thinking into the dock, same as a text turn."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from tests.hardening_helpers import _collect, _config, _deny

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory
from arelis.llm.ollama import OllamaProvider
from arelis.llm.router import ModelRouter
from arelis.tools.base import ToolRegistry


@pytest.mark.asyncio
async def test_chat_with_images_streams_thinking() -> None:
    provider = OllamaProvider()
    seen: list[str] = []

    async def fake_stream(
        model: str,
        messages: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> AsyncIterator[tuple[str, Any]]:
        assert messages[0]["images"] == ["abc"]
        del model
        yield ("thinking", "looking at page 1")
        yield ("token", "problem 2.20")

    provider.stream_chat = fake_stream  # type: ignore[method-assign]

    async def on_thinking(chunk: str) -> None:
        seen.append(chunk)

    try:
        text = await provider.chat_with_images(
            "qwen3.5:9b",
            "look",
            ["abc"],
            on_thinking=on_thinking,
        )
    finally:
        await provider.close()

    assert text == "problem 2.20"
    assert seen == ["looking at page 1"]


@pytest.mark.asyncio
async def test_run_vision_forwards_think_sink() -> None:
    seen: list[str] = []

    class _Prov:
        async def chat_with_images(self, *args: Any, **kwargs: Any) -> str:
            sink = kwargs.get("on_thinking")
            if sink is not None:
                await sink("reading the diagram")
            del args
            return "a cone"

        async def sees_images(self, model: str) -> bool:
            del model
            return True

    router = ModelRouter(
        _Prov(),  # type: ignore[arg-type]
        {"fast": "qwen3.5:9b", "research": "qwen3.5:9b"},
        warm_on_start=False,
    )

    async def sink(chunk: str) -> None:
        seen.append(chunk)

    router.think_sink = sink
    router.active_model = "qwen3.5:9b"
    router.active_role = "fast"
    text = await router.run_vision("what is this", ["abc"])
    assert text == "a cone"
    assert seen == ["reading the diagram"]


@pytest.mark.asyncio
async def test_agent_loop_binds_vision_think_to_dock() -> None:
    class _Prov:
        async def sees_images(self, model: str) -> bool:
            del model
            return False

    router = ModelRouter(
        _Prov(),  # type: ignore[arg-type]
        {"fast": "qwen3.5:9b", "research": "qwen3.5:9b"},
        warm_on_start=False,
    )
    bus = EventBus()
    loop = AgentLoop(
        bus,
        router,
        ToolRegistry(),
        SessionMemory(),
        "persona",
        _config(),
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )
    assert router.think_sink is not None
    assert router.think_sink.__self__ is loop  # type: ignore[attr-defined]
    events = await _collect(bus, loop._publish_think_stream("looking at pages 1-3"))
    streamed = [
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING and e.payload.get("stream")
    ]
    assert streamed == ["looking at pages 1-3"]
    assert loop._last_round_thinking is True


@pytest.mark.asyncio
async def test_vision_walks_pages_one_at_a_time(tmp_path) -> None:
    from io import BytesIO

    from PIL import Image

    from arelis.tools.vision import VisionTool
    from arelis.workspace import WorkspaceRoots

    shots: list[int] = []

    class _Runner:
        async def run_vision(self, prompt: str, images_b64: list[str], **_k: Any) -> str:
            shots.append(len(images_b64))
            assert len(images_b64) == 1
            return f"saw {prompt[-20:]}"

        async def chat_sees_images(self) -> bool:
            return True

    folder = tmp_path / "outputs" / "images" / "pdf_pages" / "hw"
    folder.mkdir(parents=True)
    files: list[str] = []
    for i in range(1, 4):
        dest = folder / f"page_0{i}.jpg"
        image = Image.new("RGB", (40, 40), "white")
        buf = BytesIO()
        image.save(buf, format="JPEG")
        dest.write_bytes(buf.getvalue())
        files.append(str(dest))

    tool = VisionTool(WorkspaceRoots.from_paths([str(tmp_path)]), _Runner())
    result = await tool.run(paths=files, question="transcribe")
    assert result.ok
    assert shots == [1, 1, 1]
    assert "page 1 of 3" in result.output
    assert "page 3 of 3" in result.output


def test_vision_ignores_stray_path_when_paths_set() -> None:
    from arelis.tools.vision import VisionTool
    from arelis.workspace import WorkspaceRoots

    tool = VisionTool(WorkspaceRoots.from_paths(["."]), object())
    got = tool._collect_paths(
        {
            "path": "outputs/images/arelis_00028_-text-scale2-scale2.png",
            "paths": [
                r"C:\tmp\pdf_pages\hw\page_01.jpg",
                r"C:\tmp\pdf_pages\hw\page_02.jpg",
            ],
        }
    )
    assert got == [
        r"C:\tmp\pdf_pages\hw\page_01.jpg",
        r"C:\tmp\pdf_pages\hw\page_02.jpg",
    ]


@pytest.mark.asyncio
async def test_ocr_refuses_ink_page_image(tmp_path) -> None:
    from io import BytesIO

    from PIL import Image

    from arelis.tools.ocr import OcrTool
    from arelis.workspace import WorkspaceRoots

    dest = tmp_path / "outputs" / "images" / "pdf_pages" / "hw" / "page_01.jpg"
    dest.parent.mkdir(parents=True)
    image = Image.new("RGB", (40, 40), "white")
    buf = BytesIO()
    image.save(buf, format="JPEG")
    dest.write_bytes(buf.getvalue())

    tool = OcrTool(
        WorkspaceRoots.from_paths([str(tmp_path)]),
        output_dir=tmp_path / "ocr_out",
        runner=lambda _path, _lang: "garbled soup N = ???",
    )
    result = await tool.run(action="text", path=str(dest))
    assert result.ok is False
    assert "garbled soup" not in result.output
    assert "vision" in result.output.lower()
