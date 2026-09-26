from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from arelis.config import shipped_num_ctx
from arelis.core.agenda_complete import (
    complete_agenda_draft,
    looks_like_calendar_create,
    looks_like_calendar_delete,
    looks_like_calendar_read,
)
from arelis.core.agent_loop import (
    _SEE_NO_SMS_REDIRECT,
    _SPEAK_TOOL_OUTPUT_CHARS,
    disconnected_integration_reply,
    should_offer_tools,
    static_system_prefix,
    turn_expects_tool_round,
    wants_fresh_page_ask,
)
from arelis.core.claims import apply_research_web_need, detect_exactness_need
from arelis.core.context import context_budget
from arelis.core.email_complete import (
    complete_email_draft,
    looks_like_compose_email,
    looks_like_mailbox_mutate,
    looks_like_schedule_manage,
    looks_like_scheduled_send,
)
from arelis.core.events import Event, EventType
from arelis.core.image_refs import CAMERA_FRESH_S, latest_camera_image_file
from arelis.core.look import LookTurn, classify_look, frame_sha256
from arelis.core.other_work import looks_like_other_work
from arelis.core.preflight import looks_like_room_create
from arelis.core.prompt_sections import (
    append_delivery_context,
    append_operating_context,
    append_plan_and_lessons,
    append_preflight_guidance,
    append_stopped_turn_note,
    append_turn_goal,
    choose_active_plan,
)
from arelis.core.skills import select_skill_ids_detailed
from arelis.core.sms_complete import (
    complete_sms_draft,
    draft_send_sms_args,
    looks_like_closing_chitchat,
    sms_intent_this_turn,
)
from arelis.core.tool_subset import (
    is_research_mode,
    turn_round_budget,
)
from arelis.core.tool_surface import apply_expected, base_surface, cap_to_room
from arelis.core.turn_context import TurnContext
from arelis.core.turn_telemetry import TurnTimer, turn_telemetry_enabled
from arelis.llm.router import ModelRole


@dataclass
class _TurnStart:
    model: str
    speak: bool
    agent_cfg: dict[str, Any]
    ratio: float
    research_mode: bool
    available_all: set[str]
    active_room: Any
    available: set[str]
    visible: set[str]


async def _begin_turn(
    loop: Any,
    text: str,
    role: ModelRole,
    *,
    source: str,
    route_reason: str,
) -> _TurnStart:
    """Reset turn-local state, select the model, and build the base tool surface."""
    model = loop.router.model_for(role)
    # Phone conversation is this seat only. PC conversation being on
    # must not shorten phone replies, and the reverse is also true.
    if source == "mobile":
        speak = bool(loop.config.get("_phone_speak"))
    else:
        speak = bool(loop.config.get("_speak_replies"))
    loop._turn_source = source
    sink = loop.memory.sink
    session_id = str(getattr(sink, "session_id", None) or "")
    loop._timer = TurnTimer(
        source=source,
        role=role,
        speak=speak,
        user_chars=len(text),
        enabled=turn_telemetry_enabled(loop.config),
        session_id=session_id,
        route_reason=route_reason,
        user_text=text,
    )
    # Per-turn state — must not leak across conversation turns (soak found
    # tools_used accumulating and poisoning vision/image duplicate gates).
    loop.tools_used = set()
    browser = loop.tools.get("browser")
    if browser is not None:
        browser.pixel_ok = False
    desktop = loop.tools.get("desktop")
    if desktop is not None:
        desktop.pixel_ok = False
    from arelis.look_scratch import clear_look_pending, hold_look_files, keep_look_files

    clear_look_pending()
    hold_look_files(keep_look_files(text))
    loop._trace = []
    loop._painted = ""
    # Mutable so mid-turn escalate (W2) can retarget the hot model.
    loop._turn_role = role
    loop._escalated = False
    loop._expected_tools = set()
    loop._fail_replan_used = False
    loop._active_plan = None
    loop._receipts = []
    dock_live = callable(loop.config.get("_camera_capture"))
    fresh = latest_camera_image_file(max_age_s=CAMERA_FRESH_S)
    look_intent = classify_look(
        text,
        dock_live=dock_live,
        fresh_path=fresh,
        history=loop.memory.messages,
    )
    loop._look = None
    if look_intent is not None:
        loop._look = LookTurn(
            intent=look_intent,
            path=str(look_intent.path or ""),
        )
        if loop._look.path:
            loop._look.sha = frame_sha256(loop._look.path)
    agent_cfg = loop.config.get("agent") or {}
    loop.max_rounds = turn_round_budget(role, text, agent_cfg, loop._default_max_rounds)
    active = getattr(loop.router, "active_model", None)
    if active and active != model:
        await loop.bus.publish(
            Event(
                EventType.MODEL_SWITCH,
                {"from": active, "to": model, "role": role},
            )
        )
    await loop.bus.publish(
        Event(EventType.STATUS, {"message": f"Role `{role}` -> model `{model}`"})
    )
    if (role or "").strip().lower() == "research":
        from arelis.llm.ollama import same_ollama_model

        needs_swap = True
        try:
            fast_tag = str(loop.router.model_for("fast") or "")
            needs_swap = not same_ollama_model(fast_tag, model)
        except Exception:
            needs_swap = True
        if active and same_ollama_model(str(active), model):
            needs_swap = False
        if needs_swap:
            from arelis.llm.vram import free_gpu_neighbors

            await free_gpu_neighbors(loop.config, loop.bus)
            await loop.bus.publish(
                Event(
                    EventType.STATUS,
                    {
                        "message": (
                            f"Loading `{model}` — previous chat model was unloaded so it can fit."
                        )
                    },
                )
            )
    await loop.bus.publish(
        Event(
            EventType.THINKING,
            {"text": f"round 0/{loop.max_rounds}  composing with {model}"},
        )
    )

    ratio = loop._token_ratios.get(model)
    loop.memory.chars_per_token = ratio
    loop.memory.add("user", text)
    agent_cfg = loop.config.get("agent") or {}
    research_mode = is_research_mode(role, text)
    available_all = set(loop.tools.names())
    # Cap the source so every later recompute inherits a room's explicit cage.
    active_room = getattr(loop.config.get("_rooms"), "active", None)
    if active_room is not None:
        available_all = cap_to_room(available_all, active_room)
    available, visible = base_surface(
        loop,
        available_all,
        role=role,
        text=text,
        agent_cfg=agent_cfg,
        active_room=active_room,
    )
    if loop._timer is not None and len(visible) < len(available_all):
        loop._timer.mark(
            "tool_subset",
            visible=len(visible),
            available=len(available_all),
        )
    return _TurnStart(
        model=model,
        speak=speak,
        agent_cfg=agent_cfg,
        ratio=ratio,
        research_mode=research_mode,
        available_all=available_all,
        active_room=active_room,
        available=available,
        visible=visible,
    )


@dataclass
class _TurnDrafts:
    sms: Any
    email: Any
    agenda: Any
    skip_sms: bool


def _reconstruct_turn_drafts(loop: Any, text: str) -> _TurnDrafts:
    """Rebuild current SMS, email, and agenda drafts from live history."""
    # Image-gen / goals / file-write / calendar-create must not revive a
    # stale SMS draft unless this turn itself starts with an SMS verb.
    other_work = looks_like_other_work(text, loop.memory.messages)
    skip_sms = other_work and not re.match(
        r"(?i)^\s*(?:text|sms|txt|send\s+(?:a\s+)?(?:text|sms|message))\b",
        text or "",
    )
    sms_draft = None if skip_sms else complete_sms_draft(text, history=loop.memory.messages)
    # Scheduled sends and mailbox operations can contain "email" without
    # being letter composition.
    skip_email = other_work and (
        looks_like_scheduled_send(text)
        or looks_like_schedule_manage(text)
        or looks_like_room_create(text)
        or looks_like_mailbox_mutate(text)
        or not looks_like_compose_email(text)
    )
    email_draft = None if skip_email else complete_email_draft(text, history=loop.memory.messages)
    return _TurnDrafts(
        sms=sms_draft,
        email=email_draft,
        agenda=complete_agenda_draft(text, history=loop.memory.messages),
        skip_sms=skip_sms,
    )


def _context_limits(
    loop: Any,
    role: ModelRole,
    *,
    speak: bool,
    skill_ids: list[str],
) -> tuple[int, int]:
    """Reserve context for pinned prompt sections and possible tool output."""
    ollama_cfg = loop.config.get("ollama") or {}
    num_ctx = int(ollama_cfg.get("num_ctx") or shipped_num_ctx())
    if role == "research" and ollama_cfg.get("research_num_ctx"):
        num_ctx = int(ollama_cfg["research_num_ctx"])
    # Sticky for the turn so mid-escalate does not shrink under a built prompt.
    loop._turn_num_ctx = num_ctx
    tool_reserve_chars = (
        min(loop.tool_output_chars, _SPEAK_TOOL_OUTPUT_CHARS) if speak else loop.tool_output_chars
    )
    # Spoken small-talk should not sacrifice history to a scrape slab.
    if speak and not loop._expected_tools and not skill_ids:
        tool_reserve_chars = 0
    return num_ctx, tool_reserve_chars


async def _attach_tool_schemas_and_history(
    loop: Any,
    ctx: TurnContext,
    system_messages: list[dict[str, str]],
    *,
    num_ctx: int,
    tool_reserve_chars: int,
    ratio: float,
    role: ModelRole,
    text: str,
    wants_fresh_page: bool,
    offer_tools: bool,
    expect_tool_round: bool,
    ollama_tools: list[dict[str, Any]],
) -> None:
    """Pay for tool schemas, then append as much conversation history as fits."""
    budget = context_budget(
        num_ctx,
        tool_output_chars=tool_reserve_chars,
        chars_per_token=ratio,
        schema_chars=len(json.dumps(ollama_tools)) if ollama_tools else 0,
    )
    ctx.wants_fresh_page = wants_fresh_page
    ctx.offer_tools = offer_tools
    ctx.expect_tool_round = expect_tool_round
    ctx.ollama_tools = ollama_tools
    ctx.messages = await loop._messages_for_turn(
        system_messages, budget, ratio, role, user_text=text
    )


async def _prepare_sms_first_move(
    loop: Any,
    ctx: TurnContext,
    text: str,
    agent_cfg: dict[str, Any],
) -> None:
    """Prepare a complete SMS draft for the confirmation-first fast path."""
    sms_draft = ctx.sms_draft
    if (
        "send_sms" in loop._expected_tools
        and "send_sms" not in ctx.available_all
        and sms_intent_this_turn(text)
    ):
        await loop._explain_missing_send_sms(ctx.available_all)
    elif sms_draft is not None and sms_draft.complete and not ctx.skip_sms_draft:
        if "send_sms" not in ctx.tool_names:
            if sms_intent_this_turn(text):
                await loop._explain_missing_send_sms(ctx.available_all)
        elif bool(agent_cfg.get("sms_force_call", True)) and bool(
            agent_cfg.get("sms_preinject", True)
        ):
            from arelis.core.turn_goal import sms_body_serves_goal

            inj = draft_send_sms_args(sms_draft)
            if sms_body_serves_goal(str(inj.get("body") or "")):
                ctx.sms_preinject = inj


async def prepare_turn(
    loop: Any,
    text: str,
    role: ModelRole,
    *,
    source: str = "chat",
    route_reason: str = "default",
    stopped_ask: str = "",
) -> TurnContext | None:
    """Build the prompt and TurnContext. None if the turn already finished."""
    start = await _begin_turn(
        loop,
        text,
        role,
        source=source,
        route_reason=route_reason,
    )
    model = start.model
    speak = start.speak
    agent_cfg = start.agent_cfg
    ratio = start.ratio
    research_mode = start.research_mode
    available_all = start.available_all
    active_room = start.active_room
    available = start.available
    visible = start.visible
    # Static prefix first (persona + telegraph policy) so the front of
    # the prompt is byte-stable across turns. Turn-specific lines trail it,
    # never precede it.
    system_messages = static_system_prefix(loop.persona)
    append_stopped_turn_note(system_messages, stopped_ask)
    drafts = _reconstruct_turn_drafts(loop, text)
    sms_draft = drafts.sms
    email_draft = drafts.email
    agenda_draft = drafts.agenda
    skip_sms_draft = drafts.skip_sms
    preflight_kinds = append_preflight_guidance(
        system_messages,
        loop,
        text,
        agent_cfg,
        see_no_sms_redirect=_SEE_NO_SMS_REDIRECT,
    )
    # Room extras stay on filter_tool_names (keep analyze/cas in reach).
    # Mixing them into skill_ids made select_plan treat the lean as
    # this-turn intent, so an analysis room demanded a CSV on
    # "how do toroids relate to physics?".
    skill_ids, fallback_only = select_skill_ids_detailed(text, available_tools=available)
    # The unmatched "what is" web floor is a tool-menu hint, not a scrape
    # plan. Clock asks already special-case this; definitional physics
    # questions used to get the same cage once room extras stopped
    # suppressing the fallback.
    plan_ids = () if fallback_only else skill_ids
    # Short thanks/bye must not revive weather (or a stale web_search habit).
    if looks_like_closing_chitchat(text):
        available = set(available)
        available.discard("weather")
        available.discard("web_search")
        visible = available
        loop._expected_tools.discard("weather")
        loop._expected_tools.discard("web_search")
    turn_goal = append_turn_goal(
        system_messages,
        loop,
        text,
        role,
        preflight_kinds=preflight_kinds,
        sms_draft=sms_draft,
        email_draft=email_draft,
        research_mode=research_mode,
    )
    # The vision tool used to be hidden behind a keyword list, because
    # looking cost an unload, a cold VL load, and a re-warm. A multimodal
    # chat model sees at the window it is already loaded with (see
    # ModelRouter.run_vision), so the schema is the only cost left and the
    # window has room for it. The list was also a trap: any phrasing outside
    # it — "what is this?" beside a fresh attachment — left the model
    # schema-blind and it invented a caption.
    available, visible = apply_expected(loop, available, text=text, available_all=available_all)
    active_plan = choose_active_plan(
        text,
        preflight_kinds=preflight_kinds,
        plan_ids=plan_ids,
        available_all=available_all,
    )
    disconnected = disconnected_integration_reply(
        expected=loop._expected_tools,
        available=available_all,
        want_sms=bool(
            (sms_draft is not None and sms_draft.complete and not skip_sms_draft)
            or sms_intent_this_turn(text)
        ),
        want_mail=bool(
            (email_draft is not None and email_draft.complete) or looks_like_compose_email(text)
        ),
        want_calendar=bool(
            (agenda_draft is not None and agenda_draft.complete)
            or looks_like_calendar_read(text)
            or looks_like_calendar_create(text)
            or looks_like_calendar_delete(text)
        ),
    )
    if disconnected:
        await loop._finish(disconnected, [])
        return None
    loop._active_plan = active_plan
    append_plan_and_lessons(
        system_messages,
        loop,
        text,
        agent_cfg,
        preflight_kinds=preflight_kinds,
        skill_ids=skill_ids,
        active_plan=active_plan,
    )
    append_operating_context(
        system_messages,
        loop,
        role=role,
        model=model,
        skill_ids=skill_ids,
        active_room=active_room,
    )
    append_delivery_context(system_messages, loop, speak=speak)
    num_ctx, tool_reserve_chars = _context_limits(
        loop,
        role,
        speak=speak,
        skill_ids=skill_ids,
    )
    exact_cfg = bool(agent_cfg.get("exactness", True))
    exact_need = detect_exactness_need(text)
    ctx = TurnContext(
        text=text,
        role=role,
        speak=speak,
        research_mode=research_mode,
        agent_cfg=agent_cfg,
        available_all=available_all,
        available=set(available),
        visible=set(visible),
        tool_names=set(visible),
        skill_ids=tuple(skill_ids),
        preflight_kinds=list(preflight_kinds),
        active_plan=active_plan,
        sms_draft=sms_draft,
        email_draft=email_draft,
        agenda_draft=agenda_draft,
        skip_sms_draft=skip_sms_draft,
        active_room=active_room,
        numeric_gate=exact_cfg and bool(agent_cfg.get("numeric_gate", True)),
        evidence_gate=exact_cfg and bool(agent_cfg.get("evidence_gate", True)),
        research_dual=exact_cfg and bool(agent_cfg.get("research_dual_hit", True)),
        research_min_sources=max(1, int(agent_cfg.get("research_min_sources", 2))),
        exact_need=exact_need,
        goal=turn_goal,
    )
    # Research role / deep-dive needs web warrants for contingent claims,
    # except weather (Open-Meteo). Jobs used to default to research.
    exact_need = apply_research_web_need(exact_need, research_mode=research_mode, text=text)
    ctx.exact_need = exact_need
    # News / current-events turns should not end on search snippets alone.
    wants_fresh_page = (
        exact_need.needs_web_evidence
        or research_mode
        or (not fallback_only and "web" in skill_ids)
        or ("research" in skill_ids)
        or wants_fresh_page_ask(text)
    )
    # "weather today" must not arm scrape-after-search.
    if exact_need.needs_weather or (
        "weather" in loop._expected_tools
        and "web_search" not in loop._expected_tools
        and "scrape" not in loop._expected_tools
    ):
        wants_fresh_page = False
    # A YouTube / Chrome drive is not a scrape-the-web turn.
    if "browser" in loop._expected_tools:
        wants_fresh_page = False
    # Chat fast-path: skip tool schemas + hold_paint when nothing suggests
    # a tool. Cuts prefill and lets short replies stream (felt TTFT).
    # Must still arm tools for ANY exactness warrant (vision/inbox/…) —
    # calc+web alone left describe/regen turns schema-blind, so the 7B
    # invented captions or claimed it cannot generate images.
    offer_tools = should_offer_tools(
        chat_fast_path=bool(agent_cfg.get("chat_fast_path", True)),
        skill_ids=skill_ids,
        preflight_kinds=preflight_kinds,
        research_mode=research_mode,
        expected_tools=loop._expected_tools,
        exact_need=exact_need,
        wants_fresh_page=wants_fresh_page,
        active_plan=active_plan,
    )
    # Schemas can stay on (prefix cache) without treating chitchat as a
    # tool round. The unmatched web floor is a menu hint, not a scrape.
    expect_tool_round = turn_expects_tool_round(
        skill_ids=plan_ids,
        preflight_kinds=preflight_kinds,
        research_mode=research_mode,
        expected_tools=loop._expected_tools,
        exact_need=exact_need,
        wants_fresh_page=wants_fresh_page,
        active_plan=active_plan,
    )
    ollama_tools = loop.tools.ollama_tools(visible) if offer_tools else []
    if loop._timer is not None and not offer_tools:
        loop._timer.mark("chat_fast_path", tools=0)
    await _attach_tool_schemas_and_history(
        loop,
        ctx,
        system_messages,
        num_ctx=num_ctx,
        tool_reserve_chars=tool_reserve_chars,
        ratio=ratio,
        role=role,
        text=text,
        wants_fresh_page=wants_fresh_page,
        offer_tools=offer_tools,
        expect_tool_round=expect_tool_round,
        ollama_tools=ollama_tools,
    )
    await _prepare_sms_first_move(loop, ctx, text, agent_cfg)
    return ctx
