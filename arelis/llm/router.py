from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx

from arelis.llm.errors import is_vram_failure
from arelis.llm.ollama import OllamaProvider, same_ollama_model

log = logging.getLogger(__name__)

ModelRole = Literal["fast", "research", "code"]

_HEAVY_ROLES: frozenset[str] = frozenset({"research", "code"})

# Fallback when config omits router.default_keep_alive. Long enough that a
# normal session does not reload 7B between turns; still finite so idle PCs
# can reclaim VRAM overnight.
_DEFAULT_ROLE_KEEP_ALIVE = "30m"

# Retry only transient reachability failures, and only before any token has been
# yielded. Replaying a stream that already spoke would duplicate text into chat.
# An HTTP 400 for a missing model is a RuntimeError and must not retry.
_STREAM_RETRIES = 3
_STREAM_BACKOFF_S = (0.5, 1.0, 2.0)
_RETRYABLE = (httpx.ConnectError, httpx.TimeoutException)
# Ollama's keep_alive=0 returns before VRAM is actually free. Poll /api/ps.
_UNLOAD_WAIT_S = 20.0
# AMD/Windows can report an empty /api/ps while the driver still holds the
# previous allocation. Only used on the real Ollama provider.
_VRAM_SETTLE_S = 3.0
# 14B cold TTFT on the 12GB card is ~18s when VRAM is empty. A multi-minute
# hang with model=0ms means 7B is still resident and 14B is swapping.
_HEAVY_FIRST_TOKEN_S = 90.0
_VRAM_LOCK_NOTICE = (
    "Could not load `{model}` in {seconds:.0f}s. The 12 GB card needs the "
    "previous model fully unloaded first. Say `/role fast` or try again "
    "after GPU memory drops."
)
_VRAM_STUCK_NOTICE = (
    "Could not free VRAM: {still} still resident. The 12 GB card cannot "
    "load another chat model until those are gone. Wait a few seconds and "
    "try again, or restart Ollama."
)


class ModelRouter:
    """Maps roles to Ollama models and keeps only one hot when switching."""

    def __init__(
        self,
        provider: OllamaProvider,
        models: dict[str, str],
        *,
        keep_alive: str | int = "5m",
        default_role: ModelRole = "fast",
        default_keep_alive: str | int = _DEFAULT_ROLE_KEEP_ALIVE,
        warm_on_start: bool = True,
        rewarm_after_switch: bool = True,
        rewarm_delay_s: float = 60.0,
        sticky_hold_s: float | None = None,
        options: dict[str, Any] | None = None,
        role_num_ctx: dict[str, int] | None = None,
    ) -> None:
        self.provider = provider
        self.models = dict(models)
        self.keep_alive = keep_alive
        self.default_role: ModelRole = default_role
        self.default_keep_alive = default_keep_alive
        self.warm_on_start = warm_on_start
        self.rewarm_after_switch = rewarm_after_switch
        self.rewarm_delay_s = max(0.0, float(rewarm_delay_s))
        # H6: absorb auto/fast downgrades onto the last heavy model for this
        # window (defaults to rewarm_delay_s — same clock as delayed 7B pin).
        hold = self.rewarm_delay_s if sticky_hold_s is None else float(sticky_hold_s)
        self.sticky_hold_s = max(0.0, hold)
        # Sent with every request. num_ctx lives here and matters more than it
        # looks: Ollama's default context is small, and a tool result larger
        # than it is silently dropped from the front of the prompt, so the model
        # answers about a file it never actually saw.
        self.options = dict(options or {})
        # Optional per-role overrides (e.g. research_num_ctx: 8192).
        self.role_num_ctx = {
            str(k): int(v) for k, v in (role_num_ctx or {}).items() if v
        }
        self.active_role: ModelRole | None = None
        self.active_model: str | None = None
        # True after `/role research` until 14B starts (or we recover to 7B).
        # The memory indexer must not load nomic into that gap.
        self.reserve_vram_for_heavy: bool = False
        self._rewarm_task: asyncio.Task[None] | None = None
        self._sticky_role: ModelRole | None = None
        self._sticky_until: float = 0.0

    def options_for(self, role: ModelRole) -> dict[str, Any]:
        """Base options with an optional per-role num_ctx override."""
        merged = dict(self.options)
        if role in self.role_num_ctx:
            merged["num_ctx"] = self.role_num_ctx[role]
        return merged

    def model_for(self, role: ModelRole | None = None) -> str:
        """Resolve a role to a model name.

        Falls back to the default role, then to any configured model, rather
        than raising. A missing key here used to propagate a KeyError out of the
        agent loop, which killed the turn without producing an error event and
        left the UI stuck in its busy state.
        """
        wanted = role or self.default_role
        model = self.models.get(wanted)
        if model:
            return model
        fallback = self.models.get(self.default_role)
        if fallback:
            return fallback
        if self.models:
            return next(iter(self.models.values()))
        raise RuntimeError("No models configured. Set `models:` in arelis/config/default.yaml.")

    def keep_alive_for(self, role: ModelRole) -> str | int:
        """Resident TTL for this role's model after a request."""
        if role == self.default_role:
            return self.default_keep_alive
        return self.keep_alive

    def _cancel_rewarm(self) -> None:
        task = self._rewarm_task
        if task is None or task.done():
            return
        task.cancel()

    def clear_sticky(self) -> None:
        """Drop heavy-model affinity (e.g. `/role fast` or rewarm)."""
        self._sticky_role = None
        self._sticky_until = 0.0

    def sticky_active(self) -> bool:
        role = self._sticky_role
        return bool(role) and time.monotonic() < self._sticky_until

    def mark_sticky(self, role: ModelRole) -> None:
        """Remember a heavy role so auto/fast turns can stay on it (H6)."""
        if role not in _HEAVY_ROLES or self.sticky_hold_s <= 0:
            return
        self._sticky_role = role
        self._sticky_until = time.monotonic() + self.sticky_hold_s

    def apply_sticky(
        self, wanted: ModelRole, reason: str
    ) -> tuple[ModelRole, str]:
        """Absorb fast/default downgrades while a heavy model is sticky.

        Explicit research↔code switches still happen (different weights). Only
        the costly unload-to-7B path is deferred until the hold expires.
        """
        if not self.sticky_active():
            if self._sticky_role and time.monotonic() >= self._sticky_until:
                self.clear_sticky()
            return wanted, reason
        sticky = self._sticky_role
        assert sticky is not None
        if wanted == sticky:
            return wanted, reason
        if wanted == self.default_role or wanted == "fast":
            log.info(
                "Sticky hold: keeping `%s` instead of `%s` (reason was %s)",
                sticky,
                wanted,
                reason,
            )
            return sticky, "sticky_hold"
        return wanted, reason

    async def prepare_heavy_role(self, role: ModelRole) -> None:
        """Free VRAM for research/code without loading the heavy model yet.

        `/role research` used to only flip `default_role` while 7B stayed
        pinned for 30m. The next 14B stream then fought 7B for 12GB and hung
        with model=0ms. Evict everything now; the first research ask loads
        14B into an empty card.
        """
        if role not in _HEAVY_ROLES:
            return
        self._cancel_rewarm()
        self.reserve_vram_for_heavy = True
        await self._evict_others(keep=None)
        self.active_role = role
        self.active_model = None

    async def _evict_others(self, *, keep: str | None) -> None:
        """Unload every resident chat model except `keep`, then wait for /api/ps."""
        names: set[str] = set()
        if self.active_model and not (
            keep and same_ollama_model(self.active_model, keep)
        ):
            names.add(self.active_model)
        running_fn = getattr(self.provider, "running_models", None)
        if callable(running_fn):
            try:
                for name in await running_fn() or []:
                    raw = str(name or "").strip()
                    if not raw:
                        continue
                    if keep and same_ollama_model(raw, keep):
                        continue
                    names.add(raw)
            except Exception as exc:
                log.warning("Could not list running Ollama models: %s", exc)
        for name in names:
            try:
                await self.provider.unload(name)
            except Exception as exc:
                log.warning("Unload of %s failed: %s", name, exc)
        wait_fn = getattr(self.provider, "wait_until_unloaded", None)
        if callable(wait_fn) and names:
            still = await wait_fn(list(names), timeout_s=_UNLOAD_WAIT_S)
            if still:
                raise RuntimeError(
                    _VRAM_STUCK_NOTICE.format(still=", ".join(str(x) for x in still))
                )
        guard = bool(getattr(self.provider, "guard_host_vram", False))
        if not guard:
            return
        if names:
            await asyncio.sleep(_VRAM_SETTLE_S)
            if callable(running_fn):
                leftover: list[str] = []
                try:
                    for name in await running_fn() or []:
                        raw = str(name or "").strip()
                        if not raw:
                            continue
                        if keep and same_ollama_model(raw, keep):
                            continue
                        leftover.append(raw)
                except Exception as exc:
                    log.warning("Could not re-list running Ollama models: %s", exc)
                    leftover = []
                if leftover:
                    raise RuntimeError(
                        _VRAM_STUCK_NOTICE.format(still=", ".join(leftover))
                    )
        heavy_models = {
            self.model_for(role)  # type: ignore[arg-type]
            for role in _HEAVY_ROLES
            if role in self.models
        }
        if keep and keep in heavy_models:
            already = False
            if callable(running_fn):
                try:
                    already = any(
                        same_ollama_model(str(name or ""), keep)
                        for name in (await running_fn() or [])
                    )
                except Exception:
                    already = False
            if not already:
                await self._refuse_if_host_vram_full()

    async def _refuse_if_host_vram_full(self) -> None:
        """Fail fast when the card is still full after Ollama reports empty."""
        try:
            from arelis.llm.vram import host_dedicated_bytes, host_vram_blocks_heavy
        except Exception:
            return
        try:
            dedicated = await asyncio.to_thread(host_dedicated_bytes)
        except Exception as exc:
            log.warning("Host VRAM probe failed: %s", exc)
            return
        reason = host_vram_blocks_heavy(dedicated)
        if reason:
            raise RuntimeError(reason)

    async def recover_after_heavy_fail(self) -> None:
        """Unload a stuck 14B load and pin 7B so the desktop is usable again."""
        self._cancel_rewarm()
        self.reserve_vram_for_heavy = False
        self.clear_sticky()
        try:
            await self._evict_others(keep=None)
        except Exception as exc:
            log.warning("VRAM recover evict failed: %s", exc)
        self.active_model = None
        self.active_role = None
        try:
            await self.warm_default()
        except Exception as exc:
            log.warning("VRAM recover rewarm failed: %s", exc)

    async def ensure_role(self, role: ModelRole, *, force: bool = False) -> str:
        """Make `role` the active one, evicting the previous model first.

        Heavy roles wait until `/api/ps` shows the old model gone. Loading 14B
        while 7B is still resident pegs a 12GB card and never yields a token.
        Fast switches still try to evict, but a stuck unload is logged rather
        than blocking conversation.

        When ``force`` is false, a sticky heavy role absorbs fast/default
        requests so VRAM is not thrashed mid-hold (H6).
        """
        if not force:
            role, _ = self.apply_sticky(role, "ensure")
        if role != self.default_role:
            # A follow-up research/code turn should not race a pending fast pin.
            self._cancel_rewarm()
        if role in _HEAVY_ROLES:
            self.reserve_vram_for_heavy = True
        model = self.model_for(role)
        try:
            await self._evict_others(keep=model)
        except Exception as exc:
            if role in _HEAVY_ROLES:
                raise
            log.warning(
                "Unload while switching to %s failed: %s",
                model,
                exc,
            )
        self.active_role = role
        self.active_model = model
        return model

    async def warm_default(self) -> str:
        """Pin the default conversation model in VRAM (no generation)."""
        self.clear_sticky()
        self.reserve_vram_for_heavy = False
        model = await self.ensure_role(self.default_role, force=True)
        await self.provider.pin(model, keep_alive=self.default_keep_alive)
        return model

    def _schedule_rewarm(self, role: ModelRole) -> None:
        """After research/code, pin `fast` again — delayed so follow-ups stay warm.

        Immediate re-warm made every research turn pay a cold 14B load. Waiting
        `rewarm_delay_s` keeps the research model resident for back-to-back
        deep questions, then returns VRAM to conversation.
        """
        if role == self.default_role or not self.rewarm_after_switch:
            return
        self._schedule_rewarm_default(after=role)

    def _schedule_rewarm_default(self, *, after: str = "detour") -> None:
        """Pin the default conversation model after a VRAM detour (vision, etc.)."""
        if not self.rewarm_after_switch:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._cancel_rewarm()

        async def _run() -> None:
            try:
                if self.rewarm_delay_s > 0:
                    await asyncio.sleep(self.rewarm_delay_s)
                await self.warm_default()
                log.info(
                    "Re-warmed default role `%s` after `%s` (delay=%.0fs)",
                    self.default_role,
                    after,
                    self.rewarm_delay_s,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Could not re-warm default model after %s: %s", after, exc)

        self._rewarm_task = loop.create_task(_run())

    async def run_vision(
        self,
        prompt: str,
        images_b64: list[str],
        *,
        model: str | None = None,
        num_ctx: int = 4096,
    ) -> str:
        """Unload chat, run one VL shot, unload VL, schedule fast rewarm.

        Never keeps the vision model resident next to 7B/14B on a 12GB card.
        """
        self._cancel_rewarm()
        if self.active_model:
            try:
                await self.provider.unload(self.active_model)
            except Exception as exc:
                log.warning(
                    "Unload of chat model %s before vision failed: %s",
                    self.active_model,
                    exc,
                )
            self.active_model = None
            self.active_role = None

        vl_model = (model or self.models.get("vision") or "qwen2.5vl:3b").strip()
        options = {"num_ctx": int(num_ctx)}
        try:
            return await self.provider.chat_with_images(
                vl_model,
                prompt,
                images_b64,
                keep_alive=0,
                options=options,
            )
        finally:
            try:
                await self.provider.unload(vl_model)
            except Exception as exc:
                log.warning("Unload of vision model %s failed: %s", vl_model, exc)
            self._schedule_rewarm_default(after="vision")

    async def _stream_chat_chunks(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        keep_alive: str | int | None,
        options: dict[str, Any] | None,
        tools: list[dict[str, Any]] | None,
        first_token_s: float,
    ) -> AsyncIterator[tuple[str, Any]]:
        """Proxy `stream_chat`, failing a silent heavy load before it locks VRAM."""
        agen = self.provider.stream_chat(
            model,
            messages,
            keep_alive=keep_alive,
            options=options,
            tools=tools,
        )
        try:
            if first_token_s > 0:
                try:
                    first = await asyncio.wait_for(
                        agen.__anext__(), timeout=first_token_s
                    )
                except StopAsyncIteration:
                    return
                except TimeoutError:
                    try:
                        await self.provider.unload(model)
                    except Exception as exc:
                        log.warning(
                            "Unload of %s after first-token timeout failed: %s",
                            model,
                            exc,
                        )
                    self.active_model = None
                    raise RuntimeError(
                        _VRAM_LOCK_NOTICE.format(
                            model=model, seconds=first_token_s
                        )
                    ) from None
                yield first
            async for item in agen:
                yield item
        finally:
            close = getattr(agen, "aclose", None)
            if callable(close):
                try:
                    await close()
                except Exception:
                    pass

    async def stream(
        self,
        role: ModelRole,
        messages: list[dict[str, Any]],
        *,
        options: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        force: bool = False,
    ) -> AsyncIterator[tuple[str, Any]]:
        """Yield (kind, payload) where kind is token|thinking|tool_calls|metrics."""
        if not force:
            role, _ = self.apply_sticky(role, "stream")
        if role != self.default_role:
            self._cancel_rewarm()
        try:
            model = await self.ensure_role(role, force=True)
        except RuntimeError as exc:
            if role in _HEAVY_ROLES and is_vram_failure(exc):
                await self.recover_after_heavy_fail()
            raise
        keep = self.keep_alive_for(role)
        merged = {**self.options_for(role), **(options or {})}
        first_wait = _HEAVY_FIRST_TOKEN_S if role in _HEAVY_ROLES else 0.0
        last_exc: BaseException | None = None
        for attempt in range(_STREAM_RETRIES):
            yielded = False
            try:
                async for kind, payload in self._stream_chat_chunks(
                    model,
                    messages,
                    keep_alive=keep,
                    options=merged or None,
                    tools=tools,
                    first_token_s=first_wait,
                ):
                    yielded = True
                    yield (kind, payload)
                if role in _HEAVY_ROLES:
                    self.mark_sticky(role)
                    self.reserve_vram_for_heavy = False
                self._schedule_rewarm(role)
                return
            except RuntimeError as exc:
                if role in _HEAVY_ROLES and is_vram_failure(exc):
                    await self.recover_after_heavy_fail()
                raise
            except _RETRYABLE as exc:
                last_exc = exc
                if yielded or attempt + 1 >= _STREAM_RETRIES:
                    if role in _HEAVY_ROLES:
                        self.mark_sticky(role)
                    self._schedule_rewarm(role)
                    raise
                delay = _STREAM_BACKOFF_S[min(attempt, len(_STREAM_BACKOFF_S) - 1)]
                log.warning(
                    "Ollama stream failed before first chunk (%s); retry %s/%s in %.1fs",
                    exc,
                    attempt + 1,
                    _STREAM_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)
        if last_exc is not None:
            if role in _HEAVY_ROLES:
                self.mark_sticky(role)
            self._schedule_rewarm(role)
            raise last_exc

    async def close(self) -> None:
        self._cancel_rewarm()
        if self._rewarm_task is not None:
            try:
                await self._rewarm_task
            except (asyncio.CancelledError, Exception):
                pass
        await self.provider.close()
