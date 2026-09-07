"""Host VRAM gate is for a 14B cold load, not a same-tag research overlay."""

from __future__ import annotations

import pytest

from arelis.llm.router import ModelRouter


class _FakeProvider:
    guard_host_vram = True

    async def running_models(self) -> list[str]:
        return []

    async def unload(self, name: str) -> None:
        del name


@pytest.mark.asyncio
async def test_same_tag_research_skips_the_14b_vram_gate() -> None:
    router = ModelRouter(
        _FakeProvider(),  # type: ignore[arg-type]
        {"fast": "qwen2.5:9b", "research": "qwen2.5:9b"},
    )
    called = {"n": 0}

    async def mark() -> None:
        called["n"] += 1

    router._refuse_if_host_vram_full = mark  # type: ignore[method-assign]
    await router._evict_others(keep="qwen2.5:9b")
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_real_14b_research_still_hits_the_vram_gate() -> None:
    router = ModelRouter(
        _FakeProvider(),  # type: ignore[arg-type]
        {"fast": "qwen2.5:9b", "research": "qwen2.5:14b"},
    )
    called = {"n": 0}

    async def mark() -> None:
        called["n"] += 1

    router._refuse_if_host_vram_full = mark  # type: ignore[method-assign]
    await router._evict_others(keep="qwen2.5:14b")
    assert called["n"] == 1
