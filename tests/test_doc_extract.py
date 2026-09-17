from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from arelis.core.look import inspect_ocr_text
from arelis.tools.doc_extract import DocExtractTool, build_simple_pdf_bytes
from arelis.tools.pdf_pages import build_jpeg_page_pdf_bytes, extract_embedded_pages


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
async def test_ink_pdf_looks_inside_extract(tmp_path: Path) -> None:
    pdf = _write_jpeg_pdf(tmp_path)
    pages = tmp_path / "pages"

    async def look(paths: list[Path]) -> str:
        assert paths
        assert Path(paths[0]).is_file()
        return "Page 1: N = Mg(sin beta - cos beta)"

    tool = DocExtractTool(
        [str(tmp_path)],
        page_dir=pages,
        ocr_inspect=lambda _path: inspect_ocr_text(""),
        look_pages=look,
    )
    result = await tool.run(path=str(pdf))
    assert result.ok
    assert result.data["source"] == "look"
    assert "N = Mg(sin beta - cos beta)" in result.output
    assert "call vision" not in result.output.lower()


@pytest.mark.asyncio
async def test_ink_pdf_uses_ocr_when_text_is_clean(tmp_path: Path) -> None:
    pdf = _write_jpeg_pdf(tmp_path)
    pages = tmp_path / "pages"

    def clean(_path: Path):
        return inspect_ocr_text("Printed scan of a receipt", mean_conf=92.0)

    tool = DocExtractTool([str(tmp_path)], page_dir=pages, ocr_inspect=clean)
    result = await tool.run(path=str(pdf))
    assert result.ok
    assert result.data["source"] == "ocr"
    assert "Printed scan of a receipt" in result.output


def test_embedded_jpeg_is_the_page(tmp_path: Path) -> None:
    pdf = _write_jpeg_pdf(tmp_path)
    found = extract_embedded_pages(pdf, 0, 0)
    assert len(found) == 1
    assert found[0].page == 1
    assert found[0].suffix == ".jpg"
    assert found[0].data[:2] == b"\xff\xd8"


def test_ink_followup_does_not_dump_path_list() -> None:
    from arelis.core.failure_copy import chat_followup_from_tool
    from arelis.tools.pdf_pages import ink_page_paths, ink_vision_notice, is_ink_extract

    listing = (
        "path: physhw/hw.pdf\npages: 1-2 of 2\nsource: ink\n"
        "No text layer — scanned or handwritten PDF.\n"
        "Page images (call vision on each path; do not ask them to paste; "
        "do not give up):\n"
        "  1: C:\\tmp\\page_01.jpg\n"
        "  2: C:\\tmp\\page_02.jpg\n"
    )
    assert is_ink_extract(listing)
    assert ink_page_paths(listing) == [
        r"C:\tmp\page_01.jpg",
        r"C:\tmp\page_02.jpg",
    ]
    notice = ink_vision_notice(ink_page_paths(listing))
    assert "vision path=" in notice
    assert "do not dump" in notice.lower()
    follow = chat_followup_from_tool("doc_extract", listing)
    assert "page_01.jpg" not in follow
    assert "handwritten" in follow.lower() or "scanned" in follow.lower()


def test_empty_doc_extract_replans_to_vision_not_paste() -> None:
    from arelis.core.fail_tags import tool_fail_replan_notice

    notice = tool_fail_replan_notice(
        "doc_extract",
        "[fail:empty] No extractable text or page images in scan.pdf",
        ok=False,
    )
    assert notice is not None
    assert "do not ask them to paste" in notice.lower()
    assert "vision" in notice.lower()


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


@pytest.mark.asyncio
async def test_ocr_tool_accepts_pdf(tmp_path: Path) -> None:
    from arelis.tools.ocr import OcrTool
    from arelis.workspace import WorkspaceRoots

    pdf = _write_jpeg_pdf(tmp_path)
    tool = OcrTool(
        WorkspaceRoots.from_paths([str(tmp_path)]),
        output_dir=tmp_path / "ocr_out",
        runner=lambda _path, _lang: "",
    )
    result = await tool.run(action="text", path=str(pdf))
    assert "not an image" not in result.output.lower()
    assert result.data.get("page_images") or "vision" in result.output.lower()
