"""Startup check that configured chat models are actually pulled.

list_models exists on the provider but used to be called nowhere in production.
A missing model used to surface as a mid-turn HTTP 404. This reports the exact
`ollama pull` before the first message, without blocking the window if Ollama
is slow or down.
"""

from __future__ import annotations

import logging
from typing import Any

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.llm.ollama import OllamaProvider
from arelis.llm.router import ModelRouter

log = logging.getLogger(__name__)


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
    if not bits:
        return
    await bus.publish(
        Event(EventType.STATUS, {"message": "Trust mine — " + "; ".join(bits)})
    )


async def run_model_warmup(bus: EventBus, router: ModelRouter) -> None:
    """Pin the default chat model so the first turn is not a cold load.

    Fail soft: a down Ollama must not block the UI. Toggle with
    `router.warm_on_start`.
    """
    if not router.warm_on_start:
        return
    role = router.default_role
    try:
        model = router.model_for(role)
    except RuntimeError:
        return
    await bus.publish(
        Event(
            EventType.STATUS,
            {"message": f"Warming conversation model `{model}`…"},
        )
    )
    try:
        await router.warm_default()
    except Exception as exc:
        log.info("Ollama warmup skipped: %s", exc)
        await bus.publish(
            Event(
                EventType.STATUS,
                {
                    "message": (
                        f"Could not warm `{model}` ({exc}). "
                        "First reply may be slower until Ollama loads it."
                    )
                },
            )
        )
        return
    await bus.publish(
        Event(
            EventType.STATUS,
            {"message": f"Conversation model `{model}` ready."},
        )
    )
