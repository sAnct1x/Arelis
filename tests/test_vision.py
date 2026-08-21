"""Vision tool: path containment, confirm gating, fake runner (no live VL)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from arelis.core.claims import detect_exactness_need, detect_vision_ask
from arelis.core.evidence import EvidenceLedger
from arelis.core.preflight import detect_intents
from arelis.core.receipts import action_receipt
from arelis.core.skills import select_skill_ids
from arelis.tools import build_tool_registry
from arelis.tools.base import ToolRegistry, capability_class
from arelis.tools.vision import VisionTool
from arelis.workspace import WorkspaceRoots


class _FakeRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.unload_chat = True
        self.caption = "A red circle on a white background."

    async def run_vision(
        self,
        prompt: str,
        images_b64: list[str],
        *,
        model: str | None = None,
        num_ctx: int = 4096,
    ) -> str:
        self.calls.append(
            {
                "prompt": prompt,
                "n_images": len(images_b64),
                "model": model,
                "num_ctx": num_ctx,
            }
        )
        return self.caption


def test_vision_path_outside_roots_rejected(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    ws = WorkspaceRoots.from_paths([str(root)])
    tool = VisionTool(ws, _FakeRunner())

    async def _run() -> None:
        bad = await tool.run(path=str(outside))
        assert not bad.ok
        assert "outside" in bad.output.lower() or "workspace" in bad.output.lower()

    asyncio.run(_run())


def test_vision_fake_caption(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    img = root / "demo.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    ws = WorkspaceRoots.from_paths([str(root)])
    runner = _FakeRunner()
    tool = VisionTool(ws, runner, model="qwen2.5vl:3b")

    async def _run() -> None:
        ok = await tool.run(path="demo.png", question="What color?")
        assert ok.ok
        assert "red circle" in ok.output.lower()
        assert ok.data.get("answer_len")
        assert ok.data.get("answer_hash")
        assert runner.calls and runner.calls[0]["prompt"] == "What color?"
        assert runner.calls[0]["n_images"] == 1

    asyncio.run(_run())


def test_vision_missing_model_loud(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    img = root / "demo.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    ws = WorkspaceRoots.from_paths([str(root)])

    async def _never() -> bool:
        return False

    tool = VisionTool(ws, _FakeRunner(), model="qwen2.5vl:3b", model_available=_never)

    async def _run() -> None:
        bad = await tool.run(path="demo.png")
        assert not bad.ok
        assert bad.data.get("code") == "MODEL_MISSING"
        assert "ollama pull qwen2.5vl:3b" in bad.output

    asyncio.run(_run())


def test_chat_sees_sends_a_longer_edge_and_does_not_need_the_3b(tmp_path: Path) -> None:
    """Qwen 3.5 looks at 2048. The 3B pull is only for the detour."""
    from PIL import Image

    from arelis.tools.image_io import CHAT_MAX_EDGE

    root = tmp_path / "proj"
    root.mkdir()
    img = root / "wide.png"
    Image.new("RGB", (2560, 1440), (10, 20, 30)).save(img)

    class _Sees(_FakeRunner):
        async def chat_sees_images(self) -> bool:
            return True

    async def _never() -> bool:
        return False

    tool = VisionTool(
        WorkspaceRoots.from_paths([str(root)]),
        _Sees(),
        model="qwen2.5vl:3b",
        model_available=_never,
    )

    async def _run() -> None:
        result = await tool.run(path="wide.png")
        assert result.ok
        assert result.data.get("sent_px") == [2048, 1152]
        assert max(result.data["sent_px"]) == CHAT_MAX_EDGE

    asyncio.run(_run())


def test_a_detour_look_still_caps_at_1024(tmp_path: Path) -> None:
    from PIL import Image

    from arelis.tools.image_io import DEFAULT_MAX_EDGE

    root = tmp_path / "proj"
    root.mkdir()
    img = root / "wide.png"
    Image.new("RGB", (2560, 1440), (10, 20, 30)).save(img)
    tool = VisionTool(WorkspaceRoots.from_paths([str(root)]), _FakeRunner())

    async def _run() -> None:
        result = await tool.run(path="wide.png")
        assert result.ok
        assert result.data.get("sent_px") == [1024, 576]
        assert max(result.data["sent_px"]) == DEFAULT_MAX_EDGE

    asyncio.run(_run())


def test_vision_needs_confirm_separate_from_image() -> None:
    reg = ToolRegistry()
    root = Path(".")
    ws = WorkspaceRoots.from_paths([str(root.resolve())])
    reg.register(VisionTool(ws, _FakeRunner()))

    class Img:
        name = "image"
        description = "img"
        risk = "side_effect"
        parameters_schema: dict[str, Any] = {"type": "object", "properties": {}}

        async def run(self, **kwargs: Any) -> Any:
            from arelis.tools.base import ToolResult

            return ToolResult(ok=True, output="ok")

    reg.register(Img())
    assert reg.needs_confirm("vision", {"path": "x.png"})
    assert not reg.needs_confirm(
        "vision", {"path": "x.png"}, confirm_vision=False
    )
    # Turning off image confirm must not disable vision.
    assert reg.needs_confirm(
        "vision", {"path": "x.png"}, confirm_image=False
    )
    assert capability_class("vision", {"path": "x.png"}) == "SIDE_EFFECT_LOCAL"


def test_vision_not_in_unattended_registry(tmp_path: Path) -> None:
    ws = WorkspaceRoots.from_paths([str(tmp_path)])
    unattended = build_tool_registry(
        {"tools": {"vision": {"enabled": True}}, "agent": {}, "models": {}},
        ws,
        allow_send=False,
    )
    assert "vision" not in unattended.names()


def test_vision_preflight_and_skill() -> None:
    hints = detect_intents("What's in outputs/images/demo.png?")
    assert any(h.kind == "vision" for h in hints)
    vision = next(h for h in hints if h.kind == "vision")
    assert vision.expected_tools == ("vision",)
    ids = select_skill_ids(
        "Describe this screenshot please",
        available_tools={"vision", "image"},
    )
    assert "vision" in ids
    assert "image" not in ids


def test_vision_exactness_warrant() -> None:
    assert detect_vision_ask("What's in this image?")
    assert detect_vision_ask("Look at this screenshot")
    assert detect_vision_ask("describe the image you just generated")
    assert not detect_vision_ask("What is a screenshot?")
    need = detect_exactness_need("Describe this diagram")
    assert need.needs_vision
    assert "vision" in need.kinds
    ledger = EvidenceLedger()
    ledger.record_tool(
        "vision",
        ok=True,
        output="A flowchart with three boxes.",
        data={"path": "outputs/images/demo.png"},
        args={"path": "outputs/images/demo.png"},
    )
    assert ledger.satisfies(("vision",))
    empty = EvidenceLedger()
    assert empty.missing_kinds(("vision",)) == ["vision"]


def test_vision_receipt() -> None:
    r = action_receipt(
        "vision",
        ok=True,
        args={"path": "outputs/images/demo.png"},
        data={
            "path": "outputs/images/demo.png",
            "answer_len": 42,
            "answer_hash": "abcd1234ef00",
        },
    )
    assert r is not None
    assert r["action"] == "vision"
    assert r["path"] == "outputs/images/demo.png"
    assert r["answer_len"] == 42


def test_run_vision_unload_rewarm_mocked() -> None:
    """A text-only chat tag still takes the VL detour: unload, shot, rewarm."""
    from unittest.mock import AsyncMock, MagicMock

    from arelis.llm.router import ModelRouter

    provider = MagicMock()
    provider.unload = AsyncMock()
    provider.chat_with_images = AsyncMock(return_value="caption")
    provider.pin = AsyncMock()
    # qwen2.5:7b reports completion+tools and no vision.
    provider.sees_images = AsyncMock(return_value=False)

    router = ModelRouter(
        provider,
        {"fast": "qwen2.5:7b", "vision": "qwen2.5vl:3b"},
        rewarm_after_switch=True,
        rewarm_delay_s=0,
    )
    router.active_model = "qwen2.5:7b"
    router.active_role = "fast"
    scheduled: list[str] = []
    router._schedule_rewarm_default = lambda *, after="detour": scheduled.append(after)  # type: ignore[method-assign]

    async def _run() -> None:
        text = await router.run_vision("Describe", ["YmFzZTY0"], num_ctx=4096)
        assert text == "caption"
        # Chat unload + VL unload
        assert provider.unload.await_count >= 2
        assert provider.chat_with_images.await_count == 1
        assert scheduled == ["vision"]
        assert router.active_model is None

    asyncio.run(_run())


def _seeing_router(**kwargs: Any):
    """A router whose hot chat model reports the vision capability."""
    from unittest.mock import AsyncMock, MagicMock

    from arelis.llm.router import ModelRouter

    provider = MagicMock()
    provider.unload = AsyncMock()
    provider.pin = AsyncMock()
    provider.chat_with_images = AsyncMock(return_value="a red circle")
    provider.sees_images = AsyncMock(return_value=True)
    router = ModelRouter(
        provider,
        {"fast": "qwen3.5:9b", "research": "qwen3.5:9b", "vision": "qwen2.5vl:3b"},
        options={"num_ctx": 65536},
        **kwargs,
    )
    router.active_model = "qwen3.5:9b"
    router.active_role = "fast"
    return router, provider


def test_a_multimodal_chat_model_never_unloads_to_see() -> None:
    """The swap cost tens of seconds to reach a smaller model that answers worse."""
    router, provider = _seeing_router()

    async def _run() -> None:
        text = await router.run_vision("Describe", ["YmFzZTY0"], num_ctx=4096)
        assert text == "a red circle"
        assert provider.unload.await_count == 0
        assert provider.chat_with_images.await_count == 1
        # Still hot, still the chat model. Nothing to re-warm.
        assert router.active_model == "qwen3.5:9b"

    asyncio.run(_run())


def test_a_multimodal_chat_model_sees_at_the_chat_window() -> None:
    """vision_num_ctx (4096) exists to keep a 3B VL off a small card only."""
    router, provider = _seeing_router()

    async def _run() -> None:
        await router.run_vision("Describe", ["YmFzZTY0"], num_ctx=4096)
        options = provider.chat_with_images.await_args.kwargs["options"]
        assert options["num_ctx"] == 65536

    asyncio.run(_run())


def test_the_image_goes_to_the_chat_tag_not_the_vl_tag() -> None:
    router, provider = _seeing_router()

    async def _run() -> None:
        await router.run_vision("Describe", ["YmFzZTY0"], num_ctx=4096)
        assert provider.chat_with_images.await_args.args[0] == "qwen3.5:9b"

    asyncio.run(_run())


def test_an_unknown_capability_takes_the_safe_detour() -> None:
    """Ollama not answering must not be read as "it can see"."""
    from unittest.mock import AsyncMock, MagicMock

    from arelis.llm.router import ModelRouter

    provider = MagicMock()
    provider.unload = AsyncMock()
    provider.pin = AsyncMock()
    provider.chat_with_images = AsyncMock(return_value="caption")
    provider.sees_images = AsyncMock(side_effect=RuntimeError("ollama down"))
    router = ModelRouter(provider, {"fast": "mystery:9b", "vision": "qwen2.5vl:3b"})
    router.active_model = "mystery:9b"
    router.active_role = "fast"
    router._schedule_rewarm_default = lambda *, after="": None  # type: ignore[method-assign]

    async def _run() -> None:
        await router.run_vision("Describe", ["YmFzZTY0"], num_ctx=4096)
        # Detour taken: the VL tag got the image, not the mystery chat tag.
        assert provider.chat_with_images.await_args.args[0] == "qwen2.5vl:3b"

    asyncio.run(_run())
