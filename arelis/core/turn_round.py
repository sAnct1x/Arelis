"""One model/tool round. AgentLoop._run_round is a lazy delegate.

``run_round`` coordinates: escalate, stream (or preinject), then
``apply_no_call_path`` (nudge / inject / finish) and ``dispatch_calls``
(confirm / execute) in turn_dispatch. Rebound locals ride on a
SimpleNamespace so early returns still write back. Helpers stay defined
on agent_loop so existing tests that import them do not move.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from types import SimpleNamespace
from typing import Any

from arelis.core.agent_loop import (
    _FILE_ANSWER_TOOLS,
    _HIDE_WANDER_FOR,
    _JS_SHELL_BROWSER_NOTICE,
    _MALFORMED_CALL_NOTICE,
    _MAX_TOOL_NUDGES,
    _SCRAPE_AFTER_SEARCH_NOTICE,
    _WEB_TOOLS,
    FORCE_GATE_KINDS,
    LOOK_TOOL_SUBSET,
    Event,
    EventType,
    _answer_has_quote_span,
    _exactness_finish_refuse,
    _hide_daily_wander,
    _is_ollama_object_400,
    _native_tool_call,
    _normalize_ollama_messages,
    _offer_expected,
    _StoppedError,
    _tool_followup_fallback,
    agenda_force_call_notice,
    agenda_force_close_notice,
    agenda_force_delete_notice,
    agenda_force_open_notice,
    agenda_force_read_notice,
    agenda_read_action,
    answer_looks_like_ack_only,
    answer_looks_like_refusal,
    apply_force_gates,
    catalog_force_notice,
    classify_ollama_failure,
    contact_who_from_text,
    draft_agenda_create_args,
    draft_agenda_delete_args,
    draft_browser_args,
    draft_catalog_args,
    draft_inbox_mutate_args,
    draft_rooms_create_args,
    draft_send_email_args,
    draft_send_sms_args,
    draft_signin_click_args,
    draft_weather_args,
    dual_hit_notice,
    email_force_call_notice,
    evidence_force_notice,
    extract_native_tool_calls,
    file_answer_force_notice,
    fill_vision_args,
    filter_tool_names,
    image_force_call_notice,
    is_research_mode,
    is_vram_failure,
    last_store_ids_from_context,
    local_store_inject_args,
    looks_like_bare_confirm,
    looks_like_browser_click_signin,
    looks_like_browser_or_url,
    looks_like_calendar_close,
    looks_like_calendar_delete,
    looks_like_calendar_open,
    looks_like_calendar_read,
    looks_like_contacts_followup,
    looks_like_contacts_utterance,
    looks_like_goals_utterance,
    looks_like_image_gen,
    looks_like_mailbox_mutate,
    looks_like_memory_utterance,
    looks_like_room_create,
    looks_like_schedule_manage,
    looks_like_scheduled_send,
    looks_like_stale_sms_skip,
    looks_like_tasks_utterance,
    match_tile_intent,
    next_look_call,
    parse_attachments_from_turn,
    parse_fallback_payload,
    plan_progress_notice,
    quote_first_notice,
    rewrite_browser_calls,
    rewrite_schedule_calls,
    sms_force_call_notice,
    split_attachments_turn,
    strip_thinking_text,
    tile_tool_args,
    unsupported_exactness_reply,
    wants_image_edit,
    weather_force_notice,
    weather_places_missing,
)
from arelis.core.turn_context import TurnContext
from arelis.core.turn_dispatch import dispatch_calls


def _round_scratch(
    *,
    text: Any,
    role: Any,
    agent_cfg: Any,
    available_all: Any,
    available: Any,
    visible: Any,
    tool_names: Any,
    sources: Any,
    ledger: Any,
    fail_counts: Any,
    skip_counts: Any,
    web_search_ok: Any,
    page_ok: Any,
    sms_sent: Any,
    agenda_created: Any,
    weather_ok_places: Any,
    weather_days_retried: Any,
    numeric_gate: Any,
    evidence_gate: Any,
    research_dual: Any,
    research_min_sources: Any,
    exact_need: Any,
    offer_tools: Any,
    ollama_tools: Any,
    messages: Any,
    sms_preinject: Any,
    sms_draft: Any,
    email_draft: Any,
    agenda_draft: Any,
    research_mode: Any,
    preflight_kinds: Any,
    wants_fresh_page: Any,
    active_room: Any,
    content: Any,
    streamed: Any,
    calls: Any,
    tool_calls: Any,
    round_ms: Any,
    model: Any,
) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        role=role,
        agent_cfg=agent_cfg,
        available_all=available_all,
        available=available,
        visible=visible,
        tool_names=tool_names,
        sources=sources,
        ledger=ledger,
        fail_counts=fail_counts,
        skip_counts=skip_counts,
        web_search_ok=web_search_ok,
        page_ok=page_ok,
        sms_sent=sms_sent,
        agenda_created=agenda_created,
        weather_ok_places=weather_ok_places,
        weather_days_retried=weather_days_retried,
        numeric_gate=numeric_gate,
        evidence_gate=evidence_gate,
        research_dual=research_dual,
        research_min_sources=research_min_sources,
        exact_need=exact_need,
        offer_tools=offer_tools,
        ollama_tools=ollama_tools,
        messages=messages,
        sms_preinject=sms_preinject,
        sms_draft=sms_draft,
        email_draft=email_draft,
        agenda_draft=agenda_draft,
        research_mode=research_mode,
        preflight_kinds=preflight_kinds,
        wants_fresh_page=wants_fresh_page,
        active_room=active_room,
        content=content,
        streamed=streamed,
        calls=calls,
        tool_calls=tool_calls,
        round_ms=round_ms,
        model=model,
    )


def _pull_round(r: SimpleNamespace) -> tuple[Any, ...]:
    return (
        r.available,
        r.visible,
        r.tool_names,
        r.ollama_tools,
        r.offer_tools,
        r.research_mode,
        r.sms_preinject,
        r.exact_need,
        r.calls,
        r.tool_calls,
        r.content,
        r.streamed,
        r.round_ms,
        r.role,
    )


async def apply_no_call_path(
    loop: Any, ctx: TurnContext, r: SimpleNamespace, round_i: int
) -> bool | None:
    """Nudge, inject, or finish when this round has no tool call.

    True ends the turn. False asks another round. None means dispatch
    should run (model already called, or a force-inject filled ``r.calls``).
    """
    text = r.text
    role = r.role
    agent_cfg = r.agent_cfg
    available_all = r.available_all
    available = r.available
    visible = r.visible
    tool_names = r.tool_names
    sources = r.sources
    ledger = r.ledger
    fail_counts = r.fail_counts
    skip_counts = r.skip_counts
    web_search_ok = r.web_search_ok
    page_ok = r.page_ok
    sms_sent = r.sms_sent
    agenda_created = r.agenda_created
    weather_ok_places = r.weather_ok_places
    weather_days_retried = r.weather_days_retried
    numeric_gate = r.numeric_gate
    evidence_gate = r.evidence_gate
    research_dual = r.research_dual
    research_min_sources = r.research_min_sources
    exact_need = r.exact_need
    offer_tools = r.offer_tools
    ollama_tools = r.ollama_tools
    messages = r.messages
    sms_preinject = r.sms_preinject
    sms_draft = r.sms_draft
    email_draft = r.email_draft
    agenda_draft = r.agenda_draft
    research_mode = r.research_mode
    preflight_kinds = r.preflight_kinds
    wants_fresh_page = r.wants_fresh_page
    active_room = r.active_room
    content = r.content
    streamed = r.streamed
    calls = r.calls
    tool_calls = r.tool_calls
    round_ms = r.round_ms
    model = r.model
    try:
        if not calls:
            # The model wrote a call as prose instead of making one, so the
            # strict parser refused it. Executing it anyway is the hole
            # strict mode exists to close, and shipping it means the user
            # gets raw JSON as their answer and no tool ever runs. Neither
            # is acceptable, so ask again and say what went wrong.
            stray = (
                parse_fallback_payload(content, strict=False)
                if loop.json_fallback and not ctx.fallback_mode
                else None
            )
            if stray and stray["kind"] == "tool" and ctx.nudges < _MAX_TOOL_NUDGES:
                ctx.nudges += 1
                await loop._retract()
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": _MALFORMED_CALL_NOTICE.format(
                            tool=stray["name"],
                            args=json.dumps(stray["args"], default=str),
                        ),
                    }
                )
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "tool call written as prose; asking for a real one"},
                    )
                )
                return False

            if not content and not ctx.fallback_mode:
                # Qwen3.5 often puts the wrap-up in thinking and leaves
                # chat content empty. Native calling still worked — a tool
                # already ran — so do not enter the sticky-note protocol
                # and do not ship the "empty reply / model unloaded" notice.
                # Tools may already be stripped (agenda/SMS/email wrap-up).
                if ctx.last_ok_tool_out:
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    "empty after tool; answering from result"
                                )
                            },
                        )
                    )
                    await loop._finish(
                        _tool_followup_fallback(ctx.last_ok_tool_out, ctx.last_ok_tool_name),
                        sources,
                        streamed="",
                    )
                    return True
                if ollama_tools and loop.json_fallback:
                    # First round still blank with no tools yet? JSON fallback.
                    await loop._retract()
                    ctx.fallback_mode = True
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "empty tool response; JSON fallback"},
                        )
                    )
                    return False
            # Complete SMS draft but recipients remain — nudge once, then inject.
            sms_remaining = []
            if sms_draft is not None and sms_draft.complete:
                sent_l = {s.lower() for s in sms_sent}
                sms_remaining = [
                    a
                    for a in sms_draft.resolved_aliases
                    if a and a.lower() not in sent_l
                ]
                if not sms_remaining and not sms_sent and sms_draft.tool_to:
                    sms_remaining = [sms_draft.tool_to]
            if (
                bool(agent_cfg.get("sms_force_call", True))
                and sms_draft is not None
                and sms_draft.complete
                and sms_remaining
                and "send_sms" in tool_names
            ):
                if ctx.sms_nudge_used < 1:
                    ctx.sms_nudge_used += 1
                    await loop._retract()
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": sms_force_call_notice(
                                sms_draft, already_sent=sms_sent
                            ),
                        }
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    "SMS draft ready; asking for a real "
                                    "send_sms call"
                                )
                            },
                        )
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "exactness", gate="sms_force", action="nudge"
                        )
                    return False
                # Nudge ignored — inject drafted send_sms (Allow still required).
                # Do not re-inject after a failed send (same bad card twice).
                if not ctx.sms_failed:
                    inj = draft_send_sms_args(
                        sms_draft, already_sent=sms_sent
                    )
                    calls = [("send_sms", inj)]
                    tool_calls = [_native_tool_call("send_sms", inj)]
                    await loop._retract()
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  send_sms from draft"},
                        )
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "exactness", gate="sms_force", action="inject"
                        )
            # Complete email draft — nudge once, then inject.
            elif (
                bool(agent_cfg.get("email_force_call", True))
                and email_draft is not None
                and email_draft.complete
                and "send_email" in tool_names
                and "send_email" not in loop.tools_used
            ):
                if ctx.email_nudge_used < 1:
                    ctx.email_nudge_used += 1
                    await loop._retract()
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": email_force_call_notice(email_draft),
                        }
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    "email draft ready; asking for a real "
                                    "send_email call"
                                )
                            },
                        )
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "exactness", gate="email_force", action="nudge"
                        )
                    return False
                inj = draft_send_email_args(email_draft)
                calls = [("send_email", inj)]
                tool_calls = [_native_tool_call("send_email", inj)]
                await loop._retract()
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "inject  send_email from draft"},
                    )
                )
                if loop._timer is not None:
                    loop._timer.mark(
                        "exactness", gate="email_force", action="inject"
                    )
            elif (
                looks_like_mailbox_mutate(text)
                and "inbox" in tool_names
                and not ctx.inbox_mutated_ok
            ):
                inbox = loop.tools.get("inbox")
                hits = getattr(inbox, "last_hits", None) if inbox is not None else None
                inj = draft_inbox_mutate_args(
                    text,
                    last_hits=hits if isinstance(hits, list) else None,
                )
                action = str(inj.get("action") or "").lower()
                if action == "search" and "inbox" in loop.tools_used:
                    inj = {}
                if inj:
                    calls = [("inbox", inj)]
                    tool_calls = [_native_tool_call("inbox", inj)]
                    await loop._retract()
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  inbox from intent"},
                        )
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "exactness", gate="inbox_mutate", action="inject"
                        )
            # Complete agenda create — force on missing create success, not
            # any agenda list/today call.
            elif (
                bool(agent_cfg.get("agenda_force_call", True))
                and agenda_draft is not None
                and agenda_draft.complete
                and "agenda" in tool_names
                and not ctx.agenda_create_ok
            ):
                if ctx.agenda_nudge_used < 1:
                    ctx.agenda_nudge_used += 1
                    await loop._retract()
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": agenda_force_call_notice(agenda_draft),
                        }
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    "agenda draft ready; asking for a real "
                                    "agenda create call"
                                )
                            },
                        )
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "exactness", gate="agenda_force", action="nudge"
                        )
                    return False
                inj = draft_agenda_create_args(agenda_draft)
                calls = [("agenda", inj)]
                tool_calls = [_native_tool_call("agenda", inj)]
                await loop._retract()
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "inject  agenda create from draft"},
                    )
                )
                if loop._timer is not None:
                    loop._timer.mark(
                        "exactness", gate="agenda_force", action="inject"
                    )
            elif (
                bool(agent_cfg.get("agenda_force_call", True))
                and looks_like_calendar_delete(text)
                and "agenda" in tool_names
                and "agenda" not in loop.tools_used
                and "agenda" in loop._expected_tools
            ):
                if ctx.agenda_nudge_used < 1:
                    ctx.agenda_nudge_used += 1
                    await loop._retract()
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": agenda_force_delete_notice(),
                        }
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    "agenda delete ready; asking for a real "
                                    "agenda delete call"
                                )
                            },
                        )
                    )
                    return False
                # Inject delete by title/time; only use an id the user pasted.
                inj = draft_agenda_delete_args(
                    text,
                    receipts=loop._receipts,
                    history=loop.memory.messages,
                )
                calls = [("agenda", inj)]
                tool_calls = [_native_tool_call("agenda", inj)]
                await loop._retract()
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "inject  agenda delete"},
                    )
                )
            elif (
                bool(agent_cfg.get("agenda_force_call", True))
                and looks_like_calendar_close(text)
                and "agenda" in tool_names
                and "agenda" not in loop.tools_used
            ):
                if ctx.agenda_nudge_used < 1:
                    ctx.agenda_nudge_used += 1
                    await loop._retract()
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": agenda_force_close_notice(),
                        }
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    "agenda close ready; asking for a real "
                                    "agenda close call"
                                )
                            },
                        )
                    )
                    return False
                inj = {"action": "close"}
                calls = [("agenda", inj)]
                tool_calls = [_native_tool_call("agenda", inj)]
                await loop._retract()
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "inject  agenda close from intent"},
                    )
                )
            elif (
                bool(agent_cfg.get("agenda_force_call", True))
                and looks_like_calendar_open(text)
                and "agenda" in tool_names
                and "agenda" not in loop.tools_used
            ):
                if ctx.agenda_nudge_used < 1:
                    ctx.agenda_nudge_used += 1
                    await loop._retract()
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": agenda_force_open_notice(),
                        }
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    "agenda open ready; asking for a real "
                                    "agenda open call"
                                )
                            },
                        )
                    )
                    return False
                inj = {"action": "open"}
                calls = [("agenda", inj)]
                tool_calls = [_native_tool_call("agenda", inj)]
                await loop._retract()
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "inject  agenda open from intent"},
                    )
                )
            elif (
                match_tile_intent(text)
                and "tile" in tool_names
                and "tile" not in loop.tools_used
            ):
                from arelis.tools.tile import TileTool

                hit = match_tile_intent(text)
                calendar_uses_agenda = (
                    hit is not None
                    and hit[1] == "calendar"
                    and "agenda" in tool_names
                )
                inj = (
                    None
                    if calendar_uses_agenda
                    else tile_tool_args(text, last_name=TileTool.last_name)
                )
                if inj:
                    calls = [("tile", inj)]
                    tool_calls = [_native_tool_call("tile", inj)]
                    await loop._retract()
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  tile from intent"},
                        )
                    )
            elif (
                bool(agent_cfg.get("agenda_force_call", True))
                and looks_like_calendar_read(text)
                and "agenda" in tool_names
                and "agenda" not in loop.tools_used
                and (
                    "agenda" in loop._expected_tools
                    or exact_need.needs_agenda
                )
            ):
                if ctx.agenda_nudge_used < 1:
                    ctx.agenda_nudge_used += 1
                    await loop._retract()
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": agenda_force_read_notice(
                                agenda_read_action(text)
                            ),
                        }
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    "agenda read ready; asking for a real "
                                    "agenda list call"
                                )
                            },
                        )
                    )
                    return False
                inj = {"action": agenda_read_action(text)}
                calls = [("agenda", inj)]
                tool_calls = [_native_tool_call("agenda", inj)]
                await loop._retract()
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "inject  agenda read from intent"},
                    )
                )
            elif (
                bool(agent_cfg.get("image_force_call", True))
                and "image_edit" not in loop._expected_tools
                and "image_edit" not in preflight_kinds
                and not wants_image_edit(
                    split_attachments_turn(text)[1] or text
                )
                and "image" in loop._expected_tools
                and "image" not in loop.tools_used
                and not ctx.image_attempted
                and "image" in tool_names
                and (
                    looks_like_image_gen(text)
                    or "image_gen" in preflight_kinds
                )
            ):
                if ctx.image_nudge_used < 1:
                    ctx.image_nudge_used += 1
                    await loop._retract()
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": image_force_call_notice(prompt_hint=text),
                        }
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    "image ask ready; asking for a real image call"
                                )
                            },
                        )
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "exactness", gate="image_force", action="nudge"
                        )
                    return False
                inj = {"prompt": text.strip()[:300]}
                calls = [("image", inj)]
                tool_calls = [_native_tool_call("image", inj)]
                await loop._retract()
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "inject  image from intent"},
                    )
                )
            elif (
                bool(agent_cfg.get("image_force_call", True))
                and "image_edit" in loop._expected_tools
                and "image_edit" not in loop.tools_used
                and "image_edit" in tool_names
                and (
                    wants_image_edit(split_attachments_turn(text)[1] or text)
                    or "image_edit" in preflight_kinds
                )
            ):
                ask = split_attachments_turn(text)[1] or text
                rows = parse_attachments_from_turn(text)
                path = str(rows[0].get("path") or "") if rows else ""
                if path:
                    inj_edit: dict[str, Any] = {"path": path}
                    if re.search(r"(?i)youtube|\bthumbnail\b", ask):
                        inj_edit["preset"] = "youtube_thumbnail"
                    if re.search(r"(?i)vibrant|vibrance|saturat", ask):
                        inj_edit["vibrance"] = 1.3
                    size = re.search(
                        r"(?i)(\d{2,5})\s*(?:x|\u00d7|by)\s*(\d{2,5})",
                        ask,
                    )
                    if size:
                        inj_edit["width"] = int(size.group(1))
                        inj_edit["height"] = int(size.group(2))
                        inj_edit.pop("preset", None)
                    calls = [("image_edit", inj_edit)]
                    tool_calls = [_native_tool_call("image_edit", inj_edit)]
                    await loop._retract()
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  image_edit from intent"},
                        )
                    )
            elif loop._look is not None:
                nxt = next_look_call(
                    loop._look.intent,
                    path=loop._look.path,
                    camera_done=loop._look.camera_snaps > 0,
                    ocr_done=loop._look.ocr_done,
                    vision_done=loop._look.vision_done,
                    deferral=loop._look.deferral,
                )
                if nxt is not None:
                    inj_name, inj = nxt
                    if inj_name in tool_names:
                        calls = [(inj_name, inj)]
                        tool_calls = [_native_tool_call(inj_name, inj)]
                        await loop._retract()
                        await loop.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        f"inject  look {loop._look.intent.act} "
                                        f"{inj_name}"
                                    )
                                },
                            )
                        )
                        if loop._timer is not None:
                            loop._timer.mark(
                                "look",
                                act=loop._look.intent.act,
                                tool=inj_name,
                                action="inject",
                            )
            elif (
                bool(agent_cfg.get("vision_force_call", True))
                and "vision" in loop._expected_tools
                and "vision" not in loop.tools_used
                and "vision" in tool_names
            ):
                filled = fill_vision_args(
                    {},
                    history=loop.memory.messages,
                    user_text=text,
                )
                path = str(filled.get("path") or "")
                from arelis.attachments import attachment_kinds_from_turn

                attached = "image" in attachment_kinds_from_turn(text)
                label = "attached" if attached else "generated"
                if ctx.vision_nudge_used < 1:
                    ctx.vision_nudge_used += 1
                    await loop._retract()
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"Call vision now with the {label} image path"
                                + (f" path={path}" if path else "")
                                + ". Do not web_search."
                            ),
                        }
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "vision ask ready; asking for vision call"},
                        )
                    )
                    return False
                if path:
                    inj = {"path": path}
                    calls = [("vision", inj)]
                    tool_calls = [_native_tool_call("vision", inj)]
                    await loop._retract()
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  vision from intent"},
                        )
                    )
            elif (
                bool(agent_cfg.get("weather_force_call", True))
                and exact_need.needs_weather
                and not looks_like_scheduled_send(text)
                and not looks_like_schedule_manage(text)
                and not ctx.schedule_managed_ok
                and weather_places_missing(text, weather_ok_places)
                and "weather" in tool_names
            ):
                if ctx.weather_nudge_used < 1 and not weather_ok_places:
                    ctx.weather_nudge_used += 1
                    await loop._retract()
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {"role": "user", "content": weather_force_notice()}
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    "weather ask; asking for a real weather call"
                                )
                            },
                        )
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "exactness", gate="weather_force", action="nudge"
                        )
                    return False
                inj = draft_weather_args(text)
                missing = weather_places_missing(text, weather_ok_places)
                if missing:
                    if missing[0]:
                        inj["place"] = missing[0]
                    else:
                        inj.pop("place", None)
                calls = [("weather", inj)]
                tool_calls = [_native_tool_call("weather", inj)]
                await loop._retract()
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "inject  weather from intent"},
                    )
                )
                if loop._timer is not None:
                    loop._timer.mark(
                        "exactness", gate="weather_force", action="inject"
                    )
            elif (
                not (content or "").strip()
                and numeric_gate
                and exact_need.needs_catalog
                and not ledger.has_ok("catalog")
                and "catalog" in tool_names
                and "catalog" not in loop.tools_used
            ):
                if not ctx.catalog_nudge_used:
                    ctx.catalog_nudge_used = True
                    await loop._retract()
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {"role": "user", "content": catalog_force_notice()}
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    "catalog ask; asking for a real catalog call"
                                )
                            },
                        )
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "exactness", gate="catalog_force", action="nudge"
                        )
                    return False
                inj = draft_catalog_args(text)
                calls = [("catalog", inj)]
                tool_calls = [_native_tool_call("catalog", inj)]
                await loop._retract()
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "inject  catalog from intent"},
                    )
                )
                if loop._timer is not None:
                    loop._timer.mark(
                        "exactness", gate="catalog_force", action="inject"
                    )
            elif (
                bool(agent_cfg.get("tasks_force_call", True))
                and (
                    exact_need.needs_tasks
                    or "tasks" in loop._expected_tools
                    or looks_like_tasks_utterance(text)
                )
                and "tasks" not in loop.tools_used
                and "tasks" in tool_names
            ):
                inj = local_store_inject_args(
                    "tasks",
                    text,
                    receipts=loop._receipts,
                    history=loop.memory.messages,
                )
                calls = [("tasks", inj)]
                tool_calls = [_native_tool_call("tasks", inj)]
                await loop._retract()
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "inject  tasks from intent"},
                    )
                )
                if loop._timer is not None:
                    loop._timer.mark(
                        "exactness", gate="tasks_force", action="inject"
                    )
            elif (
                bool(agent_cfg.get("goals_force_call", True))
                and (
                    exact_need.needs_goals
                    or "goals" in loop._expected_tools
                    or looks_like_goals_utterance(text)
                )
                and "goals" not in loop.tools_used
                and "goals" in tool_names
            ):
                ids = last_store_ids_from_context(
                    loop.memory.messages, loop._receipts
                )
                if (
                    re.search(r"(?i)\b(?:both|all)\b", text or "")
                    and len(ids) > 1
                ):
                    calls = [
                        ("goals", {"action": "remove", "id": gid})
                        for gid in ids
                    ]
                    tool_calls = [
                        _native_tool_call("goals", {"action": "remove", "id": gid})
                        for gid in ids
                    ]
                else:
                    inj = local_store_inject_args(
                        "goals",
                        text,
                        receipts=loop._receipts,
                        history=loop.memory.messages,
                    )
                    calls = [("goals", inj)]
                    tool_calls = [_native_tool_call("goals", inj)]
                await loop._retract()
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "inject  goals from intent"},
                    )
                )
                if loop._timer is not None:
                    loop._timer.mark(
                        "exactness", gate="goals_force", action="inject"
                    )
            elif (
                (
                    "memory" in loop._expected_tools
                    or looks_like_memory_utterance(text)
                )
                and "memory" not in loop.tools_used
                and "memory" in tool_names
            ):
                if ctx.memory_nudge_used < 1:
                    ctx.memory_nudge_used += 1
                    await loop._retract()
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Call the memory tool now. Use action=remember "
                                "or action=forget with the fact quoted from "
                                "the user. Do not call recall instead, and "
                                "do not open a browser."
                            ),
                        }
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "memory ask; asking for a real memory call"},
                        )
                    )
                    return False
                inj = local_store_inject_args("memory", text)
                calls = [("memory", inj)]
                tool_calls = [_native_tool_call("memory", inj)]
                await loop._retract()
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "inject  memory from intent"},
                    )
                )
            elif (
                (
                    "contacts" in loop._expected_tools
                    or looks_like_contacts_utterance(text)
                    or looks_like_contacts_followup(text, loop.memory.messages)
                )
                and "contacts" not in loop.tools_used
                and "contacts" in tool_names
            ):
                who = contact_who_from_text(text)
                if not who:
                    for item in reversed(loop.memory.messages[-8:]):
                        role = getattr(item, "role", "")
                        content_h = getattr(item, "content", "") or ""
                        if role == "user":
                            who = contact_who_from_text(str(content_h))
                            if who:
                                break
                inj = {"action": "get", "who": who or "wife"}
                calls = [("contacts", inj)]
                tool_calls = [_native_tool_call("contacts", inj)]
                await loop._retract()
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "inject  contacts from intent"},
                    )
                )
            elif (
                (
                    "browser" in loop._expected_tools
                    or looks_like_browser_or_url(text)
                )
                and not looks_like_calendar_open(text)
                and not looks_like_calendar_close(text)
                and not match_tile_intent(text)
                and "browser" not in loop.tools_used
                and "browser" in tool_names
            ):
                inj = draft_browser_args(text)
                calls = [("browser", inj)]
                tool_calls = [_native_tool_call("browser", inj)]
                await loop._retract()
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "inject  browser from intent"},
                    )
                )
            elif (
                looks_like_browser_click_signin(text)
                and "browser" in loop.tools_used
                and not ctx.browser_clicked
                and "browser" in tool_names
            ):
                inj = draft_signin_click_args(ctx.last_browser_snapshot)
                if inj:
                    calls = [("browser", inj)]
                    tool_calls = [_native_tool_call("browser", inj)]
                    await loop._retract()
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    "inject  browser click Sign in "
                                    f"ref={inj.get('ref')}"
                                )
                            },
                        )
                    )
            elif (
                (
                    "rooms" in loop._expected_tools
                    or looks_like_room_create(text)
                )
                and "rooms" not in loop.tools_used
                and "rooms" in tool_names
            ):
                inj = draft_rooms_create_args(text)
                calls = [("rooms", inj)]
                tool_calls = [_native_tool_call("rooms", inj)]
                await loop._retract()
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "inject  rooms create from intent"},
                    )
                )

            before_sched = list(calls)
            stripped_run_now = looks_like_bare_confirm(text) and any(
                n == "schedule"
                and str((a or {}).get("action") or "").lower() == "run_now"
                for n, a in before_sched
            )
            calls = rewrite_schedule_calls(
                text,
                calls,
                schedule_used="schedule" in loop.tools_used,
                schedule_available="schedule" in tool_names,
            )
            if calls != before_sched:
                tool_calls = [
                    _native_tool_call(n, a) for n, a in calls
                ]
                if not before_sched and calls:
                    await loop._retract()
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  schedule briefing from intent"},
                        )
                    )
            if stripped_run_now and not calls:
                await loop._finish(
                    "The job is already scheduled. It will run at the time "
                    "you set — no need to fire it now."
                )
                return True

            before_browser = list(calls)
            calls = rewrite_browser_calls(calls, text=text)
            if calls != before_browser:
                tool_calls = [
                    _native_tool_call(n, a) for n, a in calls
                ]
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "rewrite  invented browser action → snapshot"},
                    )
                )

            if not calls:
                # Searched but never opened a page — one forced scrape round.
                if (
                    bool(agent_cfg.get("scrape_after_search", True))
                    and wants_fresh_page
                    and not ctx.scrape_nudge_used
                    and "web_search" in loop.tools_used
                    and "browser" not in loop._expected_tools
                    and "browser" not in loop.tools_used
                    and not (loop.tools_used & _WEB_TOOLS)
                    and ("scrape" in tool_names or "research_report" in tool_names)
                ):
                    ctx.scrape_nudge_used = True
                    await loop._retract()
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {"role": "user", "content": _SCRAPE_AFTER_SEARCH_NOTICE}
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    "search without scrape; asking for a page read"
                                )
                            },
                        )
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "exactness",
                            gate="scrape_after_search",
                            action="nudge",
                        )
                    return False
                if (
                    bool(agent_cfg.get("browser_after_js_shell", True))
                    and ctx.js_shell_url
                    and not ctx.js_shell_nudge_used
                    and "browser" in available_all
                    and "browser" not in loop.tools_used
                    and not (loop._expected_tools & {"weather", "send_sms", "send_email"})
                ):
                    ctx.js_shell_nudge_used = True
                    # Web-skill turns do not offer browser up front (or she
                    # skips scrape). Offer it now so the nudge can land.
                    if "browser" not in tool_names:
                        visible = set(visible) | {"browser"}
                        available = set(available) | {"browser"}
                        ctx.tool_names.clear()
                        ctx.tool_names.update(visible)
                        tool_names = ctx.tool_names
                        if offer_tools:
                            ollama_tools = loop.tools.ollama_tools(visible)
                    await loop._retract()
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": _JS_SHELL_BROWSER_NOTICE.format(
                                url=ctx.js_shell_url
                            ),
                        }
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    "js shell; asking to open the page in her window"
                                )
                            },
                        )
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "exactness",
                            gate="browser_after_js_shell",
                            action="nudge",
                        )
                    return False
                # Multi-step plan: earlier tools ran but a later step was skipped.
                if (
                    bool(agent_cfg.get("plan_progress", True))
                    and loop._active_plan is not None
                    and not ctx.plan_progress_used
                    and not answer_looks_like_refusal(content)
                ):
                    progress = plan_progress_notice(
                        loop._active_plan,
                        loop.tools_used,
                        available_tools=tool_names,
                    )
                    if progress:
                        ctx.plan_progress_used = True
                        await loop._retract()
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user", "content": progress})
                        await loop.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        f"plan_progress  {loop._active_plan.id}"
                                    )
                                },
                            )
                        )
                        if loop._timer is not None:
                            loop._timer.mark(
                                "plan_progress",
                                plan=loop._active_plan.id,
                            )
                        return False
                if await apply_force_gates(
                    loop,
                    ctx,
                    content,
                    refused=answer_looks_like_refusal(content),
                ):
                    return False
                # Exactness: contingent fact without a matching warrant.
                if (
                    evidence_gate
                    and exact_need.kinds
                    and not ctx.evidence_nudge_used
                    and not answer_looks_like_refusal(content)
                ):
                    missing = ledger.missing_kinds(exact_need.kinds)
                    # Math/weather have dedicated forces above.
                    missing = [
                        k for k in missing if k not in FORCE_GATE_KINDS
                    ]
                    if missing:
                        ctx.evidence_nudge_used = True
                        await loop._retract()
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {"role": "user", "content": evidence_force_notice()}
                        )
                        await loop.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        "phase=verify missing-warrants "
                                        + ",".join(missing)
                                    )
                                },
                            )
                        )
                        if loop._timer is not None:
                            loop._timer.mark(
                                "verify",
                                gate="evidence",
                                missing=",".join(missing),
                            )
                        return False
                # File read succeeded but the model only acknowledged ("Got it,
                # I'll keep that in mind") — force one real answer from the tool
                # output instead of shipping the empty ack.
                if (
                    not ctx.file_answer_nudge_used
                    and (loop.tools_used & _FILE_ANSWER_TOOLS)
                    and answer_looks_like_ack_only(content)
                    and not answer_looks_like_refusal(content)
                ):
                    ctx.file_answer_nudge_used = True
                    await loop._retract()
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {"role": "user", "content": file_answer_force_notice()}
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "phase=verify file-answer"},
                        )
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "verify", gate="file_answer", action="nudge"
                        )
                    return False
                # Perception: quote-first when web evidence exists.
                if (
                    evidence_gate
                    and ledger.has_ok("web")
                    and not ctx.quote_nudge_used
                    and exact_need.needs_web_evidence
                    and not _answer_has_quote_span(content)
                    and not answer_looks_like_refusal(content)
                ):
                    ctx.quote_nudge_used = True
                    await loop._retract()
                    messages.append({"role": "assistant", "content": content})
                    quotes = ledger.quote_lines()
                    notice = quote_first_notice()
                    if quotes:
                        notice += "\nEvidence spans:\n" + "\n".join(quotes)
                    messages.append({"role": "user", "content": notice})
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "phase=verify quote-first"},
                        )
                    )
                    if loop._timer is not None:
                        loop._timer.mark("verify", gate="quote", action="nudge")
                    return False
                # Research mode: prefer ≥research_min_sources hits. Nudge once when
                # we already have one good page; soft-fail (answer from it) if a
                # second source never lands — hard refuse only with zero warrants
                # (R5 / S02 refuse-after-scrape paradox).
                web_ok_n = len(ledger.ok_web_sources()) if ledger.has_ok("web") else 0
                if (
                    research_dual
                    and research_mode
                    and exact_need.needs_web_evidence
                    and web_ok_n < research_min_sources
                    and not answer_looks_like_refusal(content)
                ):
                    if not ctx.dual_hit_nudge_used and web_ok_n >= 1:
                        ctx.dual_hit_nudge_used = True
                        await loop._retract()
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user", "content": dual_hit_notice()})
                        await loop.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "phase=verify dual-hit"},
                            )
                        )
                        if loop._timer is not None:
                            loop._timer.mark(
                                "verify", gate="dual_hit", action="nudge"
                            )
                        return False
                    if web_ok_n == 0:
                        await loop._retract()
                        thin = unsupported_exactness_reply(["web"])
                        if loop._timer is not None:
                            loop._timer.mark(
                                "exactness",
                                gate="research_min_sources",
                                action="refuse",
                                have=web_ok_n,
                                need=research_min_sources,
                            )
                        # No Sources on refuse — empty list avoids cite-then-refuse.
                        await loop._finish(thin, [], streamed="")
                        return True
                    if ctx.dual_hit_nudge_used and web_ok_n >= 1:
                        if loop._timer is not None:
                            loop._timer.mark(
                                "exactness",
                                gate="dual_hit",
                                action="soft_fail",
                                have=web_ok_n,
                                need=research_min_sources,
                            )
                        # Fall through: answer from the one good source.
                # Reached only when force nudges above did not continue: refuse
                # unsupported claims instead of shipping a soft second invent.
                refuse = _exactness_finish_refuse(
                    content,
                    exact_need=ctx.exact_need,
                    ledger=ctx.ledger,
                    numeric_gate=ctx.numeric_gate,
                    evidence_gate=ctx.evidence_gate,
                    send_path=ctx.is_send_path(loop._expected_tools),
                )
                if refuse is None:
                    refuse = loop._look_refuse(content)
                if refuse is not None:
                    await loop._retract()
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "phase=verify refuse"},
                        )
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "verify",
                            gate="refuse",
                            kinds=",".join(exact_need.kinds),
                        )
                    await loop._finish(refuse, sources, streamed="")
                    return True
                if loop._timer is not None:
                    loop._timer.mark(
                        "round",
                        n=round_i,
                        ms=round_ms,
                        kind="final",
                        calls=0,
                    )
                    if exact_need.kinds:
                        loop._timer.mark(
                            "exactness",
                            gate="pass",
                            kinds=",".join(exact_need.kinds),
                            warrants=len(ledger),
                        )
                await loop._finish(content, sources, streamed=streamed)
                return True

        return None
    finally:
        r.text = text
        r.role = role
        r.agent_cfg = agent_cfg
        r.available_all = available_all
        r.available = available
        r.visible = visible
        r.tool_names = tool_names
        r.sources = sources
        r.ledger = ledger
        r.fail_counts = fail_counts
        r.skip_counts = skip_counts
        r.web_search_ok = web_search_ok
        r.page_ok = page_ok
        r.sms_sent = sms_sent
        r.agenda_created = agenda_created
        r.weather_ok_places = weather_ok_places
        r.weather_days_retried = weather_days_retried
        r.numeric_gate = numeric_gate
        r.evidence_gate = evidence_gate
        r.research_dual = research_dual
        r.research_min_sources = research_min_sources
        r.exact_need = exact_need
        r.offer_tools = offer_tools
        r.ollama_tools = ollama_tools
        r.messages = messages
        r.sms_preinject = sms_preinject
        r.sms_draft = sms_draft
        r.email_draft = email_draft
        r.agenda_draft = agenda_draft
        r.research_mode = research_mode
        r.preflight_kinds = preflight_kinds
        r.wants_fresh_page = wants_fresh_page
        r.active_room = active_room
        r.content = content
        r.streamed = streamed
        r.calls = calls
        r.tool_calls = tool_calls
        r.round_ms = round_ms
        r.model = model




async def run_round(loop: Any, ctx: TurnContext, round_i: int) -> bool:
    """One model/tool step. True means the turn is over."""
    try:
        text = ctx.text
        role = loop._turn_role
        agent_cfg = ctx.agent_cfg
        available_all = ctx.available_all
        available = ctx.available
        visible = ctx.visible
        tool_names = ctx.tool_names
        sources = ctx.sources
        ledger = ctx.ledger
        fail_counts = ctx.fail_counts
        skip_counts = ctx.skip_counts
        web_search_ok = ctx.web_search_ok
        page_ok = ctx.page_ok
        sms_sent = ctx.sms_sent
        agenda_created = ctx.agenda_created
        weather_ok_places = ctx.weather_ok_places
        weather_days_retried = ctx.weather_days_retried
        numeric_gate = ctx.numeric_gate
        evidence_gate = ctx.evidence_gate
        research_dual = ctx.research_dual
        research_min_sources = ctx.research_min_sources
        exact_need = ctx.exact_need
        offer_tools = ctx.offer_tools
        ollama_tools = ctx.ollama_tools
        messages = ctx.messages
        sms_preinject = ctx.sms_preinject
        sms_draft = ctx.sms_draft
        email_draft = ctx.email_draft
        agenda_draft = ctx.agenda_draft
        research_mode = ctx.research_mode
        preflight_kinds = ctx.preflight_kinds
        wants_fresh_page = ctx.wants_fresh_page
        active_room = ctx.active_room

        await loop._hold_if_paused()

        escalated = await loop._maybe_escalate(
            text,
            round_i=round_i,
            agent_cfg=agent_cfg,
        )
        role = loop._turn_role
        model = loop.router.model_for(role)
        if escalated:
            research_mode = is_research_mode(role, text)
            if research_mode:
                loop.max_rounds = max(
                    loop.max_rounds,
                    int(agent_cfg.get("research_max_rounds", 12)),
                )
            visible = filter_tool_names(
                available_all,
                role=role,
                text=text,
                enabled=bool(agent_cfg.get("research_tool_subset", False)),
                skill_subset=bool(agent_cfg.get("skill_tool_subset", False)),
                history=loop.memory.messages,
            )
            available = visible
            if loop._look is not None:
                look_tools = {n for n in available_all if n in LOOK_TOOL_SUBSET}
                if look_tools:
                    available = look_tools
                    visible = look_tools
            if loop._expected_tools & _HIDE_WANDER_FOR:
                available = _hide_daily_wander(
                    set(available), loop._expected_tools
                )
                visible = available
            available = _offer_expected(
                available, loop._expected_tools, available_all
            )
            visible = available
            if (
                looks_like_stale_sms_skip(text, loop.memory.messages)
                and "send_sms" not in loop._expected_tools
            ) or loop._look is not None:
                available = set(available)
                available.discard("send_sms")
                available.discard("send_email")
                visible = available
            ollama_tools = loop.tools.ollama_tools(visible)
            ctx.tool_names.clear()
            ctx.tool_names.update(visible)
            ctx.ollama_tools = ollama_tools
            ctx.available = set(available)
            ctx.visible = set(visible)
            ctx.research_mode = research_mode
            tool_names = ctx.tool_names

        if round_i > 1 and (
            ctx.email_sent_ok or ctx.agenda_create_ok or bool(sms_sent)
        ):
            offer_tools = False
            ollama_tools = []
            ctx.offer_tools = False
            ctx.ollama_tools = []
            ctx.tool_names.clear()
            tool_names = ctx.tool_names

        await loop.bus.publish(
            Event(
                EventType.THINKING,
                {"text": f"round {round_i}/{loop.max_rounds}  model step"},
            )
        )

        tools_arg = None if ctx.fallback_mode else (ollama_tools or None)
        round_ms = 0
        if sms_preinject is not None:
            injected = sms_preinject
            sms_preinject = None
            content = ""
            streamed = ""
            calls = [("send_sms", injected)]
            tool_calls = [_native_tool_call("send_sms", injected)]
            await loop.bus.publish(
                Event(
                    EventType.THINKING,
                    {"text": "inject  send_sms from a complete draft (pre-model)"},
                )
            )
            await loop.bus.publish(
                Event(EventType.STATUS, {"message": "Calling send_sms…"})
            )
            if loop._timer is not None:
                loop._timer.mark(
                    "exactness", gate="sms_force", action="preinject"
                )
        else:
            try:
                round_t0 = time.perf_counter()
                raw_content, tool_calls, streamed = await loop._stream_round(
                    role,
                    messages,
                    tools_arg,
                    round_n=round_i,
                    expect_tools=bool(tools_arg) and ctx.expect_tool_round,
                )
                round_ms = int((time.perf_counter() - round_t0) * 1000)
                if loop._timer is not None:
                    loop._timer.rounds += 1
                    loop._timer.model_ms += round_ms
            except _StoppedError:
                raise
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Some model/Ollama combinations reject the tools array
                # outright. Retry once without it and let the JSON protocol
                # carry the call. A dead or missing Ollama is not that case —
                # don't spend a second stream on JSON fallback while the chip
                # is already red.
                await loop._retract()
                failure = classify_ollama_failure(
                    exc,
                    model=model,
                    base_url=str(
                        (loop.config.get("ollama") or {}).get("base_url") or ""
                    ),
                    role=str(loop._turn_role or ""),
                )
                if (
                    loop.json_fallback
                    and not ctx.fallback_mode
                    and ollama_tools
                    and not failure.skip_tool_fallback
                ):
                    ctx.fallback_mode = True
                    messages[:] = _normalize_ollama_messages(messages)
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    f"native tools failed ({exc}); "
                                    "JSON fallback"
                                )
                            },
                        )
                    )
                    return False
                if (
                    is_vram_failure(exc)
                    and ctx.last_ok_tool_out
                    and "research_report" in loop.tools_used
                ):
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    "research_report ready; answering "
                                    "from artifact"
                                )
                            },
                        )
                    )
                    await loop._finish(
                        _tool_followup_fallback(ctx.last_ok_tool_out, ctx.last_ok_tool_name),
                        sources,
                        streamed="",
                    )
                    return True
                if ctx.last_ok_tool_out and _is_ollama_object_400(exc):
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    "ollama 400 after tool; answering "
                                    "from result"
                                )
                            },
                        )
                    )
                    await loop._finish(
                        _tool_followup_fallback(ctx.last_ok_tool_out, ctx.last_ok_tool_name),
                        sources,
                        streamed="",
                    )
                    return True
                await loop._publish_error(failure.chat, detail=failure.detail)
                return True

            content = strip_thinking_text(raw_content)
            calls = extract_native_tool_calls(tool_calls)

        if not calls and loop.json_fallback:
            # strict while native tool calling is working: only a trailing
            # JSON object counts as an instruction. Scanning prose for
            # embedded JSON would let an answer that merely discusses or
            # demonstrates a tool call execute it.
            parsed = parse_fallback_payload(content, strict=not ctx.fallback_mode)
            if parsed and parsed["kind"] == "tool":
                calls = [(parsed["name"], parsed["args"])]
            elif parsed and parsed["kind"] == "final":
                content = parsed["text"]

        r = _round_scratch(
            text=text,
            role=role,
            agent_cfg=agent_cfg,
            available_all=available_all,
            available=available,
            visible=visible,
            tool_names=tool_names,
            sources=sources,
            ledger=ledger,
            fail_counts=fail_counts,
            skip_counts=skip_counts,
            web_search_ok=web_search_ok,
            page_ok=page_ok,
            sms_sent=sms_sent,
            agenda_created=agenda_created,
            weather_ok_places=weather_ok_places,
            weather_days_retried=weather_days_retried,
            numeric_gate=numeric_gate,
            evidence_gate=evidence_gate,
            research_dual=research_dual,
            research_min_sources=research_min_sources,
            exact_need=exact_need,
            offer_tools=offer_tools,
            ollama_tools=ollama_tools,
            messages=messages,
            sms_preinject=sms_preinject,
            sms_draft=sms_draft,
            email_draft=email_draft,
            agenda_draft=agenda_draft,
            research_mode=research_mode,
            preflight_kinds=preflight_kinds,
            wants_fresh_page=wants_fresh_page,
            active_room=active_room,
            content=content,
            streamed=streamed,
            calls=calls,
            tool_calls=tool_calls,
            round_ms=round_ms,
            model=model,
        )
        done = await apply_no_call_path(loop, ctx, r, round_i)
        (
            available,
            visible,
            tool_names,
            ollama_tools,
            offer_tools,
            research_mode,
            sms_preinject,
            exact_need,
            calls,
            tool_calls,
            content,
            streamed,
            round_ms,
            role,
        ) = _pull_round(r)
        if done is not None:
            return done
        done = await dispatch_calls(loop, ctx, r, round_i)
        (
            available,
            visible,
            tool_names,
            ollama_tools,
            offer_tools,
            research_mode,
            sms_preinject,
            exact_need,
            calls,
            tool_calls,
            content,
            streamed,
            round_ms,
            role,
        ) = _pull_round(r)
        return done
    finally:
        ctx.role = loop._turn_role
        ctx.available = available
        ctx.visible = visible
        ctx.ollama_tools = ollama_tools
        ctx.offer_tools = offer_tools
        ctx.research_mode = research_mode
        ctx.sms_preinject = sms_preinject
        ctx.exact_need = exact_need

