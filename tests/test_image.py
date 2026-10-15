"""Image generation helpers — no live ComfyUI."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from arelis.tools.comfy_client import (
    wait_for_image,
)
from arelis.tools.image import (
    ImageTool,
)
from arelis.tools.image_meta import read_sidecar, write_sidecar


class _EmptyHistory:
    async def get(self, url: str, **kwargs: Any) -> Any:
        del url, kwargs

        class _Resp:
            def json(self) -> dict[str, Any]:
                return {}

        return _Resp()


def test_wait_for_image_timeout_is_fail() -> None:
    name, err = asyncio.run(
        wait_for_image(
            _EmptyHistory(),  # type: ignore[arg-type]
            "http://127.0.0.1:8188",
            "job-9",
            attempts=2,
            interval_s=0,
        )
    )
    assert name is None
    assert err
    assert "job-9" in err
    assert "Queued" not in err


def test_image_tool_timeout_is_fail(tmp_path: Path, monkeypatch: Any) -> None:
    async def _boot(*_a: Any, **_k: Any) -> None:
        return None

    async def _list(*_a: Any, **_k: Any) -> list[str]:
        return ["demo.safetensors"]

    async def _queue(*_a: Any, **_k: Any) -> tuple[str, str]:
        return "pid-1", ""

    async def _wait(*_a: Any, **_k: Any) -> tuple[None, str]:
        return None, "ComfyUI did not produce an image for job pid-1 within 120s."

    monkeypatch.setattr("arelis.tools.image.ensure_comfy_running", _boot)
    monkeypatch.setattr("arelis.tools.image.list_checkpoints", _list)
    monkeypatch.setattr("arelis.tools.image.queue_workflow", _queue)
    monkeypatch.setattr("arelis.tools.image.wait_for_image", _wait)

    tool = ImageTool(comfy_url="http://127.0.0.1:9", output_dir=str(tmp_path))
    result = asyncio.run(tool.run(prompt="a fox"))
    assert result.ok is False
    assert "[fail:image]" in result.output
    assert "Queued" not in result.output


def test_sidecar_roundtrip(tmp_path: Path) -> None:
    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG")
    write_sidecar(
        png,
        prompt="a fox",
        negative="blurry",
        seed=11,
        checkpoint="demo.safetensors",
        width=768,
        height=512,
        style="oil",
        mode="txt2img",
        source="",
        denoise=1.0,
        n=2,
    )
    data = read_sidecar(png)
    assert data["prompt"] == "a fox"
    assert data["negative"] == "blurry"
    assert data["seed"] == 11
    assert data["checkpoint"] == "demo.safetensors"
    assert data["width"] == 768
    assert data["height"] == 512
    assert data["style"] == "oil"
    assert data["mode"] == "txt2img"
    assert data["n"] == 2


