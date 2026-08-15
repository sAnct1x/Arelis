"""ImageTool against a fake ComfyUI HTTP surface."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from arelis.tools import image as image_mod
from arelis.tools.image import ImageTool


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        *,
        json_data: Any = None,
        content: bytes = b"",
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "err",
                request=httpx.Request("GET", "http://comfy"),
                response=httpx.Response(self.status_code),
            )

    def json(self) -> Any:
        return self._json


class _FakeClient:
    def __init__(self, routes: dict[tuple[str, str], _FakeResponse], **_kwargs: Any) -> None:
        self.routes = routes

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def _match(self, method: str, url: str) -> _FakeResponse:
        for (route_method, prefix), response in self.routes.items():
            if route_method == method and url.startswith(prefix):
                return response
        raise AssertionError(f"unexpected {method} {url}")

    async def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self._match("GET", url)

    async def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self._match("POST", url)


@pytest.mark.asyncio
async def test_image_reports_when_comfy_cannot_auto_start(tmp_path, monkeypatch) -> None:
    async def down(*_a, **_k):
        return "ComfyUI is not reachable and launch_cwd is missing."

    monkeypatch.setattr(image_mod, "ensure_comfy_running", down)
    tool = ImageTool(
        "http://127.0.0.1:8188",
        str(tmp_path),
        auto_start=True,
        launch_cwd="",
    )
    result = await tool.run(prompt="a cat")
    assert not result.ok
    assert "launch_cwd" in result.output
    assert "[fail:image]" in result.output


@pytest.mark.asyncio
async def test_image_saves_a_finished_job_locally(tmp_path, monkeypatch) -> None:
    prompt_id = "abc123"
    routes = {
        ("POST", "http://127.0.0.1:8188/prompt"): _FakeResponse(
            200, json_data={"prompt_id": prompt_id}
        ),
        ("GET", f"http://127.0.0.1:8188/history/{prompt_id}"): _FakeResponse(
            200,
            json_data={
                prompt_id: {
                    "outputs": {"9": {"images": [{"filename": "arelis_00001.png"}]}},
                    "status": {"status_str": "success"},
                }
            },
        ),
        ("GET", "http://127.0.0.1:8188/view"): _FakeResponse(
            200, content=b"\x89PNG\r\n\x1a\nfake"
        ),
    }
    monkeypatch.setattr(image_mod.httpx, "AsyncClient", lambda **kw: _FakeClient(routes, **kw))

    async def ready(*_a, **_k):
        return None

    async def _asap(*_a, **_k):
        return None

    monkeypatch.setattr(image_mod, "ensure_comfy_running", ready)
    monkeypatch.setattr(image_mod.asyncio, "sleep", _asap)

    tool = ImageTool("http://127.0.0.1:8188", str(tmp_path))
    result = await tool.run(prompt="a nebula", seed=42)
    assert result.ok
    assert result.data["seed"] == 42
    assert "Workspace" in result.output
    saved = tmp_path / "arelis_00001.png"
    assert saved.exists()
    assert saved.read_bytes().startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_image_requires_a_prompt(tmp_path) -> None:
    tool = ImageTool("http://127.0.0.1:8188", str(tmp_path))
    result = await tool.run()
    assert not result.ok
    assert "prompt" in result.output.lower()
