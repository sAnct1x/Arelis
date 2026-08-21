"""Startup prefills the front of the prompt so the first reply is not a hang.

The whole policy and the whole tool surface now ship on every turn, which makes
the front of the prompt large and — crucially — identical every time. Identical
is what Ollama's prefix cache wants, but somebody still has to process it once,
and on a 12 GB AMD card that measured 44s. Doing it at startup instead took the
first reply from 44.1s to 0.9s (scripts/verify_prefix_warmup.py).

These tests hold the parts that would silently stop working: that the warmed
prefix is the same prefix a real turn sends, and that nothing here can keep the
app from starting.
"""

from __future__ import annotations

from typing import Any

import pytest

from arelis.core.bus import EventBus
from arelis.llm.preflight import (
    PrefixWarmup,
    prefix_warmup_for,
    run_model_warmup,
    seed_prefix_cache,
)
from arelis.llm.router import ModelRouter


class _Provider:
    def __init__(self, *, explode: bool = False) -> None:
        self.pins: list[tuple[str, str | int]] = []
        self.streams: list[dict[str, Any]] = []
        self._explode = explode

    async def stream_chat(self, model, messages, **kwargs):
        if self._explode:
            raise RuntimeError("ollama is down")
        self.streams.append({"model": model, "messages": messages, **kwargs})
        yield ("token", "ok")

    async def unload(self, model: str) -> None:
        await self.pin(model, keep_alive=0)

    async def pin(self, model: str, *, keep_alive: str | int = "30m") -> None:
        self.pins.append((model, keep_alive))

    async def close(self) -> None:
        return None


def _router(provider: _Provider) -> ModelRouter:
    return ModelRouter(
        provider,  # type: ignore[arg-type]
        {"fast": "qwen-fast"},
        default_keep_alive="30m",
        options={"num_ctx": 65536},
    )


def _prefix() -> PrefixWarmup:
    return PrefixWarmup(
        messages=[
            {"role": "system", "content": "You are Arelis."},
            {"role": "system", "content": "Tool policy."},
        ],
        tools=[{"type": "function", "function": {"name": "weather"}}],
        num_ctx=65536,
    )


@pytest.mark.asyncio
async def test_seeding_sends_the_prefix_and_the_tools() -> None:
    provider = _Provider()
    router = _router(provider)
    await router.warm_default()
    await seed_prefix_cache(EventBus(), router, _prefix())

    assert len(provider.streams) == 1
    sent = provider.streams[0]
    assert sent["messages"] == _prefix().messages
    assert sent["tools"] == _prefix().tools


@pytest.mark.asyncio
async def test_seeding_asks_for_almost_no_output() -> None:
    """The reply is thrown away; only the prefill matters."""
    provider = _Provider()
    router = _router(provider)
    await router.warm_default()
    await seed_prefix_cache(EventBus(), router, _prefix())

    options = provider.streams[0]["options"]
    assert options["num_predict"] == 1
    assert options["num_ctx"] == 65536


@pytest.mark.asyncio
async def test_seeding_keeps_the_model_resident() -> None:
    """A seed that let the model unload would throw the cache away with it."""
    provider = _Provider()
    router = _router(provider)
    await router.warm_default()
    await seed_prefix_cache(EventBus(), router, _prefix())

    assert provider.streams[0]["keep_alive"] == "30m"


@pytest.mark.asyncio
async def test_a_failed_seed_is_not_fatal() -> None:
    """Worst case is the first turn pays the prefill, exactly as it used to."""
    provider = _Provider(explode=True)
    router = _router(provider)
    await router.warm_default()
    await seed_prefix_cache(EventBus(), router, _prefix())  # must not raise


@pytest.mark.asyncio
async def test_warmup_without_a_prefix_still_only_pins() -> None:
    """Callers that pass no prefix keep the old behaviour."""
    provider = _Provider()
    router = _router(provider)
    await run_model_warmup(EventBus(), router)
    assert provider.pins == [("qwen-fast", "30m")]
    assert provider.streams == []


@pytest.mark.asyncio
async def test_warmup_with_a_prefix_pins_then_prefills() -> None:
    provider = _Provider()
    router = _router(provider)
    await run_model_warmup(EventBus(), router, prefix=_prefix())
    assert provider.pins  # pinned first
    assert len(provider.streams) == 1


def test_the_warmed_prefix_is_the_prefix_a_turn_sends() -> None:
    """A warmup that seeded a different prefix would warm nothing.

    This is the failure that would be invisible in production: the app would
    still start, still report "context ready", and the first turn would still
    take 44 seconds.
    """
    from arelis.config import load_config, load_persona
    from arelis.core.agent_loop import static_system_prefix
    from arelis.tools import build_tool_registry

    config = load_config()
    tools = build_tool_registry(config)
    warm = prefix_warmup_for(config, tools)
    assert warm is not None

    assert warm.messages == static_system_prefix(load_persona(config))
    # The full surface, because that is what a turn now offers.
    assert len(warm.tools) == len(tools.ollama_tools())


def test_an_unbuildable_prefix_returns_none_rather_than_raising() -> None:
    class _Broken:
        def ollama_tools(self, names: Any = None) -> list[dict[str, Any]]:
            raise RuntimeError("registry exploded")

    assert prefix_warmup_for({}, _Broken()) is None
