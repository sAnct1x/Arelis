from __future__ import annotations

import json
import re
from typing import Any

from arelis.config import shipped_num_ctx
from arelis.contacts import contacts_prompt_line
from arelis.core.agenda_complete import (
    complete_agenda_draft,
    looks_like_calendar_create,
    looks_like_calendar_delete,
    looks_like_calendar_read,
)
from arelis.core.agent_loop import (
    _HIDE_WANDER_FOR,
    _SEE_NO_SMS_REDIRECT,
    _SPEAK_TOOL_OUTPUT_CHARS,
    _hide_daily_wander,
    _offer_expected,
    _wants_project_context,
    disconnected_integration_reply,
    now_line,
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
from arelis.core.episodes import episodes_prompt_line
from arelis.core.events import Event, EventType
from arelis.core.image_refs import CAMERA_FRESH_S, latest_camera_image_file
from arelis.core.lessons import format_lessons, select_lessons
from arelis.core.look import LOOK_TOOL_SUBSET, LookTurn, classify_look, frame_sha256
from arelis.core.other_work import looks_like_other_work
from arelis.core.plan_nudge import select_plan
from arelis.core.preflight import (
    detect_intents,
    looks_like_room_create,
    preflight_system_message,
)
from arelis.core.skills import select_skill_ids_detailed
from arelis.core.sms_complete import (
    complete_sms_draft,
    draft_send_sms_args,
    looks_like_closing_chitchat,
    looks_like_contacts_followup,
    looks_like_contacts_utterance,
    looks_like_goals_utterance,
    looks_like_memory_utterance,
    looks_like_stale_sms_skip,
    looks_like_tasks_utterance,
    sms_intent_this_turn,
)
from arelis.core.tool_subset import filter_tool_names, is_research_mode
from arelis.core.turn_context import TurnContext
from arelis.core.turn_telemetry import TurnTimer, turn_telemetry_enabled
from arelis.core.world_state import world_state_prompt_line
from arelis.llm.router import ModelRole
from arelis.memory.store import MemoryStore
from arelis.profile import standing_profile_prompt_line


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
    loop._trace = []
    loop._painted = ""
    # Mutable so mid-turn escalate (W2) can retarget the hot model.
    loop._turn_role: ModelRole = role
    loop._escalated = False
    loop._expected_tools: set[str] = set()
    loop._fail_replan_used = False
    loop._active_plan = None
    loop._receipts: list[dict[str, Any]] = []
    dock_live = callable(loop.config.get("_camera_capture"))
    fresh = latest_camera_image_file(max_age_s=CAMERA_FRESH_S)
    look_intent = classify_look(
        text, dock_live=dock_live, fresh_path=fresh
    )
    loop._look: LookTurn | None = None
    if look_intent is not None:
        loop._look = LookTurn(
            intent=look_intent,
            path=str(look_intent.path or ""),
        )
        if loop._look.path:
            loop._look.sha = frame_sha256(loop._look.path)
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
                            f"Loading `{model}` — previous chat model was "
                            "unloaded so it can fit."
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
    if research_mode:
        loop.max_rounds = max(
            loop._default_max_rounds,
            int(agent_cfg.get("research_max_rounds", 12)),
        )
    else:
        loop.max_rounds = loop._default_max_rounds
    available_all = set(loop.tools.names())
    # A room that named its tools is capped here rather than downstream,
    # because `visible` is recomputed several times below — on escalation,
    # on expected-tool rescue — and each of those reads available_all. Cap
    # the source and every later recompute inherits it. Rooms leave `tools`
    # empty by default: leaning is the feature, caging is opt-in.
    active_room = getattr(loop.config.get("_rooms"), "active", None)
    if active_room is not None and active_room.tools:
        capped = available_all & set(active_room.tools)
        if capped:
            available_all = capped
    room_skills = tuple(active_room.spec.skills) if active_room is not None else ()
    visible = filter_tool_names(
        available_all,
        role=role,
        text=text,
        enabled=bool(agent_cfg.get("research_tool_subset", False)),
        skill_subset=bool(agent_cfg.get("skill_tool_subset", False)),
        history=loop.memory.messages,
        extra_skill_ids=room_skills,
    )
    available = visible
    if loop._look is not None:
        look_tools = {n for n in available_all if n in LOOK_TOOL_SUBSET}
        if look_tools:
            available = look_tools
            visible = look_tools
    if loop._timer is not None and len(visible) < len(available_all):
        loop._timer.mark(
            "tool_subset",
            visible=len(visible),
            available=len(available_all),
        )
    # Static prefix first (persona + telegraph policy) so the front of
    # the prompt is byte-stable across turns. Turn-specific lines trail it,
    # never precede it.
    system_messages = static_system_prefix(loop.persona)
    if (stopped_ask or "").strip():
        from arelis.core.confirm_speech import stopped_ask_note

        hint = stopped_ask_note(stopped_ask)
        if hint:
            system_messages.append({"role": "system", "content": hint})
    # SMS / email / agenda drafts from this turn + recent history.
    # Image-gen / goals / file-write / calendar-create must not revive a
    # stale SMS draft for force unless this turn itself starts with an SMS
    # verb ("text Brian: …").
    other_work = looks_like_other_work(text, loop.memory.messages)
    skip_sms_draft = other_work and not re.match(
        r"(?i)^\s*(?:text|sms|txt|send\s+(?:a\s+)?(?:text|sms|message))\b",
        text or "",
    )
    sms_draft = (
        None
        if skip_sms_draft
        else complete_sms_draft(text, history=loop.memory.messages)
    )
    # A scheduled send, a job edit, a new room or a mailbox mutate skip the
    # email draft even when the words also look like compose — "email me the
    # weather every morning" is a job, not a letter.
    skip_email_draft = other_work and (
        looks_like_scheduled_send(text)
        or looks_like_schedule_manage(text)
        or looks_like_room_create(text)
        or looks_like_mailbox_mutate(text)
        or not looks_like_compose_email(text)
    )
    email_draft = (
        None
        if skip_email_draft
        else complete_email_draft(text, history=loop.memory.messages)
    )
    agenda_draft = complete_agenda_draft(text, history=loop.memory.messages)
    # Deterministic intent nudge — does not call tools or skip confirm.
    preflight_kinds: list[str] = []
    if bool(agent_cfg.get("intent_preflight", True)):
        intent_hints = detect_intents(text, history=loop.memory.messages)
        preflight_kinds = [h.kind for h in intent_hints]
        for hint in intent_hints:
            loop._expected_tools.update(hint.expected_tools)
        if looks_like_memory_utterance(text):
            loop._expected_tools.add("memory")
        if looks_like_contacts_utterance(text) or looks_like_contacts_followup(
            text, loop.memory.messages
        ):
            loop._expected_tools.add("contacts")
        if looks_like_tasks_utterance(text):
            loop._expected_tools.add("tasks")
        if looks_like_goals_utterance(text):
            loop._expected_tools.add("goals")
        if (
            loop._expected_tools & _SEE_NO_SMS_REDIRECT
            and not sms_intent_this_turn(text)
        ):
            loop._expected_tools.discard("send_sms")
        if "image_edit" in loop._expected_tools:
            loop._expected_tools.discard("image")
        if "schedule" in loop._expected_tools:
            loop._expected_tools.discard("send_email")
            loop._expected_tools.discard("weather")
        if "browser" in loop._expected_tools:
            loop._expected_tools.discard("web_search")
        nudge = preflight_system_message(text, history=loop.memory.messages)
        if nudge:
            system_messages.append({"role": "system", "content": nudge})
            if loop._timer is not None and preflight_kinds:
                loop._timer.mark(
                    "preflight",
                    kinds=",".join(preflight_kinds),
                    expected=",".join(sorted(loop._expected_tools)) or "-",
                )
    # Room extras stay on filter_tool_names (keep analyze/cas in reach).
    # Mixing them into skill_ids made select_plan treat the lean as
    # this-turn intent, so an analysis room demanded a CSV on
    # "how do toroids relate to physics?".
    skill_ids, fallback_only = select_skill_ids_detailed(
        text, available_tools=available
    )
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
    # The vision tool used to be hidden behind a keyword list, because
    # looking cost an unload, a cold VL load, and a re-warm. A multimodal
    # chat model sees at the window it is already loaded with (see
    # ModelRouter.run_vision), so the schema is the only cost left and the
    # window has room for it. The list was also a trap: any phrasing outside
    # it — "what is this?" beside a fresh attachment — left the model
    # schema-blind and it invented a caption.
    if loop._expected_tools & _HIDE_WANDER_FOR:
        available = _hide_daily_wander(set(available), loop._expected_tools)
        visible = available
    available = _offer_expected(available, loop._expected_tools, available_all)
    visible = available
    if (
        looks_like_stale_sms_skip(text, loop.memory.messages)
        and "send_sms" not in loop._expected_tools
    ) or loop._look is not None:
        available = set(available)
        available.discard("send_sms")
        available.discard("send_email")
        visible = available
    active_plan = select_plan(
        text, preflight_kinds=preflight_kinds, skill_ids=plan_ids
    )
    if (
        active_plan is not None
        and active_plan.steps
        and not any(s in available_all for s in active_plan.steps)
    ):
        active_plan = None
    disconnected = disconnected_integration_reply(
        expected=loop._expected_tools,
        available=available_all,
        want_sms=bool(
            (sms_draft is not None and sms_draft.complete and not skip_sms_draft)
            or sms_intent_this_turn(text)
        ),
        want_mail=bool(
            (email_draft is not None and email_draft.complete)
            or looks_like_compose_email(text)
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
    plan_msg = active_plan.message if active_plan else None
    if plan_msg:
        system_messages.append({"role": "system", "content": plan_msg})
        if loop._timer is not None:
            loop._timer.mark(
                "plan_nudge",
                skills=",".join(skill_ids) or "-",
                plan=active_plan.id if active_plan else "-",
            )
    # ACE playbook items: short failure lessons matched to this turn.
    if bool(agent_cfg.get("lessons", True)):
        lesson_block = format_lessons(
            select_lessons(
                skill_ids=skill_ids,
                preflight_kinds=preflight_kinds,
                user_text=text,
            )
        )
        if lesson_block:
            system_messages.append({"role": "system", "content": lesson_block})
    workspace = loop.config.get("_workspace")
    if workspace is not None and _wants_project_context(
        role=role,
        skill_ids=skill_ids,
        expected_tools=loop._expected_tools,
    ):
        project_line = workspace.prompt_line()
        if project_line:
            system_messages.append({"role": "system", "content": project_line})
    # A room's purpose rides every turn taken inside it. It sits after the
    # project line because it explains what the project is *for*, and before
    # the standing profile because it is the narrower context of the two.
    if active_room is not None:
        system_messages.append(
            {"role": "system", "content": active_room.prompt_block()}
        )
    location = loop.config.get("_location")
    if location is not None:
        # Injected rather than left to the user_location tool. A 7B model
        # asked about the weather reliably fails to work out that it should
        # first go and find out where the user lives, and one short line
        # costs less than the round trip it prevents.
        place_line = location.prompt_line()
        if place_line:
            system_messages.append({"role": "system", "content": place_line})
    # Hand-edited standing identity/prefs from data/profile.yaml (user:).
    # Kept separate from SQLite facts so a short profile does not depend on
    # the History approve queue.
    profile_line = standing_profile_prompt_line(config=loop.config)
    if profile_line:
        system_messages.append({"role": "system", "content": profile_line})
    # Same idea as location/profile: a 7B will not reliably open the
    # contacts tool before texting, so the live alias list rides every turn.
    contacts_line = contacts_prompt_line()
    if contacts_line:
        system_messages.append({"role": "system", "content": contacts_line})
    facts_line = loop._active_facts_line()
    if facts_line:
        system_messages.append({"role": "system", "content": facts_line})
    store = loop.memory.sink if isinstance(loop.memory.sink, MemoryStore) else None
    if store is not None:
        episode_line = episodes_prompt_line(store, limit=3)
        if episode_line:
            system_messages.append({"role": "system", "content": episode_line})
    world_line = world_state_prompt_line(
        loop.config,
        role=role,
        model=model,
        workspace=loop.config.get("_workspace"),
        store=store,
    )
    if world_line:
        system_messages.append({"role": "system", "content": world_line})
    if speak:
        # Conversation mode plays the answer aloud. Bias toward short
        # spoken replies unless the user asked for detail — but still call
        # tools; the confirm card is how sends actually happen.
        system_messages.append(
            {
                "role": "system",
                "content": (
                    "You are speaking aloud in conversation mode. Prefer "
                    "1-3 short sentences unless the user asked for detail, "
                    "code, steps, or a list. When they asked you to do "
                    "something (text, email, write, search, weather, "
                    "scrape, remember), call the tool first — do not only "
                    "talk about doing it, and do not ask permission in chat. "
                    "send_sms and send_email open a confirm card; that is "
                    "how the message is approved."
                ),
            }
        )
    # The clock goes last of the system lines because it is the only one that
    # changes on its own. It used to sit directly behind the static prefix,
    # where every minute rollover re-prefilled the focus card, the preflight
    # nudge, the facts and the world state behind it. Nothing about the
    # persona or the policy depends on the time, and putting the freshest
    # fact nearest the question does the model no harm.
    from arelis.talk_language import reply_instruction

    lang_note = reply_instruction(loop.config.get("_reply_language"))
    if lang_note:
        system_messages.append({"role": "system", "content": lang_note})
    system_messages.append({"role": "system", "content": now_line()})
    # Pin system messages. Ollama drops overflow from the front, so without
    # this the persona and tool policy are the first things a long session
    # loses, and every later answer is given by a model with no identity.
    ollama_cfg = loop.config.get("ollama") or {}
    num_ctx = int(ollama_cfg.get("num_ctx") or shipped_num_ctx())
    if role == "research" and ollama_cfg.get("research_num_ctx"):
        num_ctx = int(ollama_cfg["research_num_ctx"])
    # Sticky for the turn so mid-escalate does not shrink under a built prompt.
    loop._turn_num_ctx = num_ctx
    tool_reserve_chars = (
        min(loop.tool_output_chars, _SPEAK_TOOL_OUTPUT_CHARS)
        if speak
        else loop.tool_output_chars
    )
    # Conversation small-talk: do not reserve a scrape slab when nothing
    # in this turn asked for a tool. That reserve was eating the last turn.
    if speak and not loop._expected_tools and not skill_ids:
        tool_reserve_chars = 0
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
        research_min_sources=max(
            1, int(agent_cfg.get("research_min_sources", 2))
        ),
        exact_need=exact_need,
    )
    # Containers stay aliased so each round can append without a ctx.
    # prefix on every line. Scalars that get rebound must go through ctx.
    tool_names = ctx.tool_names
    # Research role / deep-dive needs web warrants for contingent claims,
    # except weather (Open-Meteo). Jobs used to default to research.
    exact_need = apply_research_web_need(
        exact_need, research_mode=research_mode
    )
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

    # The budget is built here, after the tool array exists, because the
    # schemas are prompt and have to be paid for before history is offered
    # what is left. A fast-path turn carries no schemas and gets the room.
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

    # A complete SMS draft is a deterministic first move, so the Allow card
    # is raised before the model gets a round. Tool-bearing rounds hold the
    # answer back (hold_paint), which on a spoken "text my wife …" meant a
    # blank thread for as long as the 7B took to decide: the operator read
    # that as hung, pressed Esc to clear it, and the send died with the turn.
    # Allow is still the only thing that sends, and the model still writes
    # the reply on the round after the tool result.
    if (
        "send_sms" in loop._expected_tools
        and "send_sms" not in available_all
        and sms_intent_this_turn(text)
    ):
        await loop._explain_missing_send_sms(available_all)
    elif sms_draft is not None and sms_draft.complete and not skip_sms_draft:
        if "send_sms" not in tool_names:
            if sms_intent_this_turn(text):
                await loop._explain_missing_send_sms(available_all)
        elif bool(agent_cfg.get("sms_force_call", True)) and bool(
            agent_cfg.get("sms_preinject", True)
        ):
            ctx.sms_preinject = draft_send_sms_args(sms_draft)

    return ctx
