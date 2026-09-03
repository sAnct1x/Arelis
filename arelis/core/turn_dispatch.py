"""Confirm and execute tool calls. ``dispatch_calls`` stays the coordinator."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

from arelis.contacts import web_search_targets_known_contact
from arelis.core.agenda_complete import (
    fill_agenda_args,
    lock_agenda_delete_args,
)
from arelis.core.agent_loop import (
    _BROWSER_WANDER,
    _MAX_THINKING_SNIPPET,
    _WEATHER_WANDER,
)
from arelis.core.call_redirects import apply_redirects
from arelis.core.claims import lock_memory_forget_args
from arelis.core.document_refs import fill_doc_extract_args, fill_document_args
from arelis.core.email_complete import (
    fill_send_email_args,
)
from arelis.core.events import Event, EventType
from arelis.core.image_refs import fill_vision_args
from arelis.core.look import look_call_blocked, vision_question
from arelis.core.read_fanout import should_fanout_reads
from arelis.core.same_call import already_ran_same_call
from arelis.core.sms_complete import (
    fill_send_sms_args,
)
from arelis.core.tool_args import cross_tool_arg_error, schema_keys
from arelis.core.tool_results import is_tool_cache_path
from arelis.core.tool_subset import web_read_caps
from arelis.core.turn_confirm import RUN, STOP, confirm_call
from arelis.core.turn_context import TurnContext
from arelis.core.turn_execute import execute_call
from arelis.tools.inbox import INBOX_PEEK_ACTIONS, fill_inbox_args
from arelis.tools.weather import (
    fill_weather_args,
    weather_place_key,
)


async def dispatch_calls(
    loop: Any, ctx: TurnContext, r: SimpleNamespace, round_i: int
) -> bool:
    """Confirm and execute ``r.calls``. True ends the turn.

    Wander redirects live in ``call_redirects``. Confirm/execute stay here
    with the per-call skip guards — those still share the round locals and
    resisted a second split without a new scratch object.
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
                confirm_run=loop.confirm_run,
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

            r.messages = messages
            r.tool_names = tool_names
            r.text = text
            r.agent_cfg = agent_cfg
            r.exact_need = exact_need
            r.weather_ok_places = weather_ok_places
            r.sms_draft = sms_draft
            r.sms_sent = sms_sent
            r.email_draft = email_draft
            r.agenda_draft = agenda_draft
            redirected = await apply_redirects(loop, ctx, r, name, args, _drop_wander)
            tool_names = ctx.tool_names
            messages = r.messages
            if redirected[0] == "skip":
                continue
            _, name, args = redirected

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
                args = fill_send_email_args(
                    args, email_draft, already_sent=ctx.email_sent
                )
                to_arg = str(args.get("to") or "").strip()
                if to_arg and to_arg.lower() in {s.lower() for s in ctx.email_sent}:
                    notice = (
                        f"Already sent email to {to_arg} earlier this turn; "
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

            if name == "workspace":
                ws_path = str(args.get("path") or "")
                if is_tool_cache_path(ws_path):
                    notice = (
                        "That path is this turn's scrape cache; not reading "
                        "it again. Use the scrape card already in context, "
                        "or scrape a different URL. Do not declare a winner "
                        "from a thin listicle."
                    )
                    await loop.bus.publish(
                        Event(EventType.THINKING, {"text": f"skip  {notice}"})
                    )
                    messages.append(loop._tool_message(name, notice))
                    loop._trace.append(f"{name} tool_cache blocked")
                    continue

            if name in {"scrape", "web_fetch"}:
                page = str(args.get("url") or "").strip().casefold()
                _, scrape_cap = web_read_caps(research_mode, agent_cfg)
                if len(page_ok) >= scrape_cap:
                    notice = (
                        f"Already opened {len(page_ok)} pages this turn; "
                        "not fetching another. Answer from those. If they "
                        "were thin or listicles, say the sources were weak "
                        "— do not rank or declare a winner."
                    )
                    await loop.bus.publish(
                        Event(EventType.THINKING, {"text": f"skip  {notice}"})
                    )
                    messages.append(loop._tool_message(name, notice))
                    loop._trace.append(f"{name} page budget blocked")
                    continue
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
                if page:
                    page_ok.add(page)

            if name == "web_search":
                q = str(args.get("query") or "").strip().casefold()
                search_cap, _ = web_read_caps(research_mode, agent_cfg)
                if len(web_search_ok) >= search_cap:
                    notice = (
                        f"Already ran {len(web_search_ok)} searches this turn; "
                        "not searching again. Answer from what you have. If "
                        "the hits were listicles, say so — do not declare a "
                        "winner."
                    )
                    await loop.bus.publish(
                        Event(EventType.THINKING, {"text": f"skip  {notice}"})
                    )
                    messages.append(loop._tool_message(name, notice))
                    loop._trace.append(f"{name} search budget blocked")
                    continue
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
                if q:
                    web_search_ok.add(q)

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

            # Same successful args this turn — a loop, not more work.
            same_notice = already_ran_same_call(ctx.same_ok, name, args)
            if same_notice:
                await loop.bus.publish(
                    Event(EventType.THINKING, {"text": f"skip  {same_notice}"})
                )
                messages.append(loop._tool_message(name, same_notice))
                loop._trace.append(f"{name} same call blocked")
                continue

            action, summary, call_fp = await confirm_call(
                loop,
                ctx,
                name,
                args,
                text=text,
                fail_counts=fail_counts,
                skip_counts=skip_counts,
                messages=messages,
                tool_names=tool_names,
                drop_wander=_drop_wander,
            )
            if action == STOP:
                break
            if action != RUN:
                continue

            r.available = available
            r.visible = visible
            r.tool_names = tool_names
            r.ollama_tools = ollama_tools
            ended = await execute_call(
                loop,
                ctx,
                r,
                name,
                args,
                summary=summary,
                call_fp=call_fp,
                round_i=round_i,
                call_i=call_i,
                fanout_results=fanout_results,
                later_weather=any(
                    other == "weather" for other, _ in calls[call_i + 1 :]
                ),
            )
            available = r.available
            visible = r.visible
            tool_names = r.tool_names
            ollama_tools = r.ollama_tools
            if ended:
                return True

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

