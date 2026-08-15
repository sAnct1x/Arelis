"""Camera look-on-ask tool — no hardware required."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from arelis.tools.base import ToolRegistry
from arelis.tools.camera_capture import CameraTool


def test_camera_tool_without_hook_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "arelis.tools.camera_capture.latest_camera_image_file",
        lambda **_kw: None,
    )
    tool = CameraTool({})
    result = asyncio.run(tool.run(action="snapshot"))
    assert not result.ok
    assert "View → camera" in result.output or "Ask Arelis" in result.output


def test_camera_tool_reuses_fresh_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "arelis.tools.camera_capture.latest_camera_image_file",
        lambda **_kw: "outputs/images/camera_fresh.jpg",
    )
    tool = CameraTool({})
    result = asyncio.run(tool.run(action="snapshot"))
    assert result.ok
    assert result.data.get("path") == "outputs/images/camera_fresh.jpg"
    assert "vision" in result.output.lower()


def test_camera_tool_uses_capture_hook() -> None:
    cfg: dict = {
        "_camera_capture": lambda: str(
            Path("C:/tmp") / "outputs" / "images" / "camera_live.jpg"
        )
    }
    tool = CameraTool(cfg)

    def _rel(path):  # keep test offline of PROJECT_ROOT layout
        return "outputs/images/camera_live.jpg"

    tool._rel_path = _rel  # type: ignore[method-assign]
    result = asyncio.run(tool.run(action="snapshot"))
    assert result.ok
    assert "camera_live" in result.data.get("path", "")


def test_camera_snapshot_is_not_confirm() -> None:
    reg = ToolRegistry()
    reg.register(CameraTool({}))
    assert not reg.needs_confirm("camera", {"action": "snapshot"})
    assert not reg.needs_confirm(
        "camera", {"action": "snapshot"}, confirm_vision=True
    )
