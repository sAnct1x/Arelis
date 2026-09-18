"""Confirm and execute tool calls. ``dispatch_calls`` stays the coordinator."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from arelis.attachments import wants_person_identify
from arelis.browser.walls import is_login_url
from arelis.contacts import web_search_targets_known_contact
from arelis.core.agenda_complete import (
    fill_agenda_args,
    lock_agenda_delete_args,
)
from arelis.core.agent_loop import (
    _BROWSER_WANDER,
    _MAX_THINKING_SNIPPET,
    _WEATHER_WANDER,
    _WRITE_AFTER_ALGEBRA_NOTICE,
)
from arelis.core.call_redirects import apply_redirects
from arelis.core.claims import lock_memory_forget_args
from arelis.core.document_refs import fill_doc_extract_args, fill_document_args
from arelis.core.email_complete import (
    fill_send_email_args,
)
from arelis.core.events import Event, EventType
from arelis.core.image_refs import (
    fill_image_edit_args,
    fill_image_gen_args,
    fill_vision_args,
)
from arelis.core.look import PASTED_IDENTIFY_QUESTION, look_call_blocked, vision_question
from arelis.core.preflight import looks_like_browser_click_signin
from arelis.core.read_fanout import should_fanout_reads
from arelis.core.same_call import (
    already_ran_same_call,
    is_browser_nav_call,
    same_call_finish_line,
    same_call_finishes_turn,
    same_call_key,
    same_call_strips_tools,
)
from arelis.core.sms_complete import (
    fill_send_sms_args,
)
from arelis.core.tool_args import cross_tool_arg_error, schema_keys
from arelis.core.tool_results import is_tool_cache_path
from arelis.core.tool_subset import web_read_caps
from arelis.core.turn_confirm import RUN, STOP, confirm_call
from arelis.core.turn_context import TurnContext
from arelis.core.turn_execute import execute_call
from arelis.core.turn_goal import LOGIN_READY_REPLY, browser_open_done_reply
from arelis.core.turn_scratch import RoundScratch, strip_tool_schemas
from arelis.tools.inbox import INBOX_PEEK_ACTIONS, fill_inbox_args
from arelis.tools.weather import (
    fill_weather_args,
    weather_place_key,
)


def fill_round_calls(
    loop: Any,
    calls: list[tuple[str, dict[str, Any]]],
    *,
    text: str,
) -> list[tuple[str, dict[str, Any]]]:
    """Apply the same arg fills fanout would otherwise skip.

    Fanout runs ``tools.call`` before the per-call loop. Weather days,
    inbox ids, and extract paths have to be on the args *before* gather,
    or the bookkeeping later reads a filled call against a raw result.
    """
    inbox = loop.tools.get("inbox") if loop is not None else None
    hits = getattr(inbox, "last_hits", None) if inbox is not None else None
    history = getattr(getattr(loop, "memory", None), "messages", None)
    receipts = getattr(loop, "_receipts", None)
    out: list[tuple[str, dict[str, Any]]] = []
    for name, args in calls:
        payload = dict(args or {})
        if name == "weather":
            payload = fill_weather_args(payload, text)
        elif name == "inbox":
            payload = fill_inbox_args(
                payload,
                user_text=text,
                last_hits=hits if isinstance(hits, list) else None,
            )
        elif name == "doc_extract":
            payload = fill_doc_extract_args(
                payload,
                user_text=text,
                history=history,
                receipts=receipts,
            )
        out.append((name, payload))
    return out


async def dispatch_calls(loop: Any, ctx: TurnContext, r: RoundScratch, round_i: int) -> bool:
    """Confirm and execute ``r.calls``. True ends the turn.

    Wander redirects live in ``call_redirects``. Confirm/execute stay here
    with the per-call skip guards, which share the round's tool surface —
    so they read and write it on ``r`` rather than on locals a ``finally``
    then has to copy back.
    """
    # The round was a tool call, so anything already painted was a
    # preamble rather than an answer. Take it off the screen and put it
    # in the thinking dock, which is where a model narrating itself
    # belongs.
    if loop._timer is not None:
        loop._timer.mark(
            "round",
            n=round_i,
            ms=r.round_ms,
            kind="tools",
            calls=len(r.calls),
        )
    if r.streamed.strip():
        await loop._retract()
        await loop.bus.publish(
            Event(
                EventType.THINKING,
                {"text": f"preamble  {r.streamed.strip()[:_MAX_THINKING_SNIPPET]}"},
            )
        )

    # Record the model's turn before the results, so the transcript
    # reads call-then-result. In fallback mode the JSON text itself is
    # the assistant turn: sending an empty message instead makes several
    # models re-issue the same call until max_rounds runs out.
    assistant_msg: dict[str, Any] = {"role": "assistant", "content": r.content}
    if r.tool_calls:
        assistant_msg["tool_calls"] = r.tool_calls
    r.messages.append(assistant_msg)

    r.calls = fill_round_calls(loop, r.calls, text=r.text)

    fanout_results: dict[int, tuple[int, Any]] | None = None
    if (
        bool(r.agent_cfg.get("read_fanout", True))
        and should_fanout_reads(
            r.calls,
            tool_names=r.tool_names,
            expected_tools=loop._expected_tools,
            tools=loop.tools,
            confirm_writes=loop.confirm_writes,
            confirm_image=loop.confirm_image,
            confirm_send=loop.confirm_send,
            confirm_browser=loop.confirm_browser,
            confirm_desktop=getattr(loop, "confirm_desktop", True),
            confirm_vision=loop.confirm_vision,
            confirm_run=loop.confirm_run,
            allow_writes_this_turn=ctx.allow_writes_this_turn,
            tools_used=loop.tools_used,
            web_search_ok=r.web_search_ok,
        )
    ):
        await loop.bus.publish(
            Event(
                EventType.THINKING,
                {"text": f"phase=fanout n={len(r.calls)} independent reads"},
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
                for index, (tool_name, tool_args) in enumerate(r.calls)
            ]
        )
        fanout_results = {
            index: (elapsed, tool_result)
            for index, elapsed, tool_result in gathered
        }
        if loop._timer is not None:
            loop._timer.mark("fanout", n=len(r.calls))

    call_i = -1

    def _drop_wander(*names: str) -> None:
        hide = set(names)
        r.available = set(r.available) - hide
        r.visible = set(r.visible) - hide
        ctx.tool_names.clear()
        ctx.tool_names.update(r.visible)
        r.tool_names = ctx.tool_names
        if r.offer_tools:
            r.ollama_tools = loop.tools.ollama_tools(r.visible)

    for name, args in r.calls:
        call_i += 1
        await loop._hold_if_paused()

        if name not in r.tool_names:
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
                    f"Available: {', '.join(sorted(r.tool_names))}"
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
                r.messages.append(loop._tool_message(name, err))
                continue

        # Arguments from a different tool — a cancelled SMS draft
        # arriving as calculator(to=…, body=…). Tools take **kwargs and
        # read only the keys they know, so without this the call looks
        # like a silent miss and the model retries it.
        if name == "weather":
            args = fill_weather_args(args, r.text)
        tool_obj = loop.tools.get(name)
        cross = cross_tool_arg_error(
            name,
            args,
            declared=schema_keys(
                getattr(tool_obj, "parameters_schema", None)
            )
            if tool_obj is not None
            else None,
            strict=bool(r.agent_cfg.get("strict_tool_args", True)),
        )
        if cross is not None:
            await loop.bus.publish(
                Event(EventType.THINKING, {"text": f"reject  {cross}"})
            )
            r.messages.append(loop._tool_message(name, cross))
            if loop._timer is not None:
                loop._timer.mark(
                    "exactness", gate="cross_tool_args", action="reject"
                )
            continue

        redirected = await apply_redirects(loop, ctx, r, name, args, _drop_wander)
        if redirected[0] == "skip":
            continue
        _, name, args = redirected

        # After a successful SMS this turn, do not web_search contacts.
        if (
            name == "web_search"
            and r.sms_sent
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
            r.messages.append(loop._tool_message(name, notice))
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
                r.messages.append(loop._tool_message(name, notice))
                continue

        if name == "send_sms":
            args = fill_send_sms_args(
                args, r.sms_draft, already_sent=r.sms_sent
            ) if r.sms_draft is not None else fill_send_sms_args(args, None)
            to_arg = str(args.get("to") or "").strip()
            if to_arg and to_arg.lower() in {s.lower() for s in r.sms_sent}:
                notice = (
                    f"Already sent SMS to {to_arg} earlier this turn; "
                    "not sending a duplicate."
                )
                await loop.bus.publish(
                    Event(EventType.THINKING, {"text": f"skip  {notice}"})
                )
                r.messages.append(loop._tool_message(name, notice))
                loop._trace.append(f"{name} duplicate send blocked")
                continue
            # Block junk follow-up bodies after a locked draft send.
            if (
                r.sms_draft is not None
                and r.sms_draft.complete
                and r.sms_sent
                and str(args.get("body") or "").strip()
                and str(args.get("body") or "").strip() != r.sms_draft.body
            ):
                notice = (
                    "Already sent the drafted SMS this turn; not sending "
                    "a different follow-up body."
                )
                await loop.bus.publish(
                    Event(EventType.THINKING, {"text": f"skip  {notice}"})
                )
                r.messages.append(loop._tool_message(name, notice))
                loop._trace.append(f"{name} extra body blocked")
                continue
        if name == "send_email" and r.email_draft is not None:
            args = fill_send_email_args(
                args, r.email_draft, already_sent=ctx.email_sent
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
                r.messages.append(loop._tool_message(name, notice))
                loop._trace.append(f"{name} duplicate send blocked")
                continue
        if name == "memory":
            if str(args.get("action") or "").strip().lower() == "forget":
                args = lock_memory_forget_args(args, r.text)

        if name == "agenda":
            if r.agenda_draft is not None:
                args = fill_agenda_args(args, r.agenda_draft)
            else:
                args = fill_agenda_args(args, None)
            if str(args.get("action") or "").strip().lower() == "delete":
                args = lock_agenda_delete_args(
                    args,
                    r.text,
                    receipts=loop._receipts,
                    history=loop.memory.messages,
                )
            if str(args.get("action") or "").strip().lower() == "create":
                from arelis.calendar.models import create_fingerprint

                create_fp = create_fingerprint(
                    args.get("provider"),
                    args.get("summary"),
                    args.get("start"),
                )
                if create_fp in r.agenda_created:
                    notice = (
                        "Already created this event earlier in the turn "
                        f"({args.get('summary')} @ {args.get('start')}); "
                        "not creating a duplicate."
                    )
                    await loop.bus.publish(
                        Event(EventType.THINKING, {"text": f"skip  {notice}"})
                    )
                    r.messages.append(loop._tool_message(name, notice))
                    loop._trace.append(f"{name} duplicate create blocked")
                    continue

        if name == "image_edit":
            args = fill_image_edit_args(
                args,
                history=loop.memory.messages,
                user_text=r.text,
            )
        if name == "image":
            args = fill_image_gen_args(
                args,
                history=loop.memory.messages,
                user_text=r.text,
            )

        if name == "vision":
            args = fill_vision_args(
                args,
                history=loop.memory.messages,
                user_text=r.text,
            )
            if loop._look is not None:
                args["question"] = vision_question(
                    loop._look.intent, r.text
                )
                if loop._look.path and not str(args.get("path") or "").strip():
                    args["path"] = loop._look.path
            elif wants_person_identify(r.text):
                asked = str(args.get("question") or "").strip()
                if not asked or asked.lower().startswith("describe"):
                    args["question"] = PASTED_IDENTIFY_QUESTION

        if name == "inbox":
            inbox = loop.tools.get("inbox")
            hits = getattr(inbox, "last_hits", None) if inbox is not None else None
            args = fill_inbox_args(
                args,
                user_text=r.text,
                last_hits=hits if isinstance(hits, list) else None,
            )

        if name == "document":
            room_kind = ""
            if r.active_room is not None:
                room_kind = str(r.active_room.kind or "")
            args = fill_document_args(
                args,
                user_text=r.text,
                history=loop.memory.messages,
                receipts=loop._receipts,
                room_kind=room_kind,
            )

        if name == "doc_extract":
            args = fill_doc_extract_args(
                args,
                user_text=r.text,
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
                r.messages.append(loop._tool_message(name, blocked_look))
                loop._trace.append(f"{name} look_grant_blocked")
                continue
            if name == "camera" and loop._look.camera_snaps >= 1:
                notice = (
                    "Already captured one still this look; not "
                    "snapshotting again. Answer from the SeeRecord."
                )
                r.messages.append(loop._tool_message(name, notice))
                loop._trace.append("camera look_cap")
                continue

        # One successful weather fetch per place — otherwise the 7B
        # re-calls weather until max_rounds (83s of duplicate Open-Meteo).
        if name == "weather":
            wx_key = weather_place_key(str(args.get("place") or ""))
            if wx_key in r.weather_ok_places:
                notice = (
                    "Already fetched weather for that place this turn; "
                    "not calling it again. Answer the user from the "
                    "prior weather result in plain prose and stop, or "
                    "call weather for a city you have not fetched yet."
                )
                await loop.bus.publish(
                    Event(EventType.THINKING, {"text": f"skip  {notice}"})
                )
                r.messages.append(loop._tool_message(name, notice))
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
                r.messages.append(loop._tool_message(name, notice))
                loop._trace.append(f"{name} tool_cache blocked")
                continue

        if name in {"scrape", "web_fetch"}:
            page = str(args.get("url") or "").strip().casefold()
            _, scrape_cap = web_read_caps(r.research_mode, r.agent_cfg)
            if len(r.page_ok) >= scrape_cap:
                notice = (
                    f"Already opened {len(r.page_ok)} pages this turn; "
                    "not fetching another. Answer from those. If they "
                    "were thin or listicles, say the sources were weak "
                    "— do not rank or declare a winner."
                )
                await loop.bus.publish(
                    Event(EventType.THINKING, {"text": f"skip  {notice}"})
                )
                r.messages.append(loop._tool_message(name, notice))
                loop._trace.append(f"{name} page budget blocked")
                continue
            if page and page in r.page_ok:
                notice = (
                    "Already fetched that URL this turn; not fetching "
                    "again. Use the prior result, or pick a different "
                    "URL. Do not call scrape or web_fetch on the same "
                    "address a second time."
                )
                await loop.bus.publish(
                    Event(EventType.THINKING, {"text": f"skip  {notice}"})
                )
                r.messages.append(loop._tool_message(name, notice))
                loop._trace.append(f"{name} duplicate url blocked")
                continue
            if page:
                r.page_ok.add(page)

        if name == "web_search":
            q = str(args.get("query") or "").strip().casefold()
            search_cap, _ = web_read_caps(r.research_mode, r.agent_cfg)
            if len(r.web_search_ok) >= search_cap:
                notice = (
                    f"Already ran {len(r.web_search_ok)} searches this turn; "
                    "not searching again. Answer from what you have. If "
                    "the hits were listicles, say so — do not declare a "
                    "winner."
                )
                await loop.bus.publish(
                    Event(EventType.THINKING, {"text": f"skip  {notice}"})
                )
                r.messages.append(loop._tool_message(name, notice))
                loop._trace.append(f"{name} search budget blocked")
                continue
            if q and q in r.web_search_ok:
                notice = (
                    "Already ran web_search with that query this turn; "
                    "not searching again. Answer from the prior result "
                    "or change the query."
                )
                await loop.bus.publish(
                    Event(EventType.THINKING, {"text": f"skip  {notice}"})
                )
                r.messages.append(loop._tool_message(name, notice))
                loop._trace.append(f"{name} duplicate query blocked")
                continue
            if q:
                r.web_search_ok.add(q)

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
            r.messages.append(loop._tool_message(name, notice))
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
            r.messages.append(loop._tool_message(name, notice))
            loop._trace.append(f"{name} duplicate generate blocked")
            continue

        # Same successful args this turn — a loop, not more work.
        same_notice = already_ran_same_call(ctx.same_ok, name, args)
        if same_notice:
            await loop.bus.publish(
                Event(EventType.THINKING, {"text": f"skip  {same_notice}"})
            )
            r.messages.append(loop._tool_message(name, same_notice))
            loop._trace.append(f"{name} same call blocked")
            key = same_call_key(name, args)
            repeat = bool(key and key in ctx.same_skip_keys)
            if key:
                ctx.same_skip_keys.add(key)
            # First blocked cas/python: take schemas away. The 9B
            # otherwise re-emits the same call until the round cap.
            if same_call_strips_tools(name):
                if not ctx.algebra_write_nudge_used:
                    ctx.algebra_write_nudge_used = True
                    r.messages.append(
                        {
                            "role": "user",
                            "content": _WRITE_AFTER_ALGEBRA_NOTICE,
                        }
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    "same-call algebra; asking for a write-up"
                                )
                            },
                        )
                    )
                strip_tool_schemas(ctx, r)
                continue
            stop_open = is_browser_nav_call(name, args) and (
                ctx.goal.kind == "browser" or looks_like_browser_click_signin(r.text)
            )
            if repeat or stop_open:
                if stop_open and is_login_url(ctx.last_browser_url):
                    line = LOGIN_READY_REPLY
                elif stop_open:
                    line = browser_open_done_reply(r.text)
                elif same_call_finishes_turn(name) or repeat:
                    line = same_call_finish_line(name, ctx.last_ok_tool_out)
                else:
                    continue
                await loop._finish(line, r.sources, streamed="")
                return True
            continue

        action, summary, call_fp = await confirm_call(
            loop,
            ctx,
            name,
            args,
            text=r.text,
            fail_counts=r.fail_counts,
            skip_counts=r.skip_counts,
            messages=r.messages,
            tool_names=r.tool_names,
            drop_wander=_drop_wander,
        )
        if action == STOP:
            break
        if action != RUN:
            continue

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
                other == "weather" for other, _ in r.calls[call_i + 1 :]
            ),
        )
        if ended:
            return True

    if ctx.skip_finish_text:
        await loop._finish(ctx.skip_finish_text, r.sources, streamed="")
        return True

    return False

