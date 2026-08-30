"""Confirm and execute tool calls. ``run_round`` stays the coordinator."""

from __future__ import annotations

import asyncio
import contextlib
import time
from types import SimpleNamespace
from typing import Any

from arelis.core.agent_loop import (
    _BROWSER_WANDER,
    _LOCAL_STORE,
    _MAX_THINKING_SNIPPET,
    _SKIP_NOTICE,
    _SMS_WANDER,
    _WEATHER_WANDER,
    INBOX_PEEK_ACTIONS,
    LOOKING_STATUS,
    Event,
    EventType,
    PreparedToolOutput,
    _tool_fail_fingerprint,
    action_receipt,
    agenda_force_call_notice,
    agenda_read_action,
    append_action_ledger,
    classify_fetch_failure,
    confirm_args_blocked,
    confirm_toggles_for_call,
    cross_tool_arg_error,
    draft_agenda_create_args,
    draft_agenda_delete_args,
    draft_browser_args,
    draft_send_email_args,
    draft_send_sms_args,
    draft_weather_args,
    fill_agenda_args,
    fill_doc_extract_args,
    fill_document_args,
    fill_inbox_args,
    fill_send_email_args,
    fill_send_sms_args,
    fill_vision_args,
    fill_weather_args,
    format_action_receipt,
    format_contact_spoken,
    format_see_record,
    frame_external_tool_output,
    inbox_peek_was_empty,
    local_store_inject_args,
    lock_agenda_delete_args,
    lock_memory_forget_args,
    look_call_blocked,
    looks_like_browser_or_url,
    looks_like_calendar_close,
    looks_like_calendar_delete,
    looks_like_calendar_open,
    looks_like_calendar_read,
    looks_like_contact_email_ask,
    looks_like_contact_phone_ask,
    looks_like_contacts_followup,
    looks_like_contacts_utterance,
    looks_like_schedule_manage,
    looks_like_scheduled_send,
    match_tile_intent,
    prepare_tool_output,
    redact_secrets,
    schema_keys,
    should_fanout_reads,
    should_redirect_wander_to_sms,
    tile_tool_args,
    tool_fail_replan_notice,
    tool_trace_entry,
    truncate_tool_output,
    user_asked_for_browser,
    uuid4,
    vision_question,
    weather_place_key,
    weather_places_missing,
    weather_wants_beyond_today,
    web_search_targets_known_contact,
)
from arelis.core.turn_context import TurnContext


async def dispatch_calls(
    loop: Any, ctx: TurnContext, r: SimpleNamespace, round_i: int
) -> bool:
    """Confirm and execute ``r.calls``. True ends the turn."""
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
        # The round was a tool call, so anything already painted was a
        # preamble rather than an answer. Take it off the screen and put it
        # in the thinking dock, which is where a model narrating itself
        # belongs.
        if loop._timer is not None:
            loop._timer.mark(
                "round",
                n=round_i,
                ms=round_ms,
                kind="tools",
                calls=len(calls),
            )
        if streamed.strip():
            await loop._retract()
            await loop.bus.publish(
                Event(
                    EventType.THINKING,
                    {"text": f"preamble  {streamed.strip()[:_MAX_THINKING_SNIPPET]}"},
                )
            )

        # Record the model's turn before the results, so the transcript
        # reads call-then-result. In fallback mode the JSON text itself is
        # the assistant turn: sending an empty message instead makes several
        # models re-issue the same call until max_rounds runs out.
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        fanout_results: dict[int, tuple[int, Any]] | None = None
        if (
            bool(agent_cfg.get("read_fanout", True))
            and should_fanout_reads(
                calls,
                tool_names=tool_names,
                expected_tools=loop._expected_tools,
                tools=loop.tools,
                confirm_writes=loop.confirm_writes,
                confirm_image=loop.confirm_image,
                confirm_send=loop.confirm_send,
                confirm_browser=loop.confirm_browser,
                confirm_vision=loop.confirm_vision,
                allow_writes_this_turn=ctx.allow_writes_this_turn,
                tools_used=loop.tools_used,
                web_search_ok=web_search_ok,
            )
        ):
            await loop.bus.publish(
                Event(
                    EventType.THINKING,
                    {"text": f"phase=fanout n={len(calls)} independent reads"},
                )
            )

            async def _fanout_one(
                index: int, tool_name: str, tool_args: dict[str, Any]
            ) -> tuple[int, int, Any]:
                started = time.perf_counter()
                tool_result = await loop.tools.call(tool_name, **tool_args)
                elapsed = int((time.perf_counter() - started) * 1000)
                return index, elapsed, tool_result

            gathered = await asyncio.gather(
                *[
                    _fanout_one(index, tool_name, tool_args)
                    for index, (tool_name, tool_args) in enumerate(calls)
                ]
            )
            fanout_results = {
                index: (elapsed, tool_result)
                for index, elapsed, tool_result in gathered
            }
            if loop._timer is not None:
                loop._timer.mark("fanout", n=len(calls))

        call_i = -1

        def _drop_wander(*names: str, _offer_tools: bool = offer_tools) -> None:
            nonlocal available, visible, tool_names, ollama_tools
            hide = set(names)
            available = set(available) - hide
            visible = set(visible) - hide
            ctx.tool_names.clear()
            ctx.tool_names.update(visible)
            tool_names = ctx.tool_names
            if _offer_tools:
                ollama_tools = loop.tools.ollama_tools(visible)

        for name, args in calls:
            call_i += 1
            await loop._hold_if_paused()

            if name not in tool_names:
                daily_miss = (
                    (
                        name in _WEATHER_WANDER
                        and "weather" in loop._expected_tools
                    )
                    or (
                        name in {
                            "web_search",
                            "contacts",
                            "user_location",
                            "weather",
                            "browser",
                            "scrape",
                            "web_fetch",
                        }
                        and "send_sms" in loop._expected_tools
                    )
                    or (
                        name in {"web_search", "analyze"}
                        and "send_email" in loop._expected_tools
                        and "analyze" not in loop._expected_tools
                    )
                    or (
                        name in {
                            "web_search",
                            "contacts",
                            "user_location",
                            "weather",
                            "schedule",
                        }
                        and "agenda" in loop._expected_tools
                    )
                    or (
                        name in _BROWSER_WANDER
                        and "browser" in loop._expected_tools
                    )
                )
                if not daily_miss:
                    err = (
                        f"Unknown tool `{name}`. "
                        f"Available: {', '.join(sorted(tool_names))}"
                    )
                    if name in {"comfyui", "search_images", "generate_image"}:
                        err += (
                            ". Image generation is the `image` tool. There is "
                            "no start-ComfyUI tool and no stock-photo search; "
                            "start ComfyUI yourself or set tools.image.auto_start."
                        )
                    await loop.bus.publish(
                        Event(EventType.THINKING, {"text": f"reject  {err}"})
                    )
                    messages.append(loop._tool_message(name, err))
                    continue

            # Arguments from a different tool — a cancelled SMS draft
            # arriving as calculator(to=…, body=…). Tools take **kwargs and
            # read only the keys they know, so without this the call looks
            # like a silent miss and the model retries it.
            if name == "weather":
                args = fill_weather_args(args, text)
            tool_obj = loop.tools.get(name)
            cross = cross_tool_arg_error(
                name,
                args,
                declared=schema_keys(
                    getattr(tool_obj, "parameters_schema", None)
                )
                if tool_obj is not None
                else None,
                strict=bool(agent_cfg.get("strict_tool_args", True)),
            )
            if cross is not None:
                await loop.bus.publish(
                    Event(EventType.THINKING, {"text": f"reject  {cross}"})
                )
                messages.append(loop._tool_message(name, cross))
                if loop._timer is not None:
                    loop._timer.mark(
                        "exactness", gate="cross_tool_args", action="reject"
                    )
                continue

            # Weather ask: never run web_search/scrape/fetch; inject weather.
            if (
                name in _WEATHER_WANDER
                and bool(agent_cfg.get("weather_force_call", True))
                and exact_need.needs_weather
                and not looks_like_scheduled_send(text)
                and not looks_like_schedule_manage(text)
                and not ctx.schedule_managed_ok
                and weather_places_missing(text, weather_ok_places)
                and "weather" in tool_names
            ):
                notice = (
                    "Blocked: this turn expects the weather tool, not "
                    f"{name}. Call weather now."
                )
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": f"redirect  {name} → weather"},
                    )
                )
                messages.append(loop._tool_message(name, notice))
                _drop_wander(*_WEATHER_WANDER)
                name = "weather"
                args = draft_weather_args(text)
                missing = weather_places_missing(text, weather_ok_places)
                if missing:
                    if missing[0]:
                        args["place"] = missing[0]
                    else:
                        args.pop("place", None)
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "inject  weather from intent"},
                    )
                )
                if loop._timer is not None:
                    loop._timer.mark(
                        "exactness",
                        gate="weather_redirect",
                        action="inject",
                    )
                # Fall through to execute injected weather.

            elif (
                name == "browser"
                and looks_like_calendar_open(text)
                and "agenda" in tool_names
            ):
                notice = (
                    "Blocked: this turn expects the Arelis calendar tile, "
                    f"not {name}. Call agenda with action=open."
                )
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "redirect  browser → agenda"},
                    )
                )
                messages.append(loop._tool_message(name, notice))
                name = "agenda"
                args = {"action": "open"}
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "inject  agenda open from intent"},
                    )
                )
                if loop._timer is not None:
                    loop._timer.mark(
                        "exactness",
                        gate="agenda_redirect",
                        action="inject",
                    )

            elif (
                name == "browser"
                and match_tile_intent(text)
                and "tile" in tool_names
            ):
                from arelis.tools.tile import TileTool

                inj = tile_tool_args(text, last_name=TileTool.last_name)
                if inj:
                    notice = (
                        "Blocked: this turn expects an Arelis tile, "
                        f"not {name}. Call tile with action="
                        f"{inj['action']} and name={inj['name']}."
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "redirect  browser → tile"},
                        )
                    )
                    messages.append(loop._tool_message(name, notice))
                    name = "tile"
                    args = inj
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  tile from intent"},
                        )
                    )

            # Browser drive: never run web_search/scrape; inject browser.
            elif (
                name in _BROWSER_WANDER
                and (
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
                notice = (
                    "Blocked: this turn expects the browser tool, not "
                    f"{name}. Call browser now."
                )
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": f"redirect  {name} → browser"},
                    )
                )
                messages.append(loop._tool_message(name, notice))
                _drop_wander(*_BROWSER_WANDER)
                name = "browser"
                args = inj
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "inject  browser from intent"},
                    )
                )
                if loop._timer is not None:
                    loop._timer.mark(
                        "exactness",
                        gate="browser_redirect",
                        action="inject",
                    )

            # Local store ask: never run weather/search instead of tasks/goals.
            elif (
                name
                in {
                    "weather",
                    "web_search",
                    "browser",
                    "scrape",
                    "web_fetch",
                    "user_location",
                }
                and loop._expected_tools & _LOCAL_STORE
                and name not in loop._expected_tools
            ):
                target = next(
                    (
                        t
                        for t in ("tasks", "goals", "contacts", "memory")
                        if t in loop._expected_tools and t in tool_names
                    ),
                    "",
                )
                if target and target not in loop.tools_used:
                    notice = (
                        f"Blocked: this turn expects {target}, not {name}."
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": f"redirect  {name} → {target}"},
                        )
                    )
                    messages.append(loop._tool_message(name, notice))
                    _drop_wander(
                        "weather",
                        "web_search",
                        "browser",
                        "scrape",
                        "web_fetch",
                        "user_location",
                    )
                    name = target
                    args = local_store_inject_args(
                        target,
                        text,
                        receipts=loop._receipts,
                        history=loop.memory.messages,
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": f"inject  {target} from intent"},
                        )
                    )

            # SMS ask: strip wander on first miss; inject when draft is complete.
            # contacts is wander only when the draft is already resolvable —
            # missing recipients (or a failed send) must be allowed to look up
            # or add a number instead of injecting the same bad card.
            elif (
                (
                    should_redirect_wander_to_sms(
                        name,
                        loop._expected_tools,
                        tools_used=loop.tools_used,
                        sms_failed=ctx.sms_failed,
                    )
                    or (
                        name == "contacts"
                        and sms_draft is not None
                        and sms_draft.complete
                        and not sms_draft.missing
                        and not ctx.sms_failed
                    )
                )
                and "send_sms" in loop._expected_tools
                and "send_sms" not in loop.tools_used
                and not ctx.sms_failed
            ):
                notice = (
                    "Blocked: this turn expects send_sms (or asking once "
                    f"for the message body), not {name}. Do not invent "
                    "a body. Call send_sms when to+body are known."
                )
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": f"redirect  {name} → sms"},
                    )
                )
                messages.append(loop._tool_message(name, notice))
                _drop_wander(*_SMS_WANDER)
                if (
                    sms_draft is not None
                    and sms_draft.complete
                    and "send_sms" in tool_names
                ):
                    inj = draft_send_sms_args(
                        sms_draft, already_sent=sms_sent
                    )
                    name = "send_sms"
                    args = inj
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  send_sms from draft"},
                        )
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "exactness",
                            gate="sms_redirect",
                            action="inject",
                        )
                    # Fall through to execute injected send_sms.
                else:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "The user wants to send a text. If the body is "
                                "missing, ask once what to say. If to and body "
                                "are known, call send_sms. Do not web_search."
                            ),
                        }
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "exactness",
                            gate="sms_redirect",
                            action="block",
                        )
                    continue

            # Email compose: block web_search/analyze; inject complete draft.
            elif (
                name in {"web_search", "analyze"}
                and "send_email" in loop._expected_tools
                and "send_email" not in loop.tools_used
                and "analyze" not in loop._expected_tools
            ):
                notice = (
                    "Blocked: this turn expects send_email, not "
                    f"{name}. Use the literal address the user gave."
                )
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": f"redirect  {name} → email"},
                    )
                )
                messages.append(loop._tool_message(name, notice))
                _drop_wander("web_search")
                if (
                    email_draft is not None
                    and email_draft.complete
                    and "send_email" in tool_names
                ):
                    name = "send_email"
                    args = draft_send_email_args(email_draft)
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  send_email from draft"},
                        )
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "exactness",
                            gate="email_redirect",
                            action="inject",
                        )
                else:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Call send_email with the address and body "
                                "the user gave. Do not web_search."
                            ),
                        }
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "exactness",
                            gate="email_redirect",
                            action="block",
                        )
                    continue

            # Calendar: block wander; inject create or delete on first miss.
            elif (
                name in {
                    "web_search",
                    "contacts",
                    "user_location",
                    "weather",
                    "schedule",
                }
                and "agenda" in loop._expected_tools
                and not ctx.agenda_create_ok
            ):
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": f"redirect  {name} → agenda"},
                    )
                )
                messages.append(
                    loop._tool_message(
                        name,
                        "Blocked: this turn expects agenda, not "
                        f"{name}. Call agenda (open, close, list, create, or delete).",
                    )
                )
                _drop_wander(
                    "web_search",
                    "contacts",
                    "user_location",
                    "weather",
                    "schedule",
                )
                if (
                    looks_like_calendar_delete(text)
                    and "agenda" in tool_names
                ):
                    inj = draft_agenda_delete_args(
                        text,
                        receipts=loop._receipts,
                        history=loop.memory.messages,
                    )
                    name = "agenda"
                    args = inj
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  agenda delete"},
                        )
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "exactness",
                            gate="agenda_redirect",
                            action="inject",
                        )
                elif (
                    agenda_draft is not None
                    and agenda_draft.complete
                    and "agenda" in tool_names
                ):
                    name = "agenda"
                    args = draft_agenda_create_args(agenda_draft)
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  agenda create from draft"},
                        )
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "exactness",
                            gate="agenda_redirect",
                            action="inject",
                        )
                elif looks_like_calendar_close(text) and "agenda" in tool_names:
                    name = "agenda"
                    args = {"action": "close"}
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  agenda close from intent"},
                        )
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "exactness",
                            gate="agenda_redirect",
                            action="inject",
                        )
                elif looks_like_calendar_open(text) and "agenda" in tool_names:
                    name = "agenda"
                    args = {"action": "open"}
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  agenda open from intent"},
                        )
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "exactness",
                            gate="agenda_redirect",
                            action="inject",
                        )
                elif looks_like_calendar_read(text) and "agenda" in tool_names:
                    name = "agenda"
                    args = {"action": agenda_read_action(text)}
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  agenda read from intent"},
                        )
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "exactness",
                            gate="agenda_redirect",
                            action="inject",
                        )
                else:
                    messages.append(
                        {
                            "role": "user",
                            "content": agenda_force_call_notice(agenda_draft)
                            if agenda_draft is not None and agenda_draft.complete
                            else (
                                "Call agenda with action=open, close, today, "
                                "tomorrow, list, create, or delete. Do not "
                                "web_search."
                            ),
                        }
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "exactness",
                            gate="agenda_redirect",
                            action="block",
                        )
                    continue

            # After a successful SMS this turn, do not web_search contacts.
            if (
                name == "web_search"
                and sms_sent
                and "send_sms" in loop.tools_used
            ):
                notice = (
                    "Blocked: SMS already sent this turn. Do not web_search "
                    "for the recipient. Answer the user and stop."
                )
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "redirect  web_search → stop (sms done)"},
                    )
                )
                messages.append(loop._tool_message(name, notice))
                continue

            # A known contact is already in contacts.yaml — never search
            # the public web for their phone/email/identity.
            if name == "web_search":
                hit = web_search_targets_known_contact(
                    str(args.get("query") or "")
                )
                if hit is not None:
                    notice = (
                        f"Blocked: {hit.display_name} is already in the "
                        f"contacts book (alias `{hit.alias}`). Use the "
                        "contacts tool or send_sms. Do not search the "
                        "public web for them."
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    f"redirect  web_search → contacts "
                                    f"({hit.alias})"
                                )
                            },
                        )
                    )
                    messages.append(loop._tool_message(name, notice))
                    continue

            if name == "send_sms":
                args = fill_send_sms_args(
                    args, sms_draft, already_sent=sms_sent
                ) if sms_draft is not None else fill_send_sms_args(args, None)
                to_arg = str(args.get("to") or "").strip()
                if to_arg and to_arg.lower() in {s.lower() for s in sms_sent}:
                    notice = (
                        f"Already sent SMS to {to_arg} earlier this turn; "
                        "not sending a duplicate."
                    )
                    await loop.bus.publish(
                        Event(EventType.THINKING, {"text": f"skip  {notice}"})
                    )
                    messages.append(loop._tool_message(name, notice))
                    loop._trace.append(f"{name} duplicate send blocked")
                    continue
                # Block junk follow-up bodies after a locked draft send.
                if (
                    sms_draft is not None
                    and sms_draft.complete
                    and sms_sent
                    and str(args.get("body") or "").strip()
                    and str(args.get("body") or "").strip() != sms_draft.body
                ):
                    notice = (
                        "Already sent the drafted SMS this turn; not sending "
                        "a different follow-up body."
                    )
                    await loop.bus.publish(
                        Event(EventType.THINKING, {"text": f"skip  {notice}"})
                    )
                    messages.append(loop._tool_message(name, notice))
                    loop._trace.append(f"{name} extra body blocked")
                    continue
            if name == "send_email" and email_draft is not None:
                args = fill_send_email_args(args, email_draft)
                if "send_email" in loop.tools_used:
                    notice = (
                        "Already sent this email earlier this turn; "
                        "not sending a duplicate."
                    )
                    await loop.bus.publish(
                        Event(EventType.THINKING, {"text": f"skip  {notice}"})
                    )
                    messages.append(loop._tool_message(name, notice))
                    loop._trace.append(f"{name} duplicate send blocked")
                    continue
            if name == "memory":
                if str(args.get("action") or "").strip().lower() == "forget":
                    args = lock_memory_forget_args(args, text)

            if name == "agenda":
                if agenda_draft is not None:
                    args = fill_agenda_args(args, agenda_draft)
                else:
                    args = fill_agenda_args(args, None)
                if str(args.get("action") or "").strip().lower() == "delete":
                    args = lock_agenda_delete_args(
                        args,
                        text,
                        receipts=loop._receipts,
                        history=loop.memory.messages,
                    )
                if str(args.get("action") or "").strip().lower() == "create":
                    create_fp = (
                        f"{str(args.get('provider') or '').strip().lower()}|"
                        f"{str(args.get('summary') or '').strip().casefold()}|"
                        f"{str(args.get('start') or '').strip()}"
                    )
                    if create_fp in agenda_created:
                        notice = (
                            "Already created this event earlier in the turn "
                            f"({args.get('summary')} @ {args.get('start')}); "
                            "not creating a duplicate."
                        )
                        await loop.bus.publish(
                            Event(EventType.THINKING, {"text": f"skip  {notice}"})
                        )
                        messages.append(loop._tool_message(name, notice))
                        loop._trace.append(f"{name} duplicate create blocked")
                        continue

            if name == "vision":
                args = fill_vision_args(
                    args,
                    history=loop.memory.messages,
                    user_text=text,
                )
                if loop._look is not None:
                    args["question"] = vision_question(
                        loop._look.intent, text
                    )
                    if loop._look.path and not str(args.get("path") or "").strip():
                        args["path"] = loop._look.path

            if name == "inbox":
                inbox = loop.tools.get("inbox")
                hits = getattr(inbox, "last_hits", None) if inbox is not None else None
                args = fill_inbox_args(
                    args,
                    user_text=text,
                    last_hits=hits if isinstance(hits, list) else None,
                )

            if name == "document":
                room_kind = ""
                if active_room is not None:
                    room_kind = str(active_room.kind or "")
                args = fill_document_args(
                    args,
                    user_text=text,
                    history=loop.memory.messages,
                    receipts=loop._receipts,
                    room_kind=room_kind,
                )

            if name == "doc_extract":
                args = fill_doc_extract_args(
                    args,
                    user_text=text,
                    history=loop.memory.messages,
                    receipts=loop._receipts,
                )

            if loop._look is not None:
                blocked_look = look_call_blocked(name, args)
                if blocked_look:
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": f"look grant block  {name}"},
                        )
                    )
                    messages.append(loop._tool_message(name, blocked_look))
                    loop._trace.append(f"{name} look_grant_blocked")
                    continue
                if name == "camera" and loop._look.camera_snaps >= 1:
                    notice = (
                        "Already captured one still this look; not "
                        "snapshotting again. Answer from the SeeRecord."
                    )
                    messages.append(loop._tool_message(name, notice))
                    loop._trace.append("camera look_cap")
                    continue

            # One successful weather fetch per place — otherwise the 7B
            # re-calls weather until max_rounds (83s of duplicate Open-Meteo).
            if name == "weather":
                wx_key = weather_place_key(str(args.get("place") or ""))
                if wx_key in weather_ok_places:
                    notice = (
                        "Already fetched weather for that place this turn; "
                        "not calling it again. Answer the user from the "
                        "prior weather result in plain prose and stop, or "
                        "call weather for a city you have not fetched yet."
                    )
                    await loop.bus.publish(
                        Event(EventType.THINKING, {"text": f"skip  {notice}"})
                    )
                    messages.append(loop._tool_message(name, notice))
                    loop._trace.append(f"{name} duplicate fetch blocked")
                    continue

            if name in {"scrape", "web_fetch"}:
                page = str(args.get("url") or "").strip().casefold()
                if page and page in page_ok:
                    notice = (
                        "Already fetched that URL this turn; not fetching "
                        "again. Use the prior result, or pick a different "
                        "URL. Do not call scrape or web_fetch on the same "
                        "address a second time."
                    )
                    await loop.bus.publish(
                        Event(EventType.THINKING, {"text": f"skip  {notice}"})
                    )
                    messages.append(loop._tool_message(name, notice))
                    loop._trace.append(f"{name} duplicate url blocked")
                    continue

            if name == "web_search":
                q = str(args.get("query") or "").strip().casefold()
                if q and q in web_search_ok:
                    notice = (
                        "Already ran web_search with that query this turn; "
                        "not searching again. Answer from the prior result "
                        "or change the query."
                    )
                    await loop.bus.publish(
                        Event(EventType.THINKING, {"text": f"skip  {notice}"})
                    )
                    messages.append(loop._tool_message(name, notice))
                    loop._trace.append(f"{name} duplicate query blocked")
                    continue

            if (
                name == "inbox"
                and ctx.inbox_empty_ok
                and str(args.get("action") or "").strip().lower()
                in INBOX_PEEK_ACTIONS
            ):
                notice = (
                    "Inbox list already came back empty this turn; not "
                    "listing again. Tell the user there is nothing there "
                    "and stop."
                )
                await loop.bus.publish(
                    Event(EventType.THINKING, {"text": f"skip  {notice}"})
                )
                messages.append(loop._tool_message(name, notice))
                loop._trace.append(f"{name} empty peek blocked")
                continue

            # One successful image per turn — otherwise the 7B re-opens Allow.
            if name == "image" and "image" in loop.tools_used:
                notice = (
                    "Already generated an image this turn; not generating "
                    "another. Tell the user the saved path from the prior "
                    "image result and stop."
                )
                await loop.bus.publish(
                    Event(EventType.THINKING, {"text": f"skip  {notice}"})
                )
                messages.append(loop._tool_message(name, notice))
                loop._trace.append(f"{name} duplicate generate blocked")
                continue

            blocked = confirm_args_blocked(name, args)
            if blocked:
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": f"phase=confirm blocked  {blocked}"},
                    )
                )
                messages.append(loop._tool_message(name, f"[fail:other] {blocked}"))
                loop._trace.append(f"{name} blocked: {blocked}")
                continue

            call_fp = _tool_fail_fingerprint(name, args)
            if fail_counts.get(call_fp, 0) >= 2:
                notice = (
                    f"[fail:other] Already failed twice with the same "
                    f"{name} arguments this turn; not asking Allow again. "
                    "Change the args or stop."
                )
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": f"phase=confirm skip_repeat_fail  {name}"},
                    )
                )
                messages.append(loop._tool_message(name, notice))
                loop._trace.append(f"{name} skip_repeat_fail")
                # Drop the tool from the remaining offer so the 7B cannot
                # burn every round on the same dead call.
                if name in tool_names:
                    visible = {t for t in tool_names if t != name}
                    ctx.tool_names.clear()
                    ctx.tool_names.update(visible)
                    tool_names = ctx.tool_names
                    ollama_tools = (
                        loop.tools.ollama_tools(visible)
                        if offer_tools and visible
                        else []
                    )
                stop_msg = (
                    f"Stop calling `{name}` with those same arguments — it "
                    "already failed twice this turn."
                )
                if (
                    "weather" in loop._expected_tools
                    and "weather" in tool_names
                    and "weather" not in loop.tools_used
                ):
                    stop_msg += (
                        " Call the weather tool for the forecast instead."
                    )
                else:
                    stop_msg += (
                        " Use a different tool or answer from what you have."
                    )
                messages.append({"role": "user", "content": stop_msg})
                if loop._timer is not None:
                    loop._timer.mark(
                        "skip_repeat_fail", tool=name, action="drop_tool"
                    )
                continue

            needs = loop.tools.needs_confirm(
                name,
                args,
                # "allow writes this turn" covers images/files/browser/vision.
                # It deliberately does not cover mail/SMS (confirm_send) or
                # calendar mutates (agenda create/update/delete) — those
                # stay one Allow each.
                **confirm_toggles_for_call(
                    name,
                    confirm_writes=loop.confirm_writes,
                    confirm_image=loop.confirm_image,
                    confirm_send=loop.confirm_send,
                    confirm_browser=loop.confirm_browser,
                    confirm_vision=loop.confirm_vision,
                    allow_writes_this_turn=ctx.allow_writes_this_turn,
                ),
            )
            if name == "browser" and user_asked_for_browser(text):
                needs = False
            if (
                loop._look is not None
                and name in {"ocr", "vision"}
                and loop._look.grant_minted
            ):
                needs = False
            if (
                loop._look is not None
                and name in {"ocr", "vision"}
                and not needs
            ):
                loop._look.grant_minted = True

            summary = loop.tools.summarize_call(name, args)
            if loop._look is not None and name in {"ocr", "vision"}:
                look_path = str(args.get("path") or loop._look.path or "")
                summary = (
                    f"look ({loop._look.intent.act}) at {look_path} — "
                    "one still, no further actions"
                )
            if needs:
                confirm_id = uuid4().hex
                confirm_t0 = time.perf_counter()
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": f"phase=confirm waiting Allow for {name}"},
                    )
                )
                # Heartbeat while the card is open (L10) so wall-clock wait
                # is not mistaken for a hung model.
                heartbeat = asyncio.create_task(
                    loop._confirm_wait_heartbeat(name, confirm_t0)
                )
                try:
                    decision = await loop.request_confirm(
                        confirm_id, name, args, summary
                    )
                finally:
                    heartbeat.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await heartbeat
                confirm_ms = int((time.perf_counter() - confirm_t0) * 1000)
                if loop._timer is not None:
                    loop._timer.confirm_ms += confirm_ms
                    loop._timer.mark(
                        "confirm",
                        tool=name,
                        ms=confirm_ms,
                        decision=decision,
                    )
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {
                            "text": (
                                f"phase=confirm ms={confirm_ms} "
                                f"decision={decision}"
                            )
                        },
                    )
                )
                if decision == "allow_turn":
                    ctx.allow_writes_this_turn = True
                    decision = "allow"
                if decision != "allow":
                    await loop.bus.publish(
                        Event(EventType.THINKING, {"text": f"skip  {summary}"})
                    )
                    skip_counts[call_fp] = skip_counts.get(call_fp, 0) + 1
                    drop = (
                        name not in loop._expected_tools
                        or skip_counts[call_fp] >= 2
                    )
                    if drop:
                        notice = (
                            f"The user declined `{name}` and it is not "
                            "available for the rest of this turn. Do not "
                            "call it again."
                        )
                        if (
                            "send_sms" in loop._expected_tools
                            and name != "send_sms"
                        ):
                            notice += (
                                " If to and body are known, call send_sms."
                            )
                        elif (
                            "send_email" in loop._expected_tools
                            and name != "send_email"
                        ):
                            notice += (
                                " Call send_email if the draft is complete."
                            )
                        messages.append(loop._tool_message(name, notice))
                        _drop_wander(name)
                        loop._trace.append(f"{name} skipped and dropped")
                        if loop._timer is not None:
                            loop._timer.mark(
                                "skip_drop", tool=name, action="drop_tool"
                            )
                    else:
                        messages.append(
                            loop._tool_message(
                                name, _SKIP_NOTICE.format(tool=name)
                            )
                        )
                        loop._trace.append(f"{name} declined by user")
                    if (
                        name in {"send_sms", "send_email"}
                        and name in loop._expected_tools
                    ):
                        ctx.skip_finish_text = "Okay — I did not send that."
                        break
                    continue
                if loop._look is not None and name in {"ocr", "vision"}:
                    loop._look.grant_minted = True
                    loop._look.allow_count = 1

            await loop.bus.publish(Event(EventType.TOOL_START, {"tool": name, "args": args}))
            if loop._look is not None and name == "vision":
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": LOOKING_STATUS},
                    )
                )
            await loop.bus.publish(
                Event(
                    EventType.THINKING,
                    {"text": f"round {round_i}/{loop.max_rounds}  tool  {summary}"},
                )
            )
            if name == "image":
                ctx.image_attempted = True
            if fanout_results is not None:
                ms, result = fanout_results[call_i]
            else:
                t0 = time.perf_counter()
                result = await loop.tools.call(name, **args)
                ms = int((time.perf_counter() - t0) * 1000)
            if loop._timer is not None:
                loop._timer.tool_ms += ms
                loop._timer.tools.append(name)
                tool_fields: dict[str, Any] = {
                    "name": name,
                    "ms": ms,
                    "ok": result.ok,
                }
                action = str(args.get("action") or "").strip()
                if action:
                    tool_fields["action"] = action
                loop._timer.mark("tool", **tool_fields)
            data_dict = result.data if isinstance(result.data, dict) else None
            if name in {"scrape", "web_fetch"} and not result.ok:
                tag = ""
                if isinstance(data_dict, dict):
                    tag = str(data_dict.get("fail_class") or "")
                if not tag:
                    tag = classify_fetch_failure(str(result.output or ""))
                if tag == "fail:js_shell":
                    url = ""
                    if isinstance(data_dict, dict):
                        url = str(data_dict.get("url") or "").strip()
                    if not url.startswith("http"):
                        url = str(args.get("url") or "").strip()
                    if url.startswith("http"):
                        ctx.js_shell_url = url
                        if "browser" in available_all:
                            visible = set(visible) | {"browser"}
                            available = set(available) | {"browser"}
                            ctx.tool_names.clear()
                            ctx.tool_names.update(visible)
                            tool_names = ctx.tool_names
                            if offer_tools:
                                ollama_tools = loop.tools.ollama_tools(visible)
            if result.ok:
                loop.tools_used.add(name)
                fail_counts.pop(call_fp, None)
                ctx.last_ok_tool_out = str(result.output or "")
                ctx.last_ok_tool_name = name
                if name == "inbox" and str(args.get("action") or "").lower() in {
                    "trash",
                    "archive",
                    "delete",
                }:
                    ctx.inbox_mutated_ok = True
                if (
                    name == "inbox"
                    and str(args.get("action") or "").lower() in INBOX_PEEK_ACTIONS
                    and inbox_peek_was_empty(data_dict)
                ):
                    ctx.inbox_empty_ok = True
                if name == "browser":
                    b_act = str(args.get("action") or "").strip().lower()
                    if b_act == "snapshot":
                        ctx.last_browser_snapshot = str(result.output or "")
                    if b_act == "click":
                        ctx.browser_clicked = True
                if name == "web_search":
                    q = str(args.get("query") or "").strip().casefold()
                    if q:
                        web_search_ok.add(q)
                if name in {"scrape", "web_fetch"}:
                    page = str(args.get("url") or "").strip().casefold()
                    if page:
                        page_ok.add(page)
                if name == "send_sms":
                    sent_to = str(args.get("to") or "").strip()
                    if sent_to:
                        sms_sent.add(sent_to)
                if name == "send_email":
                    ctx.email_sent_ok = True
                if name == "agenda" and str(args.get("action") or "").lower() == "create":
                    agenda_created.add(
                        f"{str(args.get('provider') or '').strip().lower()}|"
                        f"{str(args.get('summary') or '').strip().casefold()}|"
                        f"{str(args.get('start') or '').strip()}"
                    )
                    ctx.agenda_create_ok = True
                if loop._look is not None:
                    loop._note_look_tool(name, args, result, data_dict)
            else:
                fail_counts[call_fp] = fail_counts.get(call_fp, 0) + 1
                if name == "send_sms":
                    ctx.sms_failed = True
                if loop._look is not None and name == "camera":
                    loop._look.camera_snaps += 1
            if (not result.ok) and (
                name == "browser"
                and data_dict
                and str(data_dict.get("code") or "") == "PROFILE_LOCKED"
            ):
                # Attempted browser counts for routing_gap (R9).
                loop.tools_used.add(name)
            resolved = None
            if data_dict:
                resolved = data_dict.get("abs_path") or data_dict.get("path")
            if name == "browser" and data_dict:
                mode = str(data_dict.get("mode") or "").strip()
                code = str(data_dict.get("code") or "").strip()
                bits = ["browser"]
                if mode:
                    bits.append(mode)
                if code:
                    bits.append(code)
                action = str(args.get("action") or "").strip()
                if action:
                    bits.append(action)
                await loop.bus.publish(
                    Event(EventType.THINKING, {"text": "  ".join(bits)})
                )
                if (
                    code
                    in {
                        "PROFILE_LOCKED",
                        "RELAUNCH_FAILED",
                        "CDP_TIMEOUT",
                        "CDP_DEAD",
                    }
                    and not ctx.browser_relaunch_nudge_used
                    and bool(agent_cfg.get("browser_relaunch_force", True))
                ):
                    ctx.browser_relaunch_nudge_used = True
                    pending_url = str(
                        args.get("url") or args.get("target") or ""
                    ).strip()
                    url_bit = (
                        f", url={pending_url!r}" if pending_url else ""
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Browser connect/control failed "
                                f"({code}). If the user only asked to "
                                "pull up a site, call browser(action=open"
                                f"{url_bit}) — that is a plain OS open "
                                "(no Chrome restart). For click/snapshot/"
                                "navigate when CDP is down, call "
                                f"browser(action=relaunch{url_bit}) after "
                                "Allow, or ask them to close extra Chrome "
                                "windows. Do not screenshot until connected."
                            ),
                        }
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    f"browser {code}; one-shot "
                                    "relaunch-then-open nudge"
                                )
                            },
                        )
                    )
                    if loop._timer is not None:
                        loop._timer.mark(
                            "exactness", gate="browser_relaunch", action="nudge"
                        )
            loop._trace.append(
                tool_trace_entry(name, args, result.ok, resolved_path=resolved)
            )
            ledger.record_tool(
                name,
                ok=result.ok,
                output=str(result.output or ""),
                data=data_dict,
                args=args if isinstance(args, dict) else None,
            )
            receipt = action_receipt(
                name,
                ok=result.ok,
                args=args if isinstance(args, dict) else None,
                data=data_dict,
            )
            if loop._look is not None and name in {"vision", "ocr", "camera"}:
                receipt = None
                loop._emit_look_receipt_if_ready()
            if receipt is not None:
                loop._receipts.append(receipt)
                receipt_line = format_action_receipt(receipt)
                loop._trace.append(receipt_line)
                if loop._timer is not None:
                    loop._timer.mark(
                        "receipt",
                        action=str(receipt.get("action") or name),
                        ok=True,
                    )
                await loop.bus.publish(
                    Event(EventType.THINKING, {"text": receipt_line})
                )
                session_id = None
                sink = getattr(loop.memory, "sink", None)
                if sink is not None:
                    session_id = getattr(sink, "session_id", None)
                append_action_ledger(receipt, session_id=session_id)

            if (
                name in {"web_fetch", "scrape"}
                or (
                    name == "browser"
                    and result.ok
                    and str(args.get("action") or "").strip().lower() == "read"
                )
            ) and result.ok:
                url = str(
                    (data_dict or {}).get("url") or args.get("url") or ""
                ).strip()
                if (
                    (url.startswith("http://") or url.startswith("https://"))
                    and all(url != known for _, known in sources)
                ):
                    title = str((data_dict or {}).get("title") or "").strip()
                    sources.append((title, url))
            if name == "research_report" and result.ok and data_dict:
                for item in data_dict.get("sources") or []:
                    if not isinstance(item, dict):
                        continue
                    url = str(item.get("url") or "").strip()
                    if not (
                        url.startswith("http://") or url.startswith("https://")
                    ):
                        continue
                    if any(url == known for _, known in sources):
                        continue
                    title = str(item.get("title") or "").strip()
                    sources.append((title, url))

            # Redact → optional fat-tool summary card → hard char cap.
            redacted = redact_secrets(result.output)
            if bool(agent_cfg.get("tool_summary_inject", True)):
                prepared = prepare_tool_output(
                    name,
                    redacted,
                    data=data_dict,
                    max_inject_chars=min(loop.tool_output_chars, 4000),
                    force=False,
                )
            else:
                prepared = PreparedToolOutput(
                    inject=redacted,
                    full_ref=None,
                    summarized=False,
                    original_chars=len(redacted),
                )
            if prepared.summarized:
                if loop._timer is not None:
                    loop._timer.mark(
                        "tool_summary",
                        tool=name,
                        orig=prepared.original_chars,
                        ref=prepared.full_ref or "-",
                    )
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {
                            "text": (
                                f"tool_summary  {name}  "
                                f"{prepared.original_chars} chars → card"
                                + (
                                    f"  ref={prepared.full_ref}"
                                    if prepared.full_ref
                                    else ""
                                )
                            )
                        },
                    )
                )
                if data_dict is not None and prepared.full_ref:
                    data_dict = {**data_dict, "full_ref": prepared.full_ref}
            out, trunc = truncate_tool_output(
                prepared.inject, loop.tool_output_chars
            )
            out = frame_external_tool_output(
                name,
                out,
                action=str(args.get("action") or "")
                if isinstance(args, dict)
                else "",
            )
            if (
                loop._look is not None
                and name in {"ocr", "vision"}
                and loop._look.record is not None
                and result.ok
            ):
                out = f"{out}\n\n{format_see_record(loop._look.record)}"
            if trunc.truncated:
                if loop._timer is not None:
                    loop._timer.mark(
                        "truncate",
                        tool=name,
                        orig=trunc.original_chars,
                        kept=trunc.kept_chars,
                    )
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {
                            "text": (
                                f"truncated  {name}  "
                                f"{trunc.original_chars}->{trunc.kept_chars} chars"
                            )
                        },
                    )
                )
            await loop.bus.publish(
                Event(
                    EventType.TOOL_RESULT,
                    {
                        "tool": name,
                        "ok": result.ok,
                        "output": out,
                        "data": result.data,
                        "truncated": trunc.truncated,
                        "original_chars": trunc.original_chars,
                        "kept_chars": trunc.kept_chars,
                    },
                )
            )
            if name == "browser" and data_dict:
                wall_code = str(data_dict.get("code") or "")
                if wall_code in {"YOUR_TURN", "SECRET_FIELD"}:
                    await loop.bus.publish(
                        Event(
                            EventType.TURN_PAUSE,
                            {
                                "reason": "your_turn",
                                "kind": str(
                                    data_dict.get("wall")
                                    or ("login" if wall_code == "SECRET_FIELD" else "")
                                ),
                            },
                        )
                    )
                    await loop._await_your_turn(
                        str(data_dict.get("wall") or "")
                    )
            await loop.bus.publish(
                Event(
                    EventType.THINKING,
                    {
                        "text": (
                            f"round {round_i}/{loop.max_rounds}  "
                            f"{'ok' if result.ok else 'fail'}  {name}  {ms}ms"
                        )
                    },
                )
            )
            if (
                name in {"image", "image_edit"}
                and result.ok
                and data_dict
                and data_dict.get("path")
            ):
                await loop.bus.publish(
                    Event(EventType.IMAGE_READY, {"path": data_dict["path"]})
                )
                # Finish now — otherwise the 7B often re-calls image and
                # spams Allow (same class of bug as double-SMS). image_edit
                # joins it because the round after a finished edit is where
                # she reached for vision to check her own work and then the
                # calculator to verify the pixel count.
                path = str(data_dict["path"])
                if name == "image_edit":
                    # Its own sentence already names the sizes and the
                    # adjustments, which is the part worth reading.
                    await loop._finish(str(result.output).strip(), sources, streamed="")
                    return True
                await loop._finish(
                    f"Image ready — open in Workspace ({path}).",
                    sources,
                    streamed="",
                )
                return True
            if (
                name in {"document", "plot"}
                and result.ok
                and data_dict
                and data_dict.get("abs_path")
            ):
                await loop.bus.publish(
                    Event(
                        EventType.FILE_READY,
                        {
                            "path": str(data_dict.get("path") or ""),
                            "abs_path": str(data_dict.get("abs_path") or ""),
                            "format": str(data_dict.get("format") or ""),
                            "title": str(data_dict.get("title") or ""),
                            "show_card": True,
                            "open": False,
                        },
                    )
                )
            if (
                name == "schedule"
                and result.ok
                and str(args.get("action") or "").lower()
                in {"create", "create_briefing"}
            ):
                # Keep [job.id] in the transcript. The 7B otherwise
                # paraphrases the tool output and the id vanishes.
                await loop._finish(str(result.output).strip(), sources, streamed="")
                return True
            messages.append(loop._tool_message(name, out))
            if (
                name == "schedule"
                and result.ok
                and str(args.get("action") or "").lower() in {"list", "delete"}
            ):
                ctx.schedule_managed_ok = True
            # Successful weather → answer from it; do not re-fetch all round.
            # days=1 is today only; if they asked tomorrow, one retry with
            # days=3. fill_weather_args usually bumps that before the call.
            # Two named cities are two readings; lock per place, not the tool.
            if name == "weather" and result.ok:
                used_days = 3
                try:
                    used_days = int(args.get("days") or 3)
                except (TypeError, ValueError):
                    used_days = 3
                wx_key = weather_place_key(str(args.get("place") or ""))
                retry_days = (
                    used_days < 2
                    and weather_wants_beyond_today(text)
                    and wx_key not in weather_days_retried
                )
                if retry_days:
                    weather_days_retried.add(wx_key)
                    keep_place = str(args.get("place") or "").strip()
                    retry_msg = (
                        "That reading is today only. Call weather "
                        "again with days=3 (keep place if you used "
                        "one). Then answer the user from that."
                    )
                    if keep_place:
                        retry_msg = (
                            "That reading is today only. Call weather "
                            f"again with days=3 and place={keep_place}. "
                            "Then answer the user from that."
                        )
                    messages.append(
                        {
                            "role": "user",
                            "content": retry_msg,
                        }
                    )
                else:
                    weather_ok_places.add(wx_key)
                    missing = weather_places_missing(text, weather_ok_places)
                    if missing:
                        nxt = missing[0]
                        if nxt:
                            more_msg = (
                                "You already have a successful weather "
                                f"reading this turn. Call weather now with "
                                f"place={nxt} and days=3 for the other city. "
                                "Then answer from every reading. Do not "
                                "skip a named city."
                            )
                        else:
                            more_msg = (
                                "You already have a successful weather "
                                "reading this turn. Call weather now "
                                "without place for the user's own location. "
                                "Then answer from every reading."
                            )
                        messages.append(
                            {"role": "user", "content": more_msg}
                        )
                    else:
                        if "weather" in tool_names:
                            visible = {t for t in tool_names if t != "weather"}
                            ctx.tool_names.clear()
                            ctx.tool_names.update(visible)
                            tool_names = ctx.tool_names
                            ollama_tools = (
                                loop.tools.ollama_tools(visible)
                                if offer_tools and visible
                                else []
                            )
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "You already have a successful weather tool "
                                    "result this turn. Answer the user now in plain "
                                    "prose from that reading. Do not call weather "
                                    "again."
                                ),
                            }
                        )
                if loop._timer is not None:
                    loop._timer.mark(
                        "weather_once",
                        action=(
                            "retry_days"
                            if retry_days
                            else (
                                "need_place"
                                if weather_places_missing(text, weather_ok_places)
                                else "answer_now"
                            )
                        ),
                    )
            # Successful SMS to every draft recipient → confirm and stop.
            # Otherwise the model re-opens Allow and double-texts.
            if (
                name == "send_sms"
                and result.ok
                and sms_draft is not None
                and sms_draft.complete
            ):
                sent_l = {s.lower() for s in sms_sent}
                still = [
                    a
                    for a in (sms_draft.resolved_aliases or sms_draft.all_tos)
                    if a and a.lower() not in sent_l
                ]
                if not still:
                    who = ", ".join(sms_draft.all_tos) or "them"
                    await loop._finish(
                        f"Sent your text to {who}.",
                        sources,
                        streamed="",
                    )
                    return True
            if (
                name == "send_email"
                and result.ok
                and email_draft is not None
                and email_draft.complete
            ):
                who = email_draft.tool_to or email_draft.to or "them"
                await loop._finish(
                    f"Sent email to {who}.",
                    sources,
                    streamed="",
                )
                return True
            if (
                name == "contacts"
                and result.ok
                and "send_sms" not in loop._expected_tools
                and (
                    looks_like_contacts_utterance(text)
                    or looks_like_contacts_followup(
                        text, loop.memory.messages
                    )
                    or "contacts" in loop._expected_tools
                )
            ):
                data = result.data if isinstance(result.data, dict) else {}
                if looks_like_contact_phone_ask(text):
                    field = "phone"
                elif looks_like_contact_email_ask(text):
                    field = "email"
                else:
                    field = "who"
                spoken = format_contact_spoken(data, field=field)
                await loop._finish(
                    spoken or out.strip() or "No contact matched.",
                    sources,
                    streamed="",
                )
                return True
            # A store listing is already the answer, so handing it back beats
            # letting the 7B paraphrase a list it will pad. Only once nothing
            # else is outstanding, though: "what are my deadlines? pack my
            # week" expects tasks *and* agenda, and finishing on tasks meant
            # the calendar half of the ask was silently dropped.
            if (
                name in {"tasks", "goals"}
                and result.ok
                and name in loop._expected_tools
                and not (loop._expected_tools - loop.tools_used - {name})
            ):
                await loop._finish(
                    out.strip() or f"{name} done.",
                    sources,
                    streamed="",
                )
                return True
            if (
                name == "agenda"
                and result.ok
                and looks_like_calendar_delete(text)
                and str(args.get("action") or "").strip().lower() == "delete"
            ):
                await loop._finish(
                    out.strip() or "Calendar delete finished.",
                    sources,
                    streamed="",
                )
                return True
            if (
                not result.ok
                and not loop._fail_replan_used
            ):
                replan = tool_fail_replan_notice(
                    name, redacted, ok=False
                )
                if (
                    replan
                    and name == "web_search"
                    and (
                        exact_need.needs_weather
                        or "weather" in loop._expected_tools
                    )
                ):
                    replan += (
                        " If they asked about the weather/forecast, call "
                        "weather — do not web_search again."
                    )
                if replan:
                    loop._fail_replan_used = True
                    if loop._timer is not None:
                        loop._timer.mark("fail_replan", tool=name)
                    messages.append({"role": "system", "content": replan})
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": f"fail_replan  {name}"},
                        )
                    )

        if ctx.skip_finish_text:
            await loop._finish(ctx.skip_finish_text, sources, streamed="")
            return True

        return False

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

