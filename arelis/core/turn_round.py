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
import time
from types import SimpleNamespace
from typing import Any

from arelis.core.agent_loop import (
    _HIDE_WANDER_FOR,
    _MAX_TOOL_NUDGES,
    _WRITE_AFTER_PAGE_NOTICE,
    _hide_daily_wander,
    _is_ollama_object_400,
    _native_tool_call,
    _normalize_ollama_messages,
    _offer_expected,
    _StoppedError,
    _tool_followup_fallback,
)
from arelis.core.email_complete import (
    looks_like_bare_confirm,
    rewrite_schedule_calls,
)
from arelis.core.events import Event, EventType
from arelis.core.failure_copy import should_nudge_write_after_page
from arelis.core.json_tools import (
    extract_native_tool_calls,
    parse_fallback_payload,
    strip_thinking_text,
)
from arelis.core.look import LOOK_TOOL_SUBSET
from arelis.core.loop_helpers import (
    _MALFORMED_CALL_NOTICE,
)
from arelis.core.no_call_finish import NUDGE as FINISH_NUDGE
from arelis.core.no_call_finish import run_finish_steps
from arelis.core.no_call_steps import NUDGE, run_inject_steps
from arelis.core.preflight import (
    rewrite_browser_calls,
)
from arelis.core.sms_complete import (
    looks_like_stale_sms_skip,
)
from arelis.core.tool_subset import (
    filter_tool_names,
    is_research_mode,
    turn_round_budget,
)
from arelis.core.turn_context import TurnContext
from arelis.core.turn_dispatch import dispatch_calls
from arelis.llm.errors import classify_ollama_failure, is_vram_failure


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

    Inject and finish decisions live in ``no_call_steps`` / ``no_call_finish``.
    This coordinator stays long because ~40 rebound locals still have to
    unpack and write back on every early return — splitting that again
    is a new contract, not a table.
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
                        offer_tools = False
                        ollama_tools = []
                        ctx.offer_tools = False
                        ctx.ollama_tools = []
                        ctx.tool_names.clear()
                        tool_names = ctx.tool_names
                        await loop._retract()
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {
                                "role": "user",
                                "content": _WRITE_AFTER_PAGE_NOTICE,
                            }
                        )
                        await loop.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        "empty after page; asking for a write-up"
                                    )
                                },
                            )
                        )
                        return False
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
            hit = await run_inject_steps(loop, ctx, r)
            calls = r.calls
            tool_calls = r.tool_calls
            messages = r.messages
            available = r.available
            visible = r.visible
            tool_names = r.tool_names
            ollama_tools = r.ollama_tools
            if hit == NUDGE:
                return False

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
                r.wants_fresh_page = wants_fresh_page
                r.content = content
                r.messages = messages
                r.tool_names = tool_names
                r.available = available
                r.visible = visible
                r.available_all = available_all
                r.ollama_tools = ollama_tools
                r.offer_tools = offer_tools
                r.agent_cfg = agent_cfg
                r.sources = sources
                r.ledger = ledger
                r.exact_need = exact_need
                r.evidence_gate = evidence_gate
                r.numeric_gate = numeric_gate
                r.research_dual = research_dual
                r.research_mode = research_mode
                r.research_min_sources = research_min_sources
                r.round_ms = round_ms
                r.streamed = streamed
                hit = await run_finish_steps(loop, ctx, r, round_i)
                available = r.available
                visible = r.visible
                tool_names = r.tool_names
                ollama_tools = r.ollama_tools
                messages = r.messages
                if hit == FINISH_NUDGE:
                    return False
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
            loop.max_rounds = max(
                loop.max_rounds,
                turn_round_budget(
                    role, text, agent_cfg, loop._default_max_rounds
                ),
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
            ctx.email_sent_ok
            or ctx.agenda_create_ok
            or bool(sms_sent)
            or ctx.page_write_nudge_used
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

