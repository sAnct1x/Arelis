"""Default-model warm / re-warm behaviour (feel-first latency)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.llm.router import ModelRouter
from arelis.llm.startup import run_model_warmup


class FakeProvider:
    def __init__(self) -> None:
        self.pins: list[tuple[str, str | int]] = []
        self.unloads: list[str] = []
        self.streams: list[dict[str, Any]] = []

    async def stream_chat(self, model, messages, **kwargs):
        self.streams.append({"model": model, **kwargs})
        yield ("token", "ok")

    async def unload(self, model: str) -> None:
        self.unloads.append(model)
        await self.pin(model, keep_alive=0)

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


@pytest.mark.asyncio
async def test_default_role_uses_default_keep_alive() -> None:
    provider = FakeProvider()
    router = ModelRouter(
        provider,  # type: ignore[arg-type]
        {"fast": "qwen-fast", "research": "qwen-big"},
        keep_alive="0",
        default_keep_alive="45m",
        rewarm_after_switch=False,
        rewarm_delay_s=0,
    )
    assert router.keep_alive_for("fast") == "45m"
    assert router.keep_alive_for("research") == "0"
    events = [item async for item in router.stream("fast", [{"role": "user", "content": "hi"}])]
    assert events == [("token", "ok")]
    assert provider.streams[-1]["keep_alive"] == "45m"


@pytest.mark.asyncio
async def test_warm_default_pins_without_generating() -> None:
    provider = FakeProvider()
    router = ModelRouter(
        provider,  # type: ignore[arg-type]
        {"fast": "qwen-fast"},
        default_keep_alive="30m",
    )
    assert await router.warm_default() == "qwen-fast"
    assert provider.pins == [("qwen-fast", "30m")]
    assert provider.streams == []
    assert router.active_model == "qwen-fast"


@pytest.mark.asyncio
async def test_research_stream_schedules_rewarm() -> None:
    provider = FakeProvider()
    router = ModelRouter(
        provider,  # type: ignore[arg-type]
        {"fast": "qwen-fast", "research": "qwen-big"},
        keep_alive="5m",
        default_keep_alive="30m",
        rewarm_after_switch=True,
        rewarm_delay_s=0,
    )
    _ = [item async for item in router.stream("research", [{"role": "user", "content": "deep"}])]
    assert provider.streams[-1]["model"] == "qwen-big"
    assert provider.streams[-1]["keep_alive"] == "5m"
    assert router._rewarm_task is not None
    await asyncio.wait_for(router._rewarm_task, timeout=1.0)
    assert ("qwen-fast", "30m") in provider.pins
    assert router.active_model == "qwen-fast"


@pytest.mark.asyncio
async def test_sticky_hold_absorbs_fast_downgrade() -> None:
    """H6: after research, auto-fast stays on 14b until hold expires."""
    provider = FakeProvider()
    router = ModelRouter(
        provider,  # type: ignore[arg-type]
        {"fast": "qwen-fast", "research": "qwen-big"},
        keep_alive="5m",
        default_keep_alive="30m",
        rewarm_after_switch=True,
        rewarm_delay_s=60,
        sticky_hold_s=60,
    )
    _ = [item async for item in router.stream("research", [{"role": "user", "content": "deep"}])]
    assert router.active_model == "qwen-big"
    role, reason = router.apply_sticky("fast", "default")
    assert role == "research"
    assert reason == "sticky_hold"
    unloads_before = list(provider.unloads)
    _ = [item async for item in router.stream("fast", [{"role": "user", "content": "hi"}])]
    assert provider.streams[-1]["model"] == "qwen-big"
    assert provider.unloads == unloads_before
    router.clear_sticky()
    role, reason = router.apply_sticky("fast", "default")
    assert role == "fast"
    assert reason == "default"


@pytest.mark.asyncio
async def test_sticky_absorbs_file_loop_into_research() -> None:
    provider = FakeProvider()
    router = ModelRouter(
        provider,  # type: ignore[arg-type]
        {"fast": "qwen-fast", "research": "qwen-big"},
        rewarm_after_switch=False,
        sticky_hold_s=60,
    )
    router.mark_sticky("research")
    role, reason = router.apply_sticky("fast", "file_loop")
    assert role == "research"
    assert reason == "sticky_hold"


@pytest.mark.asyncio
async def test_research_followup_cancels_pending_rewarm() -> None:
    """Back-to-back research must not get interrupted by a fast pin."""
    provider = FakeProvider()
    router = ModelRouter(
        provider,  # type: ignore[arg-type]
        {"fast": "qwen-fast", "research": "qwen-big"},
        keep_alive="5m",
        default_keep_alive="30m",
        rewarm_after_switch=True,
        rewarm_delay_s=60,
    )
    _ = [item async for item in router.stream("research", [{"role": "user", "content": "one"}])]
    first = router._rewarm_task
    assert first is not None and not first.done()
    _ = [item async for item in router.stream("research", [{"role": "user", "content": "two"}])]
    with pytest.raises(asyncio.CancelledError):
        await first
    assert first.cancelled()
    assert router.active_model == "qwen-big"
    # Pending rewarm for the second turn should still be waiting (delay=60).
    assert router._rewarm_task is not None and not router._rewarm_task.done()
    router._cancel_rewarm()
    with pytest.raises(asyncio.CancelledError):
        await router._rewarm_task


@pytest.mark.asyncio
async def test_warmup_status_events() -> None:
    provider = FakeProvider()
    router = ModelRouter(
        provider,  # type: ignore[arg-type]
        {"fast": "qwen-fast"},
        warm_on_start=True,
    )
    bus = EventBus()
    seen: list[str] = []

    async def collect(event) -> None:
        if event.type == EventType.STATUS:
            seen.append(str((event.payload or {}).get("message") or ""))

    bus.subscribe(None, collect)
    bus_task = asyncio.create_task(bus.run())
    try:
        await run_model_warmup(bus, router)
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
        try:
            await bus_task
        except asyncio.CancelledError:
            pass

    assert any("Warming conversation model" in m for m in seen)
    assert any("ready" in m for m in seen)
    assert provider.pins == [("qwen-fast", "30m")]


@pytest.mark.asyncio
async def test_prepare_heavy_role_evicts_resident_7b() -> None:
    """/role research must drop 7B before the first 14B stream."""

    class Tracking(FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.running = ["qwen-fast"]

        async def running_models(self) -> list[str]:
            return list(self.running)

        async def wait_until_unloaded(self, models, *, timeout_s: float = 15.0):
            del timeout_s
            gone = {str(m) for m in models}
            self.running = [m for m in self.running if m not in gone]
            return []

        async def unload(self, model: str) -> None:
            await super().unload(model)
            self.running = [m for m in self.running if m != model]

    provider = Tracking()
    router = ModelRouter(
        provider,  # type: ignore[arg-type]
        {"fast": "qwen-fast", "research": "qwen-big"},
        rewarm_after_switch=False,
    )
    router.active_model = "qwen-fast"
    router.active_role = "fast"
    await router.prepare_heavy_role("research")
    assert "qwen-fast" in provider.unloads
    assert provider.running == []
    assert router.active_model is None
    assert router.active_role == "research"


@pytest.mark.asyncio
async def test_ensure_role_research_evicts_7b_still_in_ps() -> None:
    """keep_alive=30m can leave 7B in /api/ps after the router already flipped."""

    class Tracking(FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.running = ["qwen-fast", "qwen-big"]

        async def running_models(self) -> list[str]:
            return list(self.running)

        async def wait_until_unloaded(self, models, *, timeout_s: float = 15.0):
            del timeout_s
            gone = {str(m) for m in models}
            self.running = [m for m in self.running if m not in gone]
            return []

        async def unload(self, model: str) -> None:
            await super().unload(model)
            self.running = [m for m in self.running if m != model]

    provider = Tracking()
    router = ModelRouter(
        provider,  # type: ignore[arg-type]
        {"fast": "qwen-fast", "research": "qwen-big"},
        rewarm_after_switch=False,
    )
    router.active_model = "qwen-big"
    await router.ensure_role("research", force=True)
    assert "qwen-fast" in provider.unloads
    assert "qwen-big" not in provider.unloads
    assert provider.running == ["qwen-big"]


@pytest.mark.asyncio
async def test_ensure_role_research_raises_when_7b_will_not_leave() -> None:
    class Stuck(FakeProvider):
        async def running_models(self) -> list[str]:
            return ["qwen-fast"]

        async def wait_until_unloaded(self, models, *, timeout_s: float = 15.0):
            del models, timeout_s
            return ["qwen-fast"]

        async def stream_chat(self, model, messages, **kwargs):
            raise AssertionError("14B must not start while 7B is still resident")
            yield  # pragma: no cover

    provider = Stuck()
    router = ModelRouter(
        provider,  # type: ignore[arg-type]
        {"fast": "qwen-fast", "research": "qwen-big"},
        rewarm_after_switch=False,
    )
    with pytest.raises(RuntimeError, match="still resident"):
        await router.ensure_role("research", force=True)
    with pytest.raises(RuntimeError, match="still resident"):
        _ = [item async for item in router.stream("research", [{"role": "user", "content": "x"}])]


@pytest.mark.asyncio
async def test_research_first_token_timeout_does_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("arelis.llm.router._HEAVY_FIRST_TOKEN_S", 0.05)

    class Slow(FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        async def stream_chat(self, model, messages, **kwargs):
            self.attempts += 1
            await asyncio.sleep(1.0)
            yield ("token", "too late")

    provider = Slow()
    router = ModelRouter(
        provider,  # type: ignore[arg-type]
        {"fast": "qwen-fast", "research": "qwen-big"},
        rewarm_after_switch=False,
    )
    with pytest.raises(RuntimeError, match="Could not load"):
        _ = [item async for item in router.stream("research", [{"role": "user", "content": "x"}])]
    assert provider.attempts == 1
    assert "qwen-big" in provider.unloads
    assert router.active_model == "qwen-fast"
    assert ("qwen-fast", "30m") in provider.pins
    assert router.reserve_vram_for_heavy is False


@pytest.mark.asyncio
async def test_warmup_respects_warm_on_start_false() -> None:
    provider = FakeProvider()
    router = ModelRouter(
        provider,  # type: ignore[arg-type]
        {"fast": "qwen-fast"},
        warm_on_start=False,
    )
    bus = EventBus()
    await run_model_warmup(bus, router)
    assert provider.pins == []
