"""Vision looks stream native thinking into the dock, same as a text turn."""

from __future__ import annotations

from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory
from arelis.llm.router import ModelRouter
from arelis.tools.base import ToolRegistry
from tests.hardening_helpers import _collect, _config, _deny


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
