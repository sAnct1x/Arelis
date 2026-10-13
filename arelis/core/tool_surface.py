"""Which tools the model is offered this round. Two phases, one copy each.

`turn_prepare` builds the surface for round one and `turn_round` rebuilds it
when the turn escalates to a bigger model. The two had the same seven steps in
the same order, written twice, and they had drifted: the escalate copy did not
pass `extra_skill_ids`, so the active room's skills were in reach on round one
and gone on round two. The comment in `turn_prepare` explaining why room extras
ride on `filter_tool_names`, "keep analyze/cas in reach", was true for
exactly as long as the turn did not escalate.

The roadmap called this "one function, called twice". It is two, and that is
the reason the drift was invisible. In `turn_prepare` the steps are 130 lines
apart, because everything between them is what decides `loop._expected_tools`:
preflight hints add to it, the weather narrowing discards from it, and the turn
goal rewrites it. The second phase reads that set, so it cannot move up. In
`turn_round` the two run back to back, because on escalate the set was settled
last round.

So: `base_surface` is what the role, the text and the room allow, and
`apply_expected` is what this turn's intent then does to it.
"""

from __future__ import annotations

import logging
from typing import Any

from arelis.core.agent_loop import (
    _HIDE_WANDER_FOR,
    _hide_daily_wander,
    _offer_expected,
)
from arelis.core.intent_catalog import profile_place_ask, weather_intent_matches
from arelis.core.look import LOOK_TOOL_SUBSET
from arelis.core.native_tool_calling import native_tool_calling
from arelis.core.sms_complete import looks_like_stale_sms_skip
from arelis.core.tool_subset import filter_tool_names

log = logging.getLogger(__name__)

# Comms stay in the expected set when they are not registered. The turn
# then says the account is missing. Desktop, vision, and camera have no
# such line: a hint that names them on a machine where they were not
# registered is skipped, not raised.
_ABSENT_HINT_KEEP = frozenset(
    {
        "send_sms",
        "inbound_sms",
        "send_email",
        "inbox",
        "agenda",
    }
)


_TOOL_LOADING_MODES = frozenset({"off", "tail", "front"})


def _tool_loading_mode(agent_cfg: dict[str, Any] | None) -> str:
    """off, tail, or front. A missing key is off. Anything else logs and is off."""
    if not agent_cfg or "tool_loading" not in agent_cfg:
        return "off"
    raw = agent_cfg.get("tool_loading")
    # An unquoted off in YAML is boolean False. That is off, not a typo.
    if raw is False:
        return "off"
    mode = raw.strip().lower() if isinstance(raw, str) else str(raw).strip().lower()
    if mode in _TOOL_LOADING_MODES:
        return mode
    log.info(
        "agent.tool_loading %r is not off, tail, or front; using off",
        raw,
    )
    return "off"


def _load_tools_spec(param_hints: bool) -> dict[str, Any]:
    """The load_tools schema, shaped like the registry's other tools."""
    from arelis.core.compact_prompt import skinny_ollama_tool
    from arelis.tools.load_tools import LoadTools
    from arelis.tools.model_schema import model_parameters

    tool = LoadTools()
    spec = skinny_ollama_tool(
        tool.name,
        tool.description,
        tool.parameters_schema,
        param_hints=param_hints,
    )
    fn = spec["function"]
    fn["parameters"] = model_parameters(tool.name, fn["parameters"])
    return spec


def _core_plus_load_tools(tools: Any, hints: bool) -> list[dict[str, Any]]:
    """Registered core tools, registry order, then the load_tools schema."""
    from arelis.tools.groups import CORE

    core = set(CORE)
    full = list(tools.ollama_tools(param_hints=hints))
    kept = [
        spec
        for spec in full
        if str((spec.get("function") or {}).get("name") or "") in core
    ]
    return [*kept, _load_tools_spec(hints)]


def _frozen_loading_list(
    tools: Any, hints: bool, mode: str
) -> list[dict[str, Any]]:
    """tail or front. Same mode returns the same list. A new mode rebuilds."""
    frozen = getattr(tools, "_session_schema_freeze", None)
    if (
        isinstance(frozen, tuple)
        and len(frozen) == 3
        and frozen[0] == hints
        and frozen[1] == mode
        and isinstance(frozen[2], list)
    ):
        return frozen[2]
    built = _core_plus_load_tools(tools, hints)
    try:
        tools._session_schema_freeze = (hints, mode, built)
    except Exception:
        # A stand-in registry may refuse the attribute. The list is still valid.
        return built
    return built


def session_tool_schemas(tools: Any, agent_cfg: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Every tool registered this session, in registry order.

    Built once for this registry and reused. The startup warmup and every
    turn read that same list, so the bytes stay put until Settings builds
    a new registry. Routing may still decide which calls are allowed.
    That decision does not add or remove schemas here.

    agent.tool_loading off is that full list. tail and front send the
    registered core tools plus load_tools. A mode change rebuilds once.
    """
    hints = bool(native_tool_calling(agent_cfg))
    mode = _tool_loading_mode(agent_cfg)
    if mode != "off":
        return _frozen_loading_list(tools, hints, mode)
    frozen = getattr(tools, "_session_schema_freeze", None)
    if (
        isinstance(frozen, tuple)
        and len(frozen) == 2
        and frozen[0] == hints
        and isinstance(frozen[1], list)
    ):
        return frozen[1]
    # names omitted: the registry's full list, same call the warmup uses.
    built = list(tools.ollama_tools(param_hints=hints))
    try:
        tools._session_schema_freeze = (hints, built)
    except Exception:
        # A stand-in registry may refuse the attribute. The list is still valid.
        return built
    return built


def omit_unregistered_hints(expected: set[str], available_all: set[str]) -> set[str]:
    """Drop hint names this session did not register.

    Keeps mail, SMS, and agenda so a missing account still gets its
    reply. Everything else (desktop on a Mac, vision without the VL
    model) is skipped.
    """
    available = set(available_all)
    return {
        name
        for name in expected
        if name in available or name in _ABSENT_HINT_KEEP
    }


def cap_to_room(available_all: set[str], active_room: Any) -> set[str]:
    """Apply a room's explicit `tools:` cage, and say so when it cannot hold.

    Rooms lean rather than cage by default, `rooms.py` argues the point at
    length, that a caged agent which has to refuse the time of day teaches you
    to stop asking. So a `tools:` list is not a side effect of naming a folder,
    it is a decision somebody made, and it is worth a line in the log when it
    does not mean what it says.

    A name that is not installed drops out of the cage silently: a typo, a tool
    since renamed, a room written against a build that had it. When *every*
    name drops out the cage disappears and the room gets the whole registry
    while the rooms tool goes on printing "limited to tools: …" either way.

    The fail-open is deliberate and stays. A room cut down to nothing could not
    answer anything, which is worse than an unenforced cage and is the exact
    failure rooms lean to avoid. What changes is that it is no longer quiet.
    """
    named = {n for n in (getattr(active_room, "tools", None) or ()) if n}
    if not named:
        return available_all
    missing = named - available_all
    capped = available_all & named
    if not capped:
        log.warning(
            "Room %r limits tools to %s, none of which are installed, the "
            "limit cannot be applied and the room is leaning on the full tool "
            "set instead.",
            getattr(active_room, "name", "?"),
            ", ".join(sorted(named)),
        )
        return available_all
    if missing:
        log.warning(
            "Room %r limits tools to %s, but %s %s not installed and will be "
            "ignored.",
            getattr(active_room, "name", "?"),
            ", ".join(sorted(named)),
            ", ".join(sorted(missing)),
            "is" if len(missing) == 1 else "are",
        )
    return capped


def base_surface(
    loop: Any,
    available_all: set[str],
    *,
    role: str,
    text: str,
    agent_cfg: dict[str, Any],
    active_room: Any = None,
) -> tuple[set[str], set[str]]:
    """The surface before this turn's intent narrows it. Returns (available, visible).

    `active_room` is not optional in spirit, omitting it drops the room's
    skills, which is the bug this module exists to close. It is keyword-only
    and defaulted so the caller that has no room does not have to say so.
    """
    room_skills = tuple(active_room.spec.skills) if active_room is not None else ()
    visible = filter_tool_names(
        available_all,
        role=role,
        text=text,
        enabled=bool(agent_cfg.get("research_tool_subset", False)),
        skill_subset=bool(agent_cfg.get("skill_tool_subset", False)),
        history=loop.memory.messages,
        extra_skill_ids=room_skills,
        agent_cfg=agent_cfg,
    )
    available = visible
    if loop._look is not None:
        look_tools = {n for n in available_all if n in LOOK_TOOL_SUBSET}
        if look_tools:
            available = look_tools
            visible = look_tools
    return set(available), set(visible)


def apply_expected(
    loop: Any,
    available: set[str],
    *,
    text: str,
    available_all: set[str],
) -> tuple[set[str], set[str]]:
    """Narrow and widen by `loop._expected_tools`. Returns (available, visible).

    Must run after `_expected_tools` is final. In `turn_prepare` that is after
    the preflight hints, the weather narrowing and the turn goal have all had
    their say.

    A hint may name a tool this session never registered. Those names are
    dropped here so a later step does not try to call them.
    """
    dropped = [
        name
        for name in list(loop._expected_tools)
        if name not in available_all and name not in _ABSENT_HINT_KEEP
    ]
    for name in dropped:
        loop._expected_tools.discard(name)
    if dropped:
        log.info(
            "Skipped hint tools that are not in this session: %s",
            ", ".join(sorted(dropped)),
        )
    if loop._expected_tools & _HIDE_WANDER_FOR:
        available = _hide_daily_wander(set(available), loop._expected_tools)
    # A saved-place ask with the planet and the browser still on the menu
    # spends the turn on Earth and web pages. Weather keeps its own menu.
    if profile_place_ask(text) and not weather_intent_matches(text):
        available = set(available)
        for name in ("earth", "browser", "web_search", "scrape", "web_fetch"):
            available.discard(name)
        if "user_location" in available_all:
            available.add("user_location")
            loop._expected_tools.add("user_location")
    available = _offer_expected(available, loop._expected_tools, available_all)
    if (
        looks_like_stale_sms_skip(text, loop.memory.messages)
        and "send_sms" not in loop._expected_tools
    ) or loop._look is not None:
        available = set(available)
        available.discard("send_sms")
        available.discard("send_email")
    return set(available), set(available)


def refresh_session_tools(window: Any, *, recheck_vl: bool = False) -> bool:
    """Rebuild the session registry after Settings turns a tool on or off.

    Returns True only when the registered names changed. That path reseeds
    the prefix cache once. A save that does not change the set does neither.
    """
    try:
        return _refresh_session_tools(window, recheck_vl=recheck_vl)
    except Exception:
        log.exception("Session tool list was not rebuilt")
        return False


def _refresh_session_tools(window: Any, *, recheck_vl: bool) -> bool:
    orchestrator = getattr(window, "orchestrator", None)
    if orchestrator is None:
        return False
    old = getattr(orchestrator, "tools", None)
    if old is None:
        return False
    config = getattr(window, "config", None) or getattr(orchestrator, "config", None)
    if not isinstance(config, dict):
        return False
    if recheck_vl:
        from arelis.llm.startup import vl_model_installed

        vl_model_installed(config, refresh=True)
    from arelis.memory import MemoryStore
    from arelis.tools import build_tool_registry

    router = getattr(window, "router", None) or getattr(orchestrator, "router", None)
    provider = getattr(router, "provider", None)
    sink = getattr(getattr(orchestrator, "memory", None), "sink", None)
    store = sink if isinstance(sink, MemoryStore) else None
    workspace = getattr(orchestrator, "workspace", None) or config.get("_workspace")
    new = build_tool_registry(
        config,
        workspace,
        allow_send=True,
        attended=True,
        memory_store=store,
        provider=provider,
        router=router,
    )
    if set(old.names()) == set(new.names()):
        return False
    _copy_transcribe_stt(old, new)
    orchestrator.tools = new
    _reseed_session_prefix(window, new)
    return True


def _copy_transcribe_stt(old: Any, new: Any) -> None:
    previous = old.get("transcribe") if hasattr(old, "get") else None
    current = new.get("transcribe") if hasattr(new, "get") else None
    if previous is None or current is None:
        return
    stt = getattr(previous, "_stt", None)
    if stt is not None and getattr(current, "_stt", None) is None:
        current._stt = stt


def _reseed_session_prefix(window: Any, tools: Any) -> None:
    import asyncio

    from arelis.llm.startup import prefix_warmup_for, seed_prefix_cache

    loop = getattr(window, "loop", None)
    router = getattr(window, "router", None)
    bus = getattr(window, "bus", None)
    config = getattr(window, "config", None)
    if loop is None or router is None or bus is None or not isinstance(config, dict):
        return
    prefix = prefix_warmup_for(config, tools)
    if prefix is None:
        return
    asyncio.run_coroutine_threadsafe(
        seed_prefix_cache(bus, router, prefix, announce=False),
        loop,
    )
