"""Finish-path nudges after inject steps left ``r.calls`` empty.

Order matches the original tail of ``apply_no_call_path``. First hit wins.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from arelis.core.agent_loop import (
    _FILE_ANSWER_TOOLS,
    _JS_SHELL_BROWSER_NOTICE,
    _SCRAPE_AFTER_SEARCH_NOTICE,
    _WEB_TOOLS,
)
from arelis.core.claims import (
    answer_looks_like_ack_only,
    answer_looks_like_refusal,
    evidence_force_notice,
    file_answer_force_notice,
    unsupported_exactness_reply,
)
from arelis.core.events import Event, EventType
from arelis.core.evidence import dual_hit_notice, quote_first_notice
from arelis.core.gates import FORCE_GATE_KINDS, apply_force_gates
from arelis.core.loop_helpers import _answer_has_quote_span, _exactness_finish_refuse
from arelis.core.plan_nudge import plan_progress_notice
from arelis.core.turn_context import TurnContext

SKIP = "skip"
NUDGE = "nudge"
FINISH = "finish"

StepFn = Callable[[Any, TurnContext, Any, int], Awaitable[str]]


async def try_scrape_after_search(loop: Any, ctx: TurnContext, r: Any, round_i: int) -> str:
    if not (
        bool(r.agent_cfg.get("scrape_after_search", True))
        and r.wants_fresh_page
        and not ctx.scrape_nudge_used
        and "web_search" in loop.tools_used
        and "browser" not in loop._expected_tools
        and "browser" not in loop.tools_used
        and not (loop.tools_used & _WEB_TOOLS)
        and ("scrape" in r.tool_names or "research_report" in r.tool_names)
    ):
        return SKIP
    ctx.scrape_nudge_used = True
    await loop._retract()
    r.messages.append({"role": "assistant", "content": r.content})
    r.messages.append({"role": "user", "content": _SCRAPE_AFTER_SEARCH_NOTICE})
    await loop.bus.publish(
        Event(EventType.THINKING, {"text": "search without scrape; asking for a page read"})
    )
    if loop._timer is not None:
        loop._timer.mark("exactness", gate="scrape_after_search", action="nudge")
    return NUDGE


async def try_js_shell_browser(loop: Any, ctx: TurnContext, r: Any, round_i: int) -> str:
    if not (
        bool(r.agent_cfg.get("browser_after_js_shell", True))
        and ctx.js_shell_url
        and not ctx.js_shell_nudge_used
        and "browser" in r.available_all
        and "browser" not in loop.tools_used
        and not (loop._expected_tools & {"weather", "send_sms", "send_email"})
    ):
        return SKIP
    ctx.js_shell_nudge_used = True
    if "browser" not in r.tool_names:
        r.visible = set(r.visible) | {"browser"}
        r.available = set(r.available) | {"browser"}
        ctx.tool_names.clear()
        ctx.tool_names.update(r.visible)
        r.tool_names = ctx.tool_names
        if r.offer_tools:
            r.ollama_tools = loop.tools.ollama_tools(r.visible)
    await loop._retract()
    r.messages.append({"role": "assistant", "content": r.content})
    r.messages.append(
        {"role": "user", "content": _JS_SHELL_BROWSER_NOTICE.format(url=ctx.js_shell_url)}
    )
    await loop.bus.publish(
        Event(EventType.THINKING, {"text": "js shell; asking to open the page in her window"})
    )
    if loop._timer is not None:
        loop._timer.mark("exactness", gate="browser_after_js_shell", action="nudge")
    return NUDGE


async def try_plan_progress(loop: Any, ctx: TurnContext, r: Any, round_i: int) -> str:
    if not (
        bool(r.agent_cfg.get("plan_progress", True))
        and loop._active_plan is not None
        and not ctx.plan_progress_used
        and not answer_looks_like_refusal(r.content)
    ):
        return SKIP
    progress = plan_progress_notice(
        loop._active_plan,
        loop.tools_used,
        available_tools=r.tool_names,
    )
    if not progress:
        return SKIP
    ctx.plan_progress_used = True
    await loop._retract()
    r.messages.append({"role": "assistant", "content": r.content})
    r.messages.append({"role": "user", "content": progress})
    await loop.bus.publish(
        Event(EventType.THINKING, {"text": f"plan_progress  {loop._active_plan.id}"})
    )
    if loop._timer is not None:
        loop._timer.mark("plan_progress", plan=loop._active_plan.id)
    return NUDGE


async def try_force_gates(loop: Any, ctx: TurnContext, r: Any, round_i: int) -> str:
    if await apply_force_gates(
        loop, ctx, r.content, refused=answer_looks_like_refusal(r.content)
    ):
        return NUDGE
    return SKIP


async def try_evidence(loop: Any, ctx: TurnContext, r: Any, round_i: int) -> str:
    if not (
        r.evidence_gate
        and r.exact_need.kinds
        and not ctx.evidence_nudge_used
        and not answer_looks_like_refusal(r.content)
    ):
        return SKIP
    missing = r.ledger.missing_kinds(r.exact_need.kinds)
    missing = [k for k in missing if k not in FORCE_GATE_KINDS]
    if not missing:
        return SKIP
    ctx.evidence_nudge_used = True
    await loop._retract()
    r.messages.append({"role": "assistant", "content": r.content})
    r.messages.append({"role": "user", "content": evidence_force_notice()})
    await loop.bus.publish(
        Event(
            EventType.THINKING,
            {"text": "phase=verify missing-warrants " + ",".join(missing)},
        )
    )
    if loop._timer is not None:
        loop._timer.mark("verify", gate="evidence", missing=",".join(missing))
    return NUDGE


async def try_file_answer(loop: Any, ctx: TurnContext, r: Any, round_i: int) -> str:
    if not (
        not ctx.file_answer_nudge_used
        and (loop.tools_used & _FILE_ANSWER_TOOLS)
        and answer_looks_like_ack_only(r.content)
        and not answer_looks_like_refusal(r.content)
    ):
        return SKIP
    ctx.file_answer_nudge_used = True
    await loop._retract()
    r.messages.append({"role": "assistant", "content": r.content})
    r.messages.append({"role": "user", "content": file_answer_force_notice()})
    await loop.bus.publish(Event(EventType.THINKING, {"text": "phase=verify file-answer"}))
    if loop._timer is not None:
        loop._timer.mark("verify", gate="file_answer", action="nudge")
    return NUDGE


async def try_quote_first(loop: Any, ctx: TurnContext, r: Any, round_i: int) -> str:
    if not (
        r.evidence_gate
        and r.ledger.has_ok("web")
        and not ctx.quote_nudge_used
        and r.exact_need.needs_web_evidence
        and not _answer_has_quote_span(r.content)
        and not answer_looks_like_refusal(r.content)
    ):
        return SKIP
    ctx.quote_nudge_used = True
    await loop._retract()
    r.messages.append({"role": "assistant", "content": r.content})
    quotes = r.ledger.quote_lines()
    notice = quote_first_notice()
    if quotes:
        notice += "\nEvidence spans:\n" + "\n".join(quotes)
    r.messages.append({"role": "user", "content": notice})
    await loop.bus.publish(Event(EventType.THINKING, {"text": "phase=verify quote-first"}))
    if loop._timer is not None:
        loop._timer.mark("verify", gate="quote", action="nudge")
    return NUDGE


async def try_research_dual(loop: Any, ctx: TurnContext, r: Any, round_i: int) -> str:
    web_ok_n = len(r.ledger.ok_web_sources()) if r.ledger.has_ok("web") else 0
    if not (
        r.research_dual
        and r.research_mode
        and r.exact_need.needs_web_evidence
        and web_ok_n < r.research_min_sources
        and not answer_looks_like_refusal(r.content)
    ):
        return SKIP
    if not ctx.dual_hit_nudge_used and web_ok_n >= 1:
        ctx.dual_hit_nudge_used = True
        await loop._retract()
        r.messages.append({"role": "assistant", "content": r.content})
        r.messages.append({"role": "user", "content": dual_hit_notice()})
        await loop.bus.publish(Event(EventType.THINKING, {"text": "phase=verify dual-hit"}))
        if loop._timer is not None:
            loop._timer.mark("verify", gate="dual_hit", action="nudge")
        return NUDGE
    if web_ok_n == 0:
        await loop._retract()
        thin = unsupported_exactness_reply(["web"])
        if loop._timer is not None:
            loop._timer.mark(
                "exactness",
                gate="research_min_sources",
                action="refuse",
                have=web_ok_n,
                need=r.research_min_sources,
            )
        await loop._finish(thin, [], streamed="")
        return FINISH
    if ctx.dual_hit_nudge_used and web_ok_n >= 1:
        if loop._timer is not None:
            loop._timer.mark(
                "exactness",
                gate="dual_hit",
                action="soft_fail",
                have=web_ok_n,
                need=r.research_min_sources,
            )
        return SKIP
    return SKIP


FINISH_STEPS: tuple[StepFn, ...] = (
    try_scrape_after_search,
    try_js_shell_browser,
    try_plan_progress,
    try_force_gates,
    try_evidence,
    try_file_answer,
    try_quote_first,
    try_research_dual,
)


async def run_finish_steps(loop: Any, ctx: TurnContext, r: Any, round_i: int) -> str:
    for step in FINISH_STEPS:
        hit = await step(loop, ctx, r, round_i)
        if hit != SKIP:
            return hit
    refuse = _exactness_finish_refuse(
        r.content,
        exact_need=ctx.exact_need,
        ledger=ctx.ledger,
        numeric_gate=ctx.numeric_gate,
        evidence_gate=ctx.evidence_gate,
        send_path=ctx.is_send_path(loop._expected_tools),
    )
    if refuse is None:
        refuse = loop._look_refuse(r.content)
    if refuse is not None:
        await loop._retract()
        await loop.bus.publish(Event(EventType.THINKING, {"text": "phase=verify refuse"}))
        if loop._timer is not None:
            loop._timer.mark("verify", gate="refuse", kinds=",".join(r.exact_need.kinds))
        await loop._finish(refuse, r.sources, streamed="")
        return FINISH
    if loop._timer is not None:
        loop._timer.mark("round", n=round_i, ms=r.round_ms, kind="final", calls=0)
        if r.exact_need.kinds:
            loop._timer.mark(
                "exactness",
                gate="pass",
                kinds=",".join(r.exact_need.kinds),
                warrants=len(r.ledger),
            )
    await loop._finish(r.content, r.sources, streamed=r.streamed)
    return FINISH
