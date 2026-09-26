"""Everything done once, before the first message.

Three jobs, in the order they run:

Check the configured models are pulled. A missing one used to surface as a
mid-turn HTTP 404; this reports the exact ``ollama pull`` up front instead.

Pin the default chat model so the first turn is not a cold weight load.

Prefill the static prefix, so the first turn is not a cold *prompt* either. The
persona, the telegraph policy and the skinny schemas are around 5,500 tokens and
identical every turn, which is what makes the prefix cache useful — but somebody
has to process them once. Doing it here took the first reply to 0.9s.

This file was ``llm/preflight.py`` and sat beside ``core/preflight.py``, which is
intent detection and shares nothing with it but a name. Nothing here inspects a
user's words.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.llm.ollama import OllamaProvider
from arelis.llm.router import ModelRouter

log = logging.getLogger(__name__)

# STATUS copy the UI matches so the first-turn shimmer is not "thinking…"
# while the prefix seed is still running.
WARMUP_PINNED = "Chat model loaded — preparing the first reply."
WARMUP_READY = "Ready for the first reply."


def model_is_available(available: list[str], wanted: str) -> bool:
    """True if Ollama already has this model name or a tagged variant of it."""
    wanted = wanted.strip()
    if not wanted:
        return True
    if wanted in available:
        return True
    # Config often says qwen2.5:7b while tags lists qwen2.5:7b-instruct-q4_K_M.
    return any(
        name == wanted or name.startswith(f"{wanted}-") or name.startswith(f"{wanted}:")
        for name in available
    )


def missing_models(available: list[str], configured: dict[str, str]) -> list[tuple[str, str]]:
    """Return (role, model) pairs that are configured but not pulled."""
    missing: list[tuple[str, str]] = []
    seen: set[str] = set()
    for role, model in configured.items():
        name = str(model or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        if not model_is_available(available, name):
            missing.append((str(role), name))
    return missing


async def run_model_preflight(
    bus: EventBus,
    provider: OllamaProvider,
    models: dict[str, Any] | None,
) -> None:
    """Publish STATUS events for missing models. Never raises into the UI loop."""
    configured = {
        str(role): str(name)
        for role, name in (models or {}).items()
        if str(name or "").strip()
    }
    if not configured:
        return
    try:
        available = await provider.list_models()
    except Exception as exc:
        log.info("Ollama preflight skipped: %s", exc)
        await bus.publish(
            Event(
                EventType.STATUS,
                {
                    "message": (
                        f"Could not reach Ollama ({exc}). "
                        "Start it, then pull the models in config if needed."
                    )
                },
            )
        )
        return

    for role, name in missing_models(available, configured):
        await bus.publish(
            Event(
                EventType.STATUS,
                {
                    "message": (
                        f"Model `{name}` (role `{role}`) is not pulled. "
                        f"Run: ollama pull {name}"
                    )
                },
            )
        )


async def run_auto_lessons(bus: EventBus, *, enabled: bool = True) -> None:
    """Mine recent turns.log signatures into data/lessons.yaml (append-only)."""
    if not enabled:
        return
    try:
        from arelis.core.lesson_mine import mine_turns_log

        report = mine_turns_log(write=True)
    except Exception as exc:
        log.info("Auto-lessons skipped: %s", exc)
        return
    if not report.lines_scanned:
        return
    fails = report.tool_fail_counts
    if not fails and not report.appended_ids:
        return
    bits: list[str] = []
    if fails:
        top = ", ".join(f"{name}x{n}" for name, n in sorted(fails.items())[:5])
        bits.append(f"recent tool fails: {top}")
    if report.appended_ids:
        bits.append("appended lessons: " + ", ".join(report.appended_ids))
    elif report.proposed_ids:
        bits.append(
            "playbook already covers: " + ", ".join(report.proposed_ids)
        )
    # Only speak when the playbook actually grew. A covered-fail recap every
    # boot ("calculatorx11…") reads as a live error. Keep it in the log.
    if report.appended_ids:
        await bus.publish(
            Event(
                EventType.STATUS,
                {
                    "message": (
                        "Noted recent tool misses and updated the playbook."
                    )
                },
            )
        )
        return
    if bits:
        log.info("Trust mine — %s", "; ".join(bits))


async def run_model_warmup(
    bus: EventBus,
    router: ModelRouter,
    *,
    prefix: PrefixWarmup | None = None,
) -> None:
    """Pin the default chat model so the first turn is not a cold load.

    Pinning loads the weights. It does not process any prompt, and the prompt is
    now the larger half of a first turn: the persona, the telegraph policy and
    the skinny schemas come to roughly 5,500 tokens, which on a 12 GB AMD card
    prefills at a few hundred tokens a second. Passing ``prefix`` sends that
    block once here, so Ollama's prefix cache already holds it.

    The first user turn waits for this to finish (``router.arm_warmup``). If it
    does not, the seed and the turn hit Ollama together and the first token
    waits on two prefills — a minute instead of one 40s load.

    Fail soft throughout: a down Ollama must not block the UI. Toggle with
    `router.warm_on_start`. Always releases the warmup gate so a failed pin
    cannot stall the first message forever.
    """
    try:
        await _run_model_warmup(bus, router, prefix=prefix)
    finally:
        router.mark_warmup_done()


async def _run_model_warmup(
    bus: EventBus,
    router: ModelRouter,
    *,
    prefix: PrefixWarmup | None = None,
) -> None:
    if not router.warm_on_start:
        return
    role = router.default_role
    try:
        model = router.model_for(role)
    except RuntimeError:
        return
    try:
        await router.warm_default()
    except Exception as exc:
        log.info("Ollama warmup skipped: %s", exc)
        await bus.publish(
            Event(
                EventType.STATUS,
                {
                    "message": (
                        f"Could not load the chat model ({exc}). "
                        "The first reply may be slow until Ollama has it."
                    )
                },
            )
        )
        return
    log.info("Chat model pinned (%s)", model)
    await bus.publish(
        Event(
            EventType.STATUS,
            {"message": WARMUP_PINNED},
        )
    )
    if prefix is not None:
        await seed_prefix_cache(bus, router, prefix)


@dataclass(frozen=True)
class PrefixWarmup:
    """The byte-stable front of every prompt, ready to prefill."""

    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    num_ctx: int


def prefix_warmup_for(
    config: dict[str, Any],
    tools: Any,
) -> PrefixWarmup | None:
    """Build the warmup payload from the same pieces a real turn would use.

    Returns None when the pieces are unavailable, because a missing warmup only
    costs a slower first reply and must never keep the app from starting.
    """
    try:
        from arelis.config import load_persona, shipped_num_ctx
        from arelis.core.agent_loop import static_system_prefix

        ollama_cfg = config.get("ollama") or {}
        num_ctx = int(ollama_cfg.get("num_ctx") or shipped_num_ctx())
        return PrefixWarmup(
            messages=list(static_system_prefix(load_persona(config))),
            # The full surface, because that is what a turn sends. Warming a
            # different tools array would seed a prefix no turn ever asks for.
            tools=list(tools.ollama_tools()),
            num_ctx=num_ctx,
        )
    except Exception as exc:
        log.info("Prefix warmup unavailable: %s", exc)
        return None


async def seed_prefix_cache(
    bus: EventBus,
    router: ModelRouter,
    prefix: PrefixWarmup,
) -> None:
    """Prefill the static prefix so the first real turn reuses it."""
    model = router.active_model or router.model_for(router.default_role)
    started = time.perf_counter()
    try:
        # num_predict=1 because the reply is discarded; the point is that the
        # prompt in front of it has been processed. Drained rather than
        # cancelled: abandoning the stream mid-prefill can leave the runner
        # without the cache entry this exists to create.
        stream = router.provider.stream_chat(
            model,
            prefix.messages,
            tools=prefix.tools,
            keep_alive=router.default_keep_alive,
            options={"num_ctx": prefix.num_ctx, "num_predict": 1},
        )
        async for _kind, _payload in stream:
            pass
    except Exception as exc:
        # Nothing is broken by this failing; the first turn just pays the
        # prefill itself, exactly as it did before.
        log.info("Prefix cache seed skipped: %s", exc)
        return
    elapsed = time.perf_counter() - started
    log.info("Seeded prefix cache for %s in %.1fs", model, elapsed)
    await bus.publish(
        Event(
            EventType.STATUS,
            {"message": WARMUP_READY},
        )
    )
