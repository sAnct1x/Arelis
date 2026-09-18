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
    _MAX_TOOL_NUDGES,
    _WRITE_AFTER_ALGEBRA_NOTICE,
    _WRITE_AFTER_PAGE_NOTICE,
    _WRITE_AFTER_THINK_NOTICE,
    _is_ollama_object_400,
    _native_tool_call,
    _normalize_ollama_messages,
    _StoppedError,
    _tool_followup_fallback,
)
from arelis.core.email_complete import (
    looks_like_bare_confirm,
    rewrite_schedule_calls,
)
from arelis.core.events import Event, EventType
from arelis.core.failure_copy import (
    should_nudge_write_after_algebra,
    should_nudge_write_after_page,
)
from arelis.core.json_tools import (
    extract_native_tool_calls,
    parse_fallback_payload,
    strip_thinking_text,
)
from arelis.core.loop_helpers import (
    _MALFORMED_CALL_NOTICE,
)
from arelis.core.no_call_finish import NUDGE as FINISH_NUDGE
from arelis.core.no_call_finish import run_finish_steps
from arelis.core.no_call_steps import NUDGE, run_inject_steps
from arelis.core.preflight import (
    rewrite_browser_calls,
)
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
from arelis.core.turn_scratch import RoundScratch, strip_tool_schemas
from arelis.llm.errors import classify_ollama_failure, is_vram_failure
from arelis.tools.pdf_pages import ink_vision_walk


def _write_round(ctx: TurnContext, r: RoundScratch) -> None:
    """Hand the next round the surface this one decided.

    These are the fields a step rebinds on ``r`` that the *next* round
    reads off ``ctx``. Everything else is already the same object on both
    (sets, the ledger, the drafts) or dies with the scratch.

    Goes through ``r``, not a local snapshot. A snapshot taken before a
    raise is how a wander-hide that already landed on the scratch could
    still be undone when ``dispatch_calls`` blew up — next round would
    offer web_search again.
    """
    ctx.available = r.available
    ctx.visible = r.visible
    ctx.ollama_tools = r.ollama_tools
    ctx.offer_tools = r.offer_tools
    ctx.research_mode = r.research_mode
    ctx.sms_preinject = r.sms_preinject
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
    time this returns — or raises.
    """
    if not r.calls:
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

        if not r.content and not ctx.fallback_mode:
            # Qwen3.5 often puts the wrap-up in thinking and leaves
            # chat content empty. Native calling still worked — a tool
            # already ran — so do not enter the sticky-note protocol
            # and do not ship the "empty reply / model unloaded" notice.
            # Tools may already be stripped (agenda/SMS/email wrap-up).
            # A long scrape/search must not become the chat line —
            # ask once for a write-up. Short facts (price, agenda)
            # still ship from the tool result.
            if ctx.last_ok_tool_out:
                if (
                    not ctx.page_write_nudge_used
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
                            "content": _WRITE_AFTER_ALGEBRA_NOTICE,
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
                await loop.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": ("empty after tool; answering from result")},
                    )
                )
                await loop._finish(
                    _tool_followup_fallback(
                        ctx.last_ok_tool_out,
                        ctx.last_ok_tool_name,
                        ask=ctx.text,
                    ),
                    r.sources,
                    streamed="",
                    passthrough_tool=ctx.last_ok_tool_name,
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
            if r.ollama_tools and loop.json_fallback:
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
                "you set — no need to fire it now.",
                r.sources,
                streamed="",
            )
            return True

        before_browser = list(r.calls)
        r.calls = rewrite_browser_calls(r.calls, text=r.text)
        if r.calls != before_browser:
            r.tool_calls = [_native_tool_call(n, a) for n, a in r.calls]
            await loop.bus.publish(
                Event(
                    EventType.THINKING,
                    {"text": "rewrite  invented browser action → snapshot"},
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
    ollama_tools = ctx.ollama_tools
    research_mode = ctx.research_mode
    exact_need = ctx.exact_need
    sms_preinject = ctx.sms_preinject
    r: RoundScratch | None = None
    try:
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
            ollama_tools = loop.tools.ollama_tools(visible)
            ctx.tool_names.clear()
            ctx.tool_names.update(visible)
            ctx.ollama_tools = ollama_tools
            ctx.available = set(available)
            ctx.visible = set(visible)
            ctx.research_mode = research_mode
            tool_names = ctx.tool_names

        if round_i > 1 and (
            ctx.email_sent_ok
            or ctx.agenda_create_ok
            or bool(ctx.sms_sent)
            or ctx.page_write_nudge_used
            or ctx.algebra_write_nudge_used
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
            await loop.bus.publish(Event(EventType.STATUS, {"message": "Calling send_sms…"}))
            if loop._timer is not None:
                loop._timer.mark("exactness", gate="sms_force", action="preinject")
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
                    base_url=str((loop.config.get("ollama") or {}).get("base_url") or ""),
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
                            {"text": (f"native tools failed ({exc}); JSON fallback")},
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
                            {"text": ("research_report ready; answering from artifact")},
                        )
                    )
                    await loop._finish(
                        _tool_followup_fallback(
                            ctx.last_ok_tool_out,
                            ctx.last_ok_tool_name,
                            ask=ctx.text,
                        ),
                        sources,
                        streamed="",
                        passthrough_tool=ctx.last_ok_tool_name,
                    )
                    return True
                if ctx.last_ok_tool_out and _is_ollama_object_400(exc):
                    await loop.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": ("ollama 400 after tool; answering from result")},
                        )
                    )
                    await loop._finish(
                        _tool_followup_fallback(
                            ctx.last_ok_tool_out,
                            ctx.last_ok_tool_name,
                            ask=ctx.text,
                        ),
                        sources,
                        streamed="",
                        passthrough_tool=ctx.last_ok_tool_name,
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
            ollama_tools=ollama_tools,
            messages=messages,
            sms_preinject=sms_preinject,
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
            ctx.ollama_tools = ollama_tools
            ctx.offer_tools = offer_tools
            ctx.research_mode = research_mode
            ctx.sms_preinject = sms_preinject
            ctx.exact_need = exact_need
