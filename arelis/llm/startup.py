"""Everything done once, before the first message.

Three jobs, in the order they run:

Check the configured models are present. A missing one used to surface as a
mid-turn HTTP 404; this reports that up front instead.

Pin the default chat model so the first turn is not a cold weight load.

Prefill the static prefix, so the first turn is not a cold *prompt* either. The
persona, the telegraph policy and the skinny schemas are around 5,500 tokens and
identical every turn, which is what makes the prefix cache useful, but somebody
has to process them once. Doing it here took the first reply to 0.9s.

This file was ``llm/preflight.py`` and sat beside ``core/preflight.py``, which is
intent detection and shares nothing with it but a name. Nothing here inspects a
user's words.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.llm.router import ModelRouter

log = logging.getLogger(__name__)

# STATUS copy the UI matches so the first-turn shimmer is not "thinking…"
# while the prefix seed is still running.
WARMUP_PINNED = "Chat model loaded, preparing the first reply."
WARMUP_READY = "Ready for the first reply."


def vl_model_installed(
    config: dict[str, Any] | None,
    *,
    refresh: bool = False,
) -> bool:
    """True when the chat launch line has a picture file on disk.

    The 35B reads pictures through the Q8 mmproj next to the GGUF. A profile
    with no model path, and a profile that only names the bare GGUF file,
    resolve that file the same way ``launch_args_for`` does, including the
    installed profile's model folder and a relative path from the data dir.
    When that search finds nothing, a llama-server already listening is
    asked for the GGUF it loaded. Launch args that name a missing mmproj do
    not count, and neither does a running server whose picture file is
    missing. ``config["_vl_model_installed"]`` forces the gate for tests.
    ``refresh`` is accepted so Settings can ask again. The check is a file
    stat, so a later call sees a file that showed up.
    """
    del refresh
    config = config or {}
    override = config.get("_vl_model_installed")
    if isinstance(override, bool):
        return override
    return _mmproj_on_launch_line(config)


def _mmproj_on_launch_line(config: dict[str, Any]) -> bool:
    """True when the launch line, or the server already up, has the picture file."""
    from arelis.llm.llama_launch import launch_args_for, mmproj_beside_running_server

    args = launch_args_for(config)
    if not args:
        return mmproj_beside_running_server(config)
    try:
        index = args.index("--mmproj")
    except ValueError:
        return False
    if index + 1 >= len(args):
        return False
    return Path(args[index + 1]).is_file()


def _model_identities(name: str) -> frozenset[str]:
    """Comparable ids for a config name or a llama-server listing.

    llama-server lists a GGUF path or an ``--alias``. Config stores the
    family name or the file name. Compare those pieces, case-insensitive.
    """
    raw = (name or "").strip()
    if not raw:
        return frozenset()
    keys = {raw.casefold()}
    base = Path(raw).name
    if base:
        keys.add(base.casefold())
        suffix = ".gguf"
        if base.casefold().endswith(suffix):
            keys.add(base[: -len(suffix)].casefold())
    return frozenset(key for key in keys if key)


def model_is_available(available: list[str], wanted: str) -> bool:
    """True if the configured name is the listed GGUF file or server alias."""
    wanted = wanted.strip()
    if not wanted:
        return True
    want = _model_identities(wanted)
    for name in available:
        have = _model_identities(name)
        if want & have:
            return True
        for left in want:
            for right in have:
                if right.startswith(f"{left}-") or left.startswith(f"{right}-"):
                    return True
    return False


async def listed_server_models(provider: Any) -> list[str]:
    """Ids from ``/v1/models`` plus GGUF path and alias from ``/props``."""
    names = [str(item) for item in await provider.list_models()]
    extra_fn = getattr(provider, "props_model_names", None)
    if not callable(extra_fn):
        return names
    try:
        extra = await extra_fn()
    except Exception:
        # /props is optional. The /v1/models ids are enough to match.
        return names
    seen = set(names)
    for item in extra:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            names.append(text)
    return names


def missing_models(available: list[str], configured: dict[str, str]) -> list[tuple[str, str]]:
    """Return (role, model) pairs that are configured but not on the server."""
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
    provider: Any,
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
        available = await listed_server_models(provider)
    except Exception as exc:
        log.warning("Model preflight skipped", exc_info=exc)
        await bus.publish(
            Event(
                EventType.STATUS,
                {
                    "message": (
                        "Could not reach the local model. "
                        "Start it, then try again."
                    )
                },
            )
        )
        return

    for _role, name in missing_models(available, configured):
        await bus.publish(
            Event(
                EventType.STATUS,
                {"message": f"The model {name} isn't on the server yet."},
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
        log.info("Trust mine, %s", "; ".join(bits))


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
    block once here, so the prefix cache already holds it.

    The first user turn waits for this to finish (``router.arm_warmup``). If it
    does not, the seed and the turn hit the server together and the first token
    waits on two prefills, a minute instead of one 40s load.

    Fail soft throughout: a down server must not block the UI. Toggle with
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
        log.info("Warmup skipped: %s", exc)
        await bus.publish(
            Event(
                EventType.STATUS,
                {
                    "message": (
                        f"Could not load the chat model ({exc}). "
                        "The first reply may be slow until the server has it."
                    )
                },
            )
        )
    else:
        log.info("Chat model pinned (%s)", model)
        await bus.publish(
            Event(
                EventType.STATUS,
                {"message": WARMUP_PINNED},
            )
        )
    # A failed pin used to return here and open the gate with no seed, so the
    # first turn prefills cold. The seed still has to finish before that gate opens.
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
        from arelis.core.tool_surface import session_tool_schemas

        agent_cfg = config.get("agent") or {}
        lc = config.get("llamacpp") or {}
        num_ctx = int(lc.get("default_cap") or shipped_num_ctx())
        return PrefixWarmup(
            messages=list(static_system_prefix(load_persona(config))),
            # Same function a turn calls, so the seed is a prefix of turn 1.
            tools=session_tool_schemas(tools, agent_cfg),
            num_ctx=num_ctx,
        )
    except Exception as exc:
        log.info("Prefix warmup unavailable: %s", exc)
        return None


async def seed_prefix_cache(
    bus: EventBus,
    router: ModelRouter,
    prefix: PrefixWarmup,
    *,
    announce: bool = True,
) -> None:
    """Prefill the static prefix so the next turn reuses it.

    ``announce`` is for the startup seed. A mid-session rebuild stays quiet:
    the first-reply line would be wrong in the middle of a chat.
    """
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
        try:
            async for _kind, _payload in stream:
                pass
        finally:
            close = getattr(stream, "aclose", None)
            if callable(close):
                try:
                    await close()
                except Exception:
                    # The stream is already drained. A close error is not a
                    # failed seed, and it must not hide one either.
                    pass
    except Exception as exc:
        # Nothing is broken by this failing; the first turn just pays the
        # prefill itself, exactly as it did before.
        log.info("Prefix cache seed skipped: %s", exc)
        return
    elapsed = time.perf_counter() - started
    log.info("Seeded prefix cache for %s in %.1fs", model, elapsed)
    if not announce:
        return
    await bus.publish(
        Event(
            EventType.STATUS,
            {"message": WARMUP_READY},
        )
    )
