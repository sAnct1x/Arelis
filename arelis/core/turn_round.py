"""One model/tool round. AgentLoop._run_round is a lazy delegate.

``run_round`` coordinates: escalate, stream (or preinject), then
``apply_no_call_path`` (nudge / inject / finish) and ``dispatch_calls``
(confirm / execute) in turn_dispatch. Rebound state rides on a
``RoundScratch`` (turn_scratch), so an early return or a raise still hands
the next stage what this one decided. Helpers stay defined on agent_loop
so existing tests that import them do not move.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from arelis.core.agent_loop import (
    _CLOSE_PARTIAL,
    _MAX_TOOL_NUDGES,
    _WRITE_AFTER_PAGE_NOTICE,
    _WRITE_AFTER_THINK_NOTICE,
    _WRITE_AFTER_TOOL_NOTICE,
    _CloseError,
    _is_tool_object_400,
    _native_tool_call,
    _normalize_tool_messages,
    _StoppedError,
    _tool_followup_fallback,
    append_tool_free_nudge,
    write_after_algebra_notice,
)
from arelis.core.claims import document_force_notice
from arelis.core.email_complete import (
    looks_like_bare_confirm,
    rewrite_schedule_calls,
)
from arelis.core.events import Event, EventType
from arelis.core.failure_copy import (
    _CONTENT_PASSTHROUGH_TOOLS,
    answer_is_raw_tool_line,
    followup_passthrough_tool,
    replace_raw_tool_line,
    reply_is_done_without_answer,
    should_nudge_write_after_algebra,
    should_nudge_write_after_page,
)
from arelis.core.json_tools import (
    extract_native_tool_calls,
    parse_fallback_payload,
    parse_text_tool_call,
    strip_thinking_text,
)
from arelis.core.loop_helpers import (
    _MALFORMED_CALL_NOTICE,
    chart_failed_reply,
    chart_only_failure,
    python_plot_stop_line,
)
from arelis.core.native_tool_calling import native_tool_calling
from arelis.core.no_call_finish import NUDGE as FINISH_NUDGE
from arelis.core.no_call_finish import hold_for_owed_tools, run_finish_steps
from arelis.core.no_call_steps import NUDGE, run_inject_steps
from arelis.core.preflight import rewrite_desktop_calls
from arelis.core.tool_subset import (
    is_research_mode,
    turn_round_budget,
)
from arelis.core.tool_surface import apply_expected, base_surface
from arelis.core.turn_context import TurnContext
from arelis.core.turn_dispatch import dispatch_calls
from arelis.core.turn_goal import (
    goal_miss_reply,
    goal_unlock_notice,
    receipt_serves_goal,
)
from arelis.core.turn_scratch import (
    RoundScratch,
    chain_unfinished,
    close_tools_after_progress,
    closing_call_ok,
    closing_tool_names,
    named_tools_owed,
    strip_tool_schemas,
    uncovered_named_steps,
)
from arelis.llm.errors import classify_turn_failure, is_vram_failure
from arelis.tools.pdf_pages import ink_vision_walk

_CHAIN_STILL_OPEN = "That result does not finish what they asked."
_CHECKING_AGAIN = "Checking again..."
_DISCARDED_CALL = "not applied; this call was not run."


def _chain_continue_notice(owed: list[str]) -> str:
    """Ask for the step the last receipt did not cover. Tools stay on."""
    if owed:
        names = ", ".join(owed)
        return (
            f"{_CHAIN_STILL_OPEN} "
            f"Call {names} for the step still open, then answer in your own words. "
            "Do not paste the tool output as the answer."
        )
    return (
        f"{_CHAIN_STILL_OPEN} "
        "Do the next step before you answer. "
        "Do not paste the tool output as the answer."
    )


async def _ask_for_tool_writeup(loop: Any, ctx: TurnContext, r: RoundScratch) -> None:
    """One write-up round. Schemas stay off. The model answers in words."""
    ctx.tool_answer_nudge_used = True
    strip_tool_schemas(ctx, r)
    await loop._retract()
    # The write-up line is already on the request that carried the tool
    # result. Adding it here, after that request was sent, would change
    # how the call renders.
    if not any(
        item.get("content") == _WRITE_AFTER_TOOL_NOTICE for item in r.messages
    ):
        r.messages.append({"role": "assistant", "content": r.content})
        r.messages.append(
            {"role": "user", "content": _WRITE_AFTER_TOOL_NOTICE}
        )
    await loop.bus.publish(
        Event(
            EventType.THINKING,
            {"text": "empty after tool; asking for a write-up"},
        )
    )


def _asked_to_continue(messages: list[dict[str, Any]]) -> bool:
    return any(
        str(item.get("content") or "").startswith(_CHAIN_STILL_OPEN) for item in messages
    )


async def _ask_for_next_step(loop: Any, ctx: TurnContext, r: RoundScratch) -> None:
    """Hold the turn open. Do not add the plain-answer line that forbids calls."""
    owed = uncovered_named_steps(loop, ctx)
    await loop._retract()
    r.messages.append({"role": "assistant", "content": r.content or ""})
    r.messages.append({"role": "user", "content": _chain_continue_notice(owed)})
    await loop.bus.publish(
        Event(
            EventType.THINKING,
            {"text": "chain still open; asking for the next step"},
        )
    )


async def _keep_bubble_on_retry(loop: Any) -> None:
    """A retry must not leave the reply bubble blank.

    Native tool rounds already keep the draft. A discarded plain-only
    round still has to show something until the next tokens arrive.
    Retract only to swap in the wait note, never to sit empty.
    """
    if str(getattr(loop, "_painted", "") or "").strip():
        await loop._retract()
    loop._wait_note = True
    await loop._publish_delta(_CHECKING_AGAIN)


def _record_discarded_round(
    loop: Any,
    messages: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
) -> None:
    """Keep the rejected call in the transcript, marked as not applied.

    The assistant row with tool_calls is what the next request needs so
    that call still renders. Rows come from that same list: one tool row
    per tool_call, with a matching id. Content from the discarded round
    is dropped, and the tool rows say the work did not run, so the next
    answer cannot treat those claims as done.
    """
    assistant_msg: dict[str, Any] = {
        "role": "assistant",
        "content": "",
    }
    if tool_calls:
        assistant_msg["tool_calls"] = tool_calls
    messages.append(assistant_msg)
    for call in tool_calls:
        fn = call.get("function") or {}
        name = str(fn.get("name") or "")
        row = loop._tool_message(name, _DISCARDED_CALL)
        call_id = call.get("id")
        if call_id:
            row["tool_call_id"] = str(call_id)
        messages.append(row)


def _write_round(ctx: TurnContext, r: RoundScratch) -> None:
    """Hand the next round the surface this one decided.

    These are the fields a step rebinds on ``r`` that the *next* round
    reads off ``ctx``. Everything else is already the same object on both
    (sets, the ledger, the drafts) or dies with the scratch.

    Goes through ``r``, not a local snapshot. A snapshot taken before a
    raise is how a wander-hide that already landed on the scratch could
    still be undone when ``dispatch_calls`` blew up, next round would
    offer web_search again.
    """
    ctx.available = r.available
    ctx.visible = r.visible
    ctx.chat_tools = r.chat_tools
    ctx.offer_tools = r.offer_tools
    ctx.research_mode = r.research_mode
    ctx.sms_preinject = r.sms_preinject
    ctx.email_preinject = r.email_preinject
    ctx.weather_preinject = r.weather_preinject
    ctx.agenda_preinject = r.agenda_preinject
    ctx.agenda_open_read_ok = r.agenda_open_read_ok
    ctx.calculator_preinject = r.calculator_preinject
    ctx.calculator_ok = r.calculator_ok
    ctx.units_preinject = r.units_preinject
    ctx.units_ok = r.units_ok
    ctx.browser_preinject = r.browser_preinject
    ctx.browser_ok = r.browser_ok
    ctx.tile_preinject = r.tile_preinject
    ctx.tile_ok = r.tile_ok
    ctx.workspace_preinject = r.workspace_preinject
    ctx.inspect_ok = r.inspect_ok
    ctx.run_script_preinject = r.run_script_preinject
    ctx.run_script_ok = r.run_script_ok
    ctx.exact_need = r.exact_need


async def apply_no_call_path(
    loop: Any, ctx: TurnContext, r: RoundScratch, round_i: int
) -> bool | None:
    """Nudge, inject, or finish when this round has no tool call.

    True ends the turn. False asks another round. None means dispatch
    should run (model already called, or a force-inject filled ``r.calls``).

    Inject and finish decisions live in ``no_call_steps`` / ``no_call_finish``.
    Everything rebindable is a field on ``r``, so a nudge that takes the tool
    schemas away has already handed that decision to the next round by the
    time this returns, or raises.
    """
    if not r.calls:
        # Plot is still owed and this round called nothing. Stop before a
        # nudge spends another model pass. A python call can keep the round.
        owed = python_plot_stop_line(
            next_tool=ctx.python_result_next_tool,
            ledger=ctx.ledger,
            plot_available="plot" in r.tool_names,
            extra_rounds=ctx.python_plot_extra_rounds,
            python_returned_data=not ctx.python_plot_data_failed,
            idle_round=True,
        )
        if owed:
            await loop._finish(owed, r.sources, streamed="")
            return True
        # The model wrote a call as prose instead of making one, so the
        # strict parser refused it. Executing it anyway is the hole
        # strict mode exists to close, and shipping it means the user
        # gets raw JSON as their answer and no tool ever runs. Neither
        # is acceptable, so ask again and say what went wrong.
        stray = (
            parse_fallback_payload(r.content, strict=False)
            if loop.json_fallback and not ctx.fallback_mode
            else None
        )
        if stray and stray["kind"] == "tool" and ctx.nudges < _MAX_TOOL_NUDGES:
            ctx.nudges += 1
            await loop._retract()
            r.messages.append({"role": "assistant", "content": r.content})
            r.messages.append(
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

        no_words = not (r.content or "").strip()
        # A failed chart plus a blank bubble used to start another model
        # pass. That pass is the one that can sit until the read times out.
        if no_words and not (ctx.last_ok_tool_out or "").strip():
            reply = chart_failed_reply(ctx.ledger)
            if reply:
                await loop._finish(reply, r.sources, streamed="")
                return True
        # A blank bubble is not an answer. Neither is a bare Done, or
        # Done plus a link, once a tool has already run. A copy of the
        # tool line is the same hole: it is not a written reply.
        pasted = " ".join((r.content or "").split())
        source = " ".join((ctx.last_ok_tool_out or "").split())
        # A paste of the receipt is not a written reply. On an open chain it
        # has to keep going; on a finished ask it is the status-line case.
        echo = answer_is_raw_tool_line(
            ctx.last_ok_tool_name, r.content, ctx.last_ok_tool_out
        ) or bool(pasted and source and pasted == source and chain_unfinished(loop, ctx))
        done_instead = bool(ctx.last_ok_tool_out) and reply_is_done_without_answer(r.content)
        if (no_words or done_instead or echo) and not ctx.fallback_mode:
            # Qwen3.5 often puts the wrap-up in thinking and leaves
            # chat content empty. Native calling still worked, a tool
            # already ran, so do not enter the sticky-note protocol
            # and do not ship the "empty reply / model unloaded" notice.
            # Tools may already be stripped (agenda/SMS/email wrap-up).
            # A long scrape/search must not become the chat line —
            # ask once for a write-up. Short facts (price, agenda)
            # still ship from the tool result.
            if ctx.last_ok_tool_out:
                serves_goal = receipt_serves_goal(
                    ctx.goal, ctx.last_ok_tool_name, ctx.last_ok_tool_out
                )
                owes_file = (
                    serves_goal
                    and ctx.exact_need.needs_document
                    and not ctx.ledger.has_ok("document")
                    and "document" in r.tool_names
                )
                # A search list is not the report. Stripping tools here
                # used to fire before goal-unlock, so scrape / document
                # came back as "Unknown tool".
                if (
                    owes_file
                    and not ctx.document_nudge_used
                    and ctx.nudges < _MAX_TOOL_NUDGES
                    and should_nudge_write_after_page(
                        ctx.last_ok_tool_name, ctx.last_ok_tool_out
                    )
                ):
                    ctx.document_nudge_used = True
                    ctx.nudges += 1
                    await loop._retract()
                    r.messages.append({"role": "assistant", "content": r.content})
                    r.messages.append(
                        {"role": "user", "content": document_force_notice()}
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    "empty after page; report still needs a file"
                                )
                            },
                        )
                    )
                    return False
                if (
                    serves_goal
                    and not ctx.page_write_nudge_used
                    and ctx.nudges < _MAX_TOOL_NUDGES
                    and should_nudge_write_after_page(
                        ctx.last_ok_tool_name, ctx.last_ok_tool_out
                    )
                ):
                    ctx.page_write_nudge_used = True
                    ctx.nudges += 1
                    strip_tool_schemas(ctx, r)
                    await loop._retract()
                    r.messages.append({"role": "assistant", "content": r.content})
                    r.messages.append(
                        {
                            "role": "user",
                            "content": _WRITE_AFTER_PAGE_NOTICE,
                        }
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": ("empty after page; asking for a write-up")},
                        )
                    )
                    return False
                if (
                    not ctx.algebra_write_nudge_used
                    and ctx.nudges < _MAX_TOOL_NUDGES
                    and should_nudge_write_after_algebra(ctx.last_ok_tool_name)
                ):
                    ctx.algebra_write_nudge_used = True
                    ctx.nudges += 1
                    strip_tool_schemas(ctx, r)
                    await loop._retract()
                    r.messages.append({"role": "assistant", "content": r.content})
                    r.messages.append(
                        {
                            "role": "user",
                            "content": write_after_algebra_notice(
                                ctx.last_ok_tool_name
                            ),
                        }
                    )
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": ("empty after algebra; asking for a write-up")},
                        )
                    )
                    return False
                if not receipt_serves_goal(
                    ctx.goal, ctx.last_ok_tool_name, ctx.last_ok_tool_out
                ):
                    if not ctx.goal_unlock_used and ctx.nudges < _MAX_TOOL_NUDGES:
                        ctx.goal_unlock_used = True
                        ctx.nudges += 1
                        await loop._retract()
                        r.messages.append({"role": "assistant", "content": r.content})
                        r.messages.append(
                            {
                                "role": "user",
                                "content": goal_unlock_notice(ctx.goal),
                            }
                        )
                        await loop.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        "goal unlock; last receipt does not finish the turn"
                                    )
                                },
                            )
                        )
                        return False
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": ("goal miss; not shipping that receipt")},
                        )
                    )
                    await loop._finish(
                        goal_miss_reply(ctx.goal),
                        r.sources,
                        streamed="",
                    )
                    return True
                ink_owes_vision = bool(ctx.ink_page_images and "vision" not in loop.tools_used)
                if ink_owes_vision and "vision" in r.tool_names:
                    pages = list(ctx.ink_page_images)
                    r.calls = ink_vision_walk(pages)
                    r.tool_calls = [_native_tool_call(n, a) for n, a in r.calls]
                    ctx.allow_writes_this_turn = True
                    ctx.ink_vision_nudge_used = True
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    f"looking at pages 1-{len(pages)} of "
                                    f"{len(pages)}, one at a time"
                                )
                            },
                        )
                    )
                    return None
                if chain_unfinished(loop, ctx) and not _asked_to_continue(r.messages):
                    await _ask_for_next_step(loop, ctx, r)
                    return False
                # Text pulled from a page is not a written answer yet. Ask
                # once. Ship the raw text only if that round is empty too.
                if (
                    ctx.last_ok_tool_name in _CONTENT_PASSTHROUGH_TOOLS
                    and not ctx.page_write_nudge_used
                    and not ctx.algebra_write_nudge_used
                    and not ctx.tool_answer_nudge_used
                ):
                    await _ask_for_tool_writeup(loop, ctx, r)
                    return False
                line = _tool_followup_fallback(
                    ctx.last_ok_tool_out,
                    ctx.last_ok_tool_name,
                    ask=ctx.text,
                )
                raw = (ctx.last_ok_tool_out or "").strip()
                # Weather / short agenda / price lines already are the answer.
                # Data dumps and formula rewrites still need a write-up round.
                already_plain = bool(
                    line.strip()
                    and (
                        line.strip() == raw
                        or (raw and line.strip() in raw)
                    )
                )
                # A status line that happens to be a sentence is still the
                # tool's text. Ask for a written reply instead of shipping it.
                if answer_is_raw_tool_line(ctx.last_ok_tool_name, line, raw):
                    already_plain = False
                if (
                    not already_plain
                    and not ctx.page_write_nudge_used
                    and not ctx.algebra_write_nudge_used
                    and not ctx.tool_answer_nudge_used
                ):
                    await _ask_for_tool_writeup(loop, ctx, r)
                    return False
                # Composed plain fallback is her words, not a tool paste.
                line = replace_raw_tool_line(ctx.last_ok_tool_name, line, raw)
                if await hold_for_owed_tools(loop, ctx, r, note_assistant=True):
                    return False
                passthrough = followup_passthrough_tool(
                    ctx.last_ok_tool_name, line, raw
                )
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": ("empty after tool; answering from result")},
                    )
                )
                await loop._finish(
                    line,
                    r.sources,
                    streamed="",
                    passthrough_tool=passthrough,
                )
                return True
            # Thinking ate the reply (LIGO / long proofs). Ask for the
            # chat line once. Skip when a daily inject still owes a
            # tool — weather/SMS/agenda must not become an essay.
            leftover = set(getattr(loop, "_expected_tools", ()) or ()) - {
                "cas",
                "python",
                "calculator",
                "units",
                "plot",
            }
            if (
                not leftover
                and not ctx.think_write_nudge_used
                and ctx.nudges < _MAX_TOOL_NUDGES
                and getattr(loop, "_last_round_thinking", False)
            ):
                ctx.think_write_nudge_used = True
                ctx.nudges += 1
                await loop._retract()
                r.messages.append({"role": "assistant", "content": r.content})
                r.messages.append(
                    {
                        "role": "user",
                        "content": _WRITE_AFTER_THINK_NOTICE,
                    }
                )
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": ("empty after think; asking for a write-up")},
                    )
                )
                return False
            if r.chat_tools and loop.json_fallback:
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
        hit = await run_inject_steps(loop, ctx, r)
        if hit == NUDGE:
            return False

        before_sched = list(r.calls)
        stripped_run_now = looks_like_bare_confirm(r.text) and any(
            n == "schedule" and str((a or {}).get("action") or "").lower() == "run_now"
            for n, a in before_sched
        )
        # Bare "yes" strips schedule run_now. That is the approval guard.
        if looks_like_bare_confirm(r.text):
            r.calls = rewrite_schedule_calls(
                r.text,
                r.calls,
                schedule_used="schedule" in loop.tools_used,
                schedule_available="schedule" in r.tool_names,
            )
            if r.calls != before_sched:
                r.tool_calls = [_native_tool_call(n, a) for n, a in r.calls]
                if not before_sched and r.calls:
                    await loop._retract()
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  schedule briefing from intent"},
                        )
                    )
        if stripped_run_now and not r.calls:
            await loop._finish(
                "The job is already scheduled. It will run at the time "
                "you set, no need to fire it now.",
                r.sources,
                streamed="",
            )
            return True

        before_desk = list(r.calls)
        r.calls = rewrite_desktop_calls(r.calls, text=r.text)
        if r.calls != before_desk:
            r.tool_calls = [_native_tool_call(n, a) for n, a in r.calls]
            await loop.bus.publish(
                Event(
                    EventType.THINKING,
                    {"text": "rewrite  desk look snapshot → screenshot"},
                )
            )

        if not r.calls:
            hit = await run_finish_steps(loop, ctx, r, round_i)
            if hit == FINISH_NUDGE:
                return False
            return True

    return None


async def run_round(loop: Any, ctx: TurnContext, round_i: int) -> bool:
    """One model/tool step. True means the turn is over."""
    # Only the names this coordinator rebinds, or that the write-back below
    # has to have bound before the first await. Everything else the round
    # needs is read off ``ctx`` when the scratch is built.
    text = ctx.text
    role = loop._turn_role
    agent_cfg = ctx.agent_cfg
    available_all = ctx.available_all
    available = ctx.available
    visible = ctx.visible
    tool_names = ctx.tool_names
    sources = ctx.sources
    messages = ctx.messages
    offer_tools = ctx.offer_tools
    chat_tools = ctx.chat_tools
    research_mode = ctx.research_mode
    exact_need = ctx.exact_need
    sms_preinject = ctx.sms_preinject
    email_preinject = ctx.email_preinject
    weather_preinject = ctx.weather_preinject
    agenda_preinject = ctx.agenda_preinject
    calculator_preinject = ctx.calculator_preinject
    units_preinject = ctx.units_preinject
    browser_preinject = ctx.browser_preinject
    tile_preinject = ctx.tile_preinject
    workspace_preinject = ctx.workspace_preinject
    run_script_preinject = ctx.run_script_preinject
    r: RoundScratch | None = None
    try:
        await loop._hold_if_paused()

        # A close is one answer from work already in hand, not a model swap
        # and not another search.
        escalated = False
        if not getattr(loop, "_in_close", False):
            escalated = await loop._maybe_escalate(
                text,
                round_i=round_i,
                agent_cfg=agent_cfg,
            )
        role = loop._turn_role
        model = loop.router.model_for(role)
        if escalated:
            research_mode = is_research_mode(role, text)
            loop.max_rounds = max(
                loop.max_rounds,
                turn_round_budget(role, text, agent_cfg, loop._default_max_rounds),
            )
            # active_room was always in scope here; the escalate copy of this
            # just never passed it, so a room's skills survived round one and
            # not round two.
            available, visible = base_surface(
                loop,
                available_all,
                role=role,
                text=text,
                agent_cfg=agent_cfg,
                active_room=ctx.active_room,
            )
            available, visible = apply_expected(
                loop, available, text=text, available_all=available_all
            )
            from arelis.core.tool_surface import session_tool_schemas

            chat_tools = session_tool_schemas(loop.tools, agent_cfg)
            ctx.tool_names.clear()
            ctx.tool_names.update(visible)
            ctx.chat_tools = chat_tools
            ctx.available = set(available)
            ctx.visible = set(visible)
            ctx.research_mode = research_mode
            tool_names = ctx.tool_names

        if round_i > 1 and (
            ctx.email_sent_ok
            or ctx.agenda_create_ok
            or ctx.agenda_open_read_ok
            or ctx.calculator_ok
            or ctx.units_ok
            or ctx.tile_ok
            or ctx.inspect_ok
            or ctx.run_script_ok
            or bool(ctx.sms_sent)
            or ctx.page_write_nudge_used
            or ctx.algebra_write_nudge_used
            or ctx.tool_answer_nudge_used
        ):
            # Only strip tools if all exactness needs are satisfied.
            # Multi-step asks (chains) need tools until all required kinds complete.
            # named_tools_owed still applies in native_tool_calling mode: the flag
            # drops regex injects/nudges, not the "user named these tools" hold.
            missing_kinds = ctx.ledger.missing_kinds(ctx.exact_need.kinds)
            if close_tools_after_progress(
                missing_kinds=missing_kinds,
                owed=named_tools_owed(loop, ctx),
                text=ctx.text,
                trace=getattr(loop, "_trace", ()),
            ):
                # Schemas stay. This round answers in words and does not run a call.
                offer_tools = False
                ctx.offer_tools = False
                ctx.plain_only = True
                ctx.tool_names.clear()
                tool_names = ctx.tool_names

        await loop.bus.publish(
            Event(
                EventType.THINKING,
                {"text": f"round {round_i}/{loop.max_rounds}  model step"},
            )
        )

        if getattr(loop, "_in_close", False):
            keep = closing_tool_names(
                ctx.text,
                getattr(loop, "_trace", ()),
                have_document=loop.tools.get("document") is not None,
                have_workspace=loop.tools.get("workspace") is not None,
            )
            # Closing still steers with the nudge. The schema list stays the
            # session list so this request matches the one before it.
            offer_tools = bool(keep)
            ctx.offer_tools = offer_tools
            if not keep:
                ctx.plain_only = True
                ctx.tool_names.clear()
                tool_names = ctx.tool_names

        # JSON fallback still omits schemas: the server rejected the tool
        # list, or this round is the text protocol. Sending the same list
        # again would repeat that rejection. A plain-answer round is not
        # that case, so it keeps the list and adds one last line.
        tools_arg = None if ctx.fallback_mode else (chat_tools or None)
        if ctx.plain_only and not ctx.fallback_mode:
            append_tool_free_nudge(messages)
        round_ms = 0
        try:
            round_t0 = time.perf_counter()
            raw_content, tool_calls, streamed = await loop._stream_round(
                role,
                messages,
                tools_arg,
                round_n=round_i,
                # Hold paint only until a tool has answered. The write-up
                # round after that streams, so speech can start per sentence.
                expect_tools=(
                    bool(tools_arg)
                    and ctx.expect_tool_round
                    and not ctx.plain_only
                    and not ctx.last_ok_tool_name
                ),
            )
            round_ms = int((time.perf_counter() - round_t0) * 1000)
            if loop._timer is not None:
                loop._timer.rounds += 1
                loop._timer.model_ms += round_ms
        except _StoppedError:
            raise
        except _CloseError:
            # Pre-stream only. A close during the stream no longer raises,
            # so a finished call is not on this exception. Stop still wins
            # if it landed in the same gap. Stubs used by round tests have
            # no cancel flag.
            cancelled = getattr(loop, "is_cancelled", None)
            if callable(cancelled) and cancelled():
                raise _StoppedError
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Some servers reject the tools array outright. Retry once
            # without it and let the JSON protocol carry the call. A dead
            # server is not that case. Do not spend a second stream on JSON
            # fallback while the chip is already red.
            await loop._retract()
            failure = classify_turn_failure(
                exc,
                model=model,
                role=str(loop._turn_role or ""),
                config=getattr(loop, "config", None),
                backend=getattr(getattr(loop, "router", None), "provider", None),
            )
            if (
                ctx.last_ok_tool_out
                and _is_tool_object_400(exc)
                and not failure.skip_tool_fallback
            ):
                # A result is already in hand. Another request does not
                # phrase it: the same 400 comes back. Ship the sentence.
                four_line = _tool_followup_fallback(
                    ctx.last_ok_tool_out,
                    ctx.last_ok_tool_name,
                    ask=ctx.text,
                )
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": ("tool result rejected; answering from it")},
                    )
                )
                await loop._finish(
                    four_line,
                    sources,
                    streamed="",
                    passthrough_tool=followup_passthrough_tool(
                        ctx.last_ok_tool_name,
                        four_line,
                        ctx.last_ok_tool_out,
                    ),
                )
                return True
            if (
                loop.json_fallback
                and not ctx.fallback_mode
                and chat_tools
                and not failure.skip_tool_fallback
            ):
                ctx.fallback_mode = True
                messages[:] = _normalize_tool_messages(messages)
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": (f"native tools failed ({exc}); JSON fallback")},
                    )
                )
                return False
            if (
                is_vram_failure(exc)
                and ctx.last_ok_tool_out
                and "research_report" in loop.tools_used
            ):
                vram_line = _tool_followup_fallback(
                    ctx.last_ok_tool_out,
                    ctx.last_ok_tool_name,
                    ask=ctx.text,
                )
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": ("research_report ready; answering from artifact")},
                    )
                )
                await loop._finish(
                    vram_line,
                    sources,
                    streamed="",
                    passthrough_tool=followup_passthrough_tool(
                        ctx.last_ok_tool_name,
                        vram_line,
                        ctx.last_ok_tool_out,
                    ),
                )
                return True
            await loop._publish_error(failure.chat, detail=failure.detail)
            return True

        content = strip_thinking_text(raw_content)
        calls = extract_native_tool_calls(tool_calls)
        # Native calls keep a streamed draft. Text parses do not. The
        # flag is on the parsed dict. The wording of the draft is not
        # what decides it.
        calls_from_text = False
        # When native_tool_calling is enabled and the model wrote a text-form
        # tool call (e.g. <tool_call>{"name":..., "arguments":...}</tool_call>),
        # parse and execute it.
        if (
            not calls
            and native_tool_calling(agent_cfg)
            and content
        ):
            # Names are cleared on a plain round, so pass none and
            # reject the call below instead of missing it.
            text_call = parse_text_tool_call(
                content,
                registered_tools=None if ctx.plain_only else tool_names,
            )
            if (
                text_call
                and text_call.get("kind") == "tool"
                and text_call.get("from_text") is True
            ):
                name = text_call["name"]
                args = text_call["args"]
                calls = [(name, args)]
                tool_calls = [_native_tool_call(name, args)]
                calls_from_text = True

        if not calls and loop.json_fallback:
            # strict while native tool calling is working: only a trailing
            # JSON object counts as an instruction. Scanning prose for
            # embedded JSON would let an answer that merely discusses or
            # demonstrates a tool call execute it.
            parsed = parse_fallback_payload(content, strict=not ctx.fallback_mode)
            if (
                parsed
                and parsed["kind"] == "tool"
                and parsed.get("from_text") is True
            ):
                name = parsed["name"]
                args = parsed["args"]
                calls = [(name, args)]
                tool_calls = [_native_tool_call(name, args)]
                calls_from_text = True
            elif parsed and parsed["kind"] == "final":
                content = parsed["text"]

        # A close pass does not get the re-ask. The block below owns that
        # round, and a menu that progress already closed stays closed.
        if (
            ctx.plain_only
            and not ctx.fallback_mode
            and calls
            and not getattr(loop, "_in_close", False)
        ):
            if not ctx.plain_reask_used:
                ctx.plain_reask_used = True
                # A real user line after the rejected call keeps that call
                # rendering the same way on the next turn. The discarded
                # prose and results are not fed through as if they ran.
                _record_discarded_round(loop, messages, tool_calls)
                messages.append(
                    {"role": "user", "content": _WRITE_AFTER_TOOL_NOTICE}
                )
                append_tool_free_nudge(messages)
                await _keep_bubble_on_retry(loop)
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "plain answer round; asking again"},
                    )
                )
                return False
            prose = (content or "").strip()
            if answer_is_raw_tool_line(ctx.last_ok_tool_name, prose, ctx.last_ok_tool_out):
                prose = ""
            if not prose and ctx.last_ok_tool_out:
                prose = replace_raw_tool_line(
                    ctx.last_ok_tool_name,
                    _tool_followup_fallback(
                        ctx.last_ok_tool_out,
                        ctx.last_ok_tool_name,
                        ask=ctx.text,
                    ),
                    ctx.last_ok_tool_out,
                )
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "plain answer round; answering from result"},
                    )
                )
                await loop._finish(
                    prose,
                    sources,
                    streamed="",
                    passthrough_tool=followup_passthrough_tool(
                        ctx.last_ok_tool_name,
                        prose,
                        ctx.last_ok_tool_out,
                    ),
                )
                return True
            await loop._finish(prose, sources, streamed="")
            return True

        # A close that arrived while this step was still streaming keeps the
        # calls. They go through the normal confirm and execute path below.
        # The allow-list applies only once the close pass itself is running.
        wants_close = getattr(loop, "_wants_close", None)
        if (
            calls
            and callable(wants_close)
            and wants_close()
            and not getattr(loop, "_in_close", False)
        ):
            loop._close_kept_calls = True
        if getattr(loop, "_in_close", False):
            kept_calls = bool(getattr(loop, "_close_kept_calls", False))
            loop._close_kept_calls = False
            # plain_only means a send (or another finished step) already took
            # the menu. The wrap-up allow-list must not hand it back.
            if ctx.plain_only:
                calls = []
            else:
                calls = [
                    (n, a)
                    for n, a in (calls or [])
                    if closing_call_ok(n, a, ctx.text, getattr(loop, "_trace", ()))
                ]
            if not calls:
                prose = (content or "").strip()
                if not prose:
                    prose = chart_only_failure(ctx.ledger, loop) or ""
                if not prose and kept_calls and ctx.last_ok_tool_out:
                    prose = _tool_followup_fallback(
                        ctx.last_ok_tool_out,
                        ctx.last_ok_tool_name,
                        ask=ctx.text,
                    )
                if not prose:
                    prose = _CLOSE_PARTIAL
                await loop._finish(prose, sources, streamed=streamed)
                return True
            tool_calls = [_native_tool_call(n, a) for n, a in calls]

        r = RoundScratch(
            text=text,
            agent_cfg=agent_cfg,
            available_all=available_all,
            available=available,
            visible=visible,
            tool_names=tool_names,
            sources=sources,
            ledger=ctx.ledger,
            fail_counts=ctx.fail_counts,
            skip_counts=ctx.skip_counts,
            web_search_ok=ctx.web_search_ok,
            page_ok=ctx.page_ok,
            sms_sent=ctx.sms_sent,
            agenda_created=ctx.agenda_created,
            weather_ok_places=ctx.weather_ok_places,
            weather_days_retried=ctx.weather_days_retried,
            numeric_gate=ctx.numeric_gate,
            evidence_gate=ctx.evidence_gate,
            research_dual=ctx.research_dual,
            research_min_sources=ctx.research_min_sources,
            exact_need=exact_need,
            offer_tools=offer_tools,
            chat_tools=chat_tools,
            messages=messages,
            sms_preinject=sms_preinject,
            email_preinject=email_preinject,
            weather_preinject=weather_preinject,
            agenda_preinject=agenda_preinject,
            agenda_open_read_ok=ctx.agenda_open_read_ok,
            calculator_preinject=calculator_preinject,
            calculator_ok=ctx.calculator_ok,
            units_preinject=units_preinject,
            units_ok=ctx.units_ok,
            browser_preinject=browser_preinject,
            browser_ok=ctx.browser_ok,
            tile_preinject=tile_preinject,
            tile_ok=ctx.tile_ok,
            workspace_preinject=workspace_preinject,
            inspect_ok=ctx.inspect_ok,
            run_script_preinject=run_script_preinject,
            run_script_ok=ctx.run_script_ok,
            sms_draft=ctx.sms_draft,
            email_draft=ctx.email_draft,
            agenda_draft=ctx.agenda_draft,
            research_mode=research_mode,
            preflight_kinds=ctx.preflight_kinds,
            wants_fresh_page=ctx.wants_fresh_page,
            active_room=ctx.active_room,
            content=content,
            streamed=streamed,
            calls=calls,
            tool_calls=tool_calls,
            round_ms=round_ms,
            calls_from_text=calls_from_text,
        )
        done = await apply_no_call_path(loop, ctx, r, round_i)
        if done is not None:
            return done
        done = await dispatch_calls(loop, ctx, r, round_i)
        if (
            done is False
            and ctx.ink_page_images
            and "vision" not in loop.tools_used
            and "vision" in r.tool_names
        ):
            pages = list(ctx.ink_page_images)
            extra = ink_vision_walk(pages)
            r.calls = extra
            r.tool_calls = [_native_tool_call(n, a) for n, a in extra]
            r.calls_from_text = False
            ctx.allow_writes_this_turn = True
            ctx.ink_vision_nudge_used = True
            await loop.bus.publish(
                Event(
                    EventType.THINKING,
                    {"text": (f"looking at pages 1-{len(pages)} of {len(pages)}, one at a time")},
                )
            )
            done = await dispatch_calls(loop, ctx, r, round_i)
        return done
    finally:
        ctx.role = loop._turn_role
        if r is not None:
            _write_round(ctx, r)
        else:
            ctx.available = available
            ctx.visible = visible
            ctx.chat_tools = chat_tools
            ctx.offer_tools = offer_tools
            ctx.research_mode = research_mode
            ctx.sms_preinject = sms_preinject
            ctx.email_preinject = email_preinject
            ctx.weather_preinject = weather_preinject
            ctx.agenda_preinject = agenda_preinject
            ctx.calculator_preinject = calculator_preinject
            ctx.units_preinject = units_preinject
            ctx.browser_preinject = browser_preinject
            ctx.tile_preinject = tile_preinject
            ctx.workspace_preinject = workspace_preinject
            ctx.run_script_preinject = run_script_preinject
            ctx.exact_need = exact_need
