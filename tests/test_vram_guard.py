"""12GB card: do not start 14B on a full GPU, and never JSON-fallback that."""

from __future__ import annotations

import pytest

from arelis.llm.router import ModelRouter
from arelis.llm.vram import host_vram_blocks_heavy


class _FakeProvider:
    def __init__(self) -> None:
        self.pins: list[tuple[str, str | int]] = []
        self.unloads: list[str] = []
        self.streams: list[dict] = []

    async def stream_chat(self, model, messages, **kwargs):
        self.streams.append({"model": model, **kwargs})
        yield ("token", "ok")

    async def unload(self, model: str) -> None:
        self.unloads.append(model)

    async def pin(
        self,
        model: str,
        *,
        keep_alive: str | int = "30m",
        options: dict | None = None,
    ) -> None:
        self.pins.append((model, keep_alive))

    async def close(self) -> None:
        return None


def test_host_vram_blocks_heavy_threshold() -> None:
    assert host_vram_blocks_heavy(None) is None
    assert host_vram_blocks_heavy(2 * 1024**3) is None
    reason = host_vram_blocks_heavy(11 * 1024**3)
    assert reason is not None
    assert "11.0 GB" in reason
    assert "Close ComfyUI" not in reason


@pytest.mark.asyncio
async def test_ensure_role_research_refuses_when_host_vram_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "arelis.llm.vram.host_dedicated_bytes",
        lambda: 11 * 1024**3,
    )

    class Guarded(_FakeProvider):
        guard_host_vram = True

        async def running_models(self) -> list[str]:
            return []

        async def stream_chat(self, model, messages, **kwargs):
            raise AssertionError("14B must not start when the card is already full")
            yield  # pragma: no cover

    provider = Guarded()
    router = ModelRouter(
        provider,  # type: ignore[arg-type]
        {"fast": "qwen-fast", "research": "qwen-big"},
        rewarm_after_switch=False,
    )
    with pytest.raises(RuntimeError, match=r"11\.0 GB"):
        await router.ensure_role("research", force=True)
    with pytest.raises(RuntimeError, match=r"11\.0 GB"):
        _ = [
            item
            async for item in router.stream(
                "research", [{"role": "user", "content": "x"}]
            )
        ]
    assert provider.streams == []


@pytest.mark.asyncio
async def test_ensure_role_research_allows_already_resident_14b(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Host VRAM at 10GB is the 14B we just loaded — not a leftover app."""
    monkeypatch.setattr(
        "arelis.llm.vram.host_dedicated_bytes",
        lambda: 10 * 1024**3,
    )

    class Resident(_FakeProvider):
        guard_host_vram = True

        async def running_models(self) -> list[str]:
            return ["qwen-big"]

    provider = Resident()
    router = ModelRouter(
        provider,  # type: ignore[arg-type]
        {"fast": "qwen-fast", "research": "qwen-big"},
        rewarm_after_switch=False,
    )
    assert await router.ensure_role("research", force=True) == "qwen-big"
