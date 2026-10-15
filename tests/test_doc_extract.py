from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from arelis.core.look import inspect_ocr_text
from arelis.tools.doc_extract import DocExtractTool, build_simple_pdf_bytes
from arelis.tools.pdf_pages import build_jpeg_page_pdf_bytes


def _jpeg(width: int = 80, height: int = 40) -> bytes:
    image = Image.new("RGB", (width, height), "white")
    buf = BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


def _write_jpeg_pdf(folder: Path, name: str = "scan.pdf") -> Path:
    dest = folder / name
    dest.write_bytes(build_jpeg_page_pdf_bytes(_jpeg(), 80, 40))
    return dest


@pytest.mark.asyncio
async def test_text_pdf_extracts(tmp_path: Path) -> None:
    pdf = tmp_path / "note.pdf"
    pdf.write_bytes(build_simple_pdf_bytes("hello from the text layer"))
    tool = DocExtractTool([str(tmp_path)])
    result = await tool.run(path=str(pdf))
    assert result.ok
    assert result.data["source"] == "text"
    assert "hello from the text layer" in result.output


@pytest.mark.asyncio
async def test_ink_pdf_writes_page_images_not_empty_fail(tmp_path: Path) -> None:
    pdf = _write_jpeg_pdf(tmp_path)
    pages = tmp_path / "pages"
    tool = DocExtractTool(
        [str(tmp_path)],
        page_dir=pages,
        ocr_inspect=lambda _path: inspect_ocr_text(""),
    )
    result = await tool.run(path=str(pdf))
    assert result.ok
    assert result.data["source"] == "ink"
    assert result.data.get("fail_class") is None
    images = result.data["page_images"]
    assert len(images) == 1
    assert Path(images[0]).is_file()
    assert "call vision" in result.output.lower()
    assert "do not ask them to paste" in result.output.lower()


@pytest.mark.asyncio
async def test_raster_ink_extract_writes_page_images(tmp_path: Path) -> None:
    from arelis.tools.pdf_pages import build_vector_page_pdf_bytes

    pdf = tmp_path / "vector_ink.pdf"
    pdf.write_bytes(build_vector_page_pdf_bytes(80, 40))
    pages = tmp_path / "pages"
    tool = DocExtractTool(
        [str(tmp_path)],
        page_dir=pages,
        ocr_inspect=lambda _path: inspect_ocr_text(""),
    )
    result = await tool.run(path=str(pdf))
    assert result.ok
    assert result.data["source"] == "ink"
    images = result.data["page_images"]
    assert len(images) == 1
    assert Path(images[0]).is_file()
    assert Path(images[0]).suffix == ".png"


@pytest.mark.asyncio
async def test_missing_rasterizer_is_loud(tmp_path: Path, monkeypatch) -> None:
    from arelis.tools import pdf_pages as pages_mod
    from arelis.tools.pdf_pages import RasterizerMissingError, build_vector_page_pdf_bytes

    def _boom(*_args, **_kwargs):
        raise RasterizerMissingError("pypdfium2 is not installed")

    monkeypatch.setattr(pages_mod, "raster_pages", _boom)
    pdf = tmp_path / "vector_ink.pdf"
    pdf.write_bytes(build_vector_page_pdf_bytes(80, 40))
    tool = DocExtractTool(
        [str(tmp_path)],
        page_dir=tmp_path / "pages",
        ocr_inspect=lambda _path: inspect_ocr_text(""),
    )
    result = await tool.run(path=str(pdf))
    assert not result.ok
    assert result.data["fail_class"] == "fail:rasterizer"
    assert "pypdfium2" in result.output.lower()
    assert "do not ask them to paste" in result.output.lower()


@pytest.mark.asyncio
async def test_empty_after_ink_asks_for_vision_not_path_dump() -> None:
    from arelis.core.agent_loop import AgentLoop
    from arelis.core.bus import EventBus
    from arelis.core.events import EventType
    from arelis.core.memory import SessionMemory
    from arelis.tools.base import ToolRegistry, ToolResult
    from tests.hardening_helpers import _collect, _config, _deny, _ScriptedRouter

    listing = (
        "path: physhw/hw.pdf\npages: 1-1 of 1\nsource: ink\n"
        "No text layer — scanned or handwritten PDF.\n"
        "Page images (call vision on each path):\n"
        "  1: C:\\tmp\\page_01.jpg\n"
    )

    class ExtractStub:
        name = "doc_extract"
        description = "pdf"
        risk = "read"
        parameters_schema = {
            "type": "object",
            "properties": {"path": {"type": "string"}},
        }

        async def run(self, **kwargs: Any) -> ToolResult:
            del kwargs
            return ToolResult(
                ok=True,
                output=listing,
                data={
                    "source": "ink",
                    "page_images": [r"C:\tmp\page_01.jpg"],
                },
            )

    class VisionStub:
        name = "vision"
        description = "look"
        risk = "read"
        parameters_schema = {
            "type": "object",
            "properties": {"path": {"type": "string"}},
        }

        async def run(self, **kwargs: Any) -> ToolResult:
            del kwargs
            return ToolResult(ok=True, output="Page 1: N = Mg(sin beta - cos beta)")

    router = _ScriptedRouter(
        [
            [
                (
                    "tool_calls",
                    [
                        {
                            "type": "function",
                            "function": {
                                "name": "doc_extract",
                                "arguments": {"path": "hw.pdf"},
                            },
                        }
                    ],
                )
            ],
            [("token", "2.20 is correct: N = Mg(sin beta - cos beta).")],
        ]
    )
    tools = ToolRegistry()
    tools.register(ExtractStub())
    tools.register(VisionStub())
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["max_rounds"] = 8
    bus = EventBus()
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "persona",
        cfg,
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )
    events = await _collect(bus, loop.run("how accurate is this homework pdf?", "fast"))
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    assert "looking at pages 1-" in thinking
    assert "empty after tool; answering from result" not in thinking
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    assert "page_01.jpg" not in done.payload["text"]
    assert "2.20 is correct" in done.payload["text"]


