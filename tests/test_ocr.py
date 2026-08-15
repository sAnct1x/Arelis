"""Local OCR tool — injectable runner/capturer; no system tesseract required."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.tools import build_tool_registry
from arelis.tools.ocr import OcrTool
from arelis.workspace import WorkspaceRoots


@pytest.mark.asyncio
async def test_ocr_text_from_workspace_image(tmp_path: Path) -> None:
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")  # suffix check only; runner injected
    workspace = WorkspaceRoots.from_config(
        {"workspace": {"roots": [{"name": "t", "path": str(tmp_path)}]}}
    )
    tool = OcrTool(
        workspace,
        runner=lambda path, lang: f"hello from {path.name} lang={lang}",
    )
    result = await tool.run(action="text", path="shot.png")
    assert result.ok
    assert "hello from shot.png" in result.output
    assert result.data.get("chars", 0) > 0
    assert result.data.get("empty") is False
    assert result.data.get("word_count", 0) > 0


@pytest.mark.asyncio
async def test_ocr_screen_uses_capturer(tmp_path: Path) -> None:
    workspace = WorkspaceRoots.from_config(
        {"workspace": {"roots": [{"name": "t", "path": str(tmp_path)}]}}
    )
    out = tmp_path / "out"
    captured: list[Path] = []

    def capturer(dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"png")
        captured.append(dest)
        return dest

    tool = OcrTool(
        workspace,
        output_dir=out,
        capturer=capturer,
        runner=lambda path, lang: "SCREEN TEXT",
    )
    result = await tool.run(action="screen")
    assert result.ok
    assert "SCREEN TEXT" in result.output
    assert captured and captured[0].name.startswith("ocr_screen_")


@pytest.mark.asyncio
async def test_ocr_missing_tesseract_is_clear(tmp_path: Path) -> None:
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    workspace = WorkspaceRoots.from_config(
        {"workspace": {"roots": [{"name": "t", "path": str(tmp_path)}]}}
    )

    def boom(path: Path, lang: str) -> str:
        raise RuntimeError("tesseract is not on PATH. Install Tesseract OCR")

    tool = OcrTool(workspace, runner=boom)
    result = await tool.run(action="text", path="a.png")
    assert not result.ok
    assert "[fail:" in result.output
    assert "tesseract" in result.output.lower()


def test_ocr_needs_vision_confirm_and_attended_only(tmp_path: Path) -> None:
    workspace = WorkspaceRoots.from_config(
        {"workspace": {"roots": [{"name": "t", "path": str(tmp_path)}]}}
    )
    attended = build_tool_registry(
        {"tools": {"ocr": {"enabled": True}}, "agent": {}},
        workspace,
        allow_send=True,
        memory_store=None,
    )
    assert "ocr" in attended.names()
    assert attended.needs_confirm(
        "ocr", {"action": "text", "path": "x.png"}, confirm_vision=True
    )
    assert not attended.needs_confirm(
        "ocr", {"action": "text"}, confirm_vision=False
    )
    jobs = build_tool_registry(
        {"tools": {"ocr": {"enabled": True}}, "agent": {}},
        workspace,
        allow_send=False,
        memory_store=None,
    )
    assert "ocr" not in jobs.names()


def test_ocr_capability() -> None:
    from arelis.tools.base import capability_class

    assert capability_class("ocr") == "SIDE_EFFECT_LOCAL"
