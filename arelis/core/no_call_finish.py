"""Finish a turn that made no tool call.

The model already chose not to call. This path does not invent a call
from the user's words. It can name the screen theme, refuse an exact
claim that has no warrant, and ask again for a tool the user named
that has not run and still has no evidence.
"""

from __future__ import annotations

from typing import Any

from arelis.core.agent_loop import _MAX_TOOL_NUDGES, theme_reply_if_needed
from arelis.core.claims import answer_looks_like_refusal
from arelis.core.events import Event, EventType
from arelis.core.failure_copy import (
    _algebra_was_asked,
    chat_followup_from_tool,
    reply_states_algebra_result,
    should_nudge_write_after_algebra,
)
from arelis.core.loop_helpers import _exactness_finish_refuse, _turn_requested_tools
from arelis.core.turn_context import TurnContext
from arelis.core.turn_scratch import (
    RoundScratch,
    named_tools_owed_runnable,
    negated_tool_mentions,
)

NUDGE = "nudge"
FINISH = "finish"


def _still_owed(
    owed: list[str],
    *,
    kinds: tuple[str, ...],
    missing: list[str],
    used: set[str],
) -> list[str]:
    """Named tools that have not run and still have no evidence.

    ``owed`` is already the not-yet-run, still-runnable, not-negated set.
    When the tool name is one of this turn's evidence kinds, a successful
    warrant for that kind means it is not owed. A name that is not a kind
    on this turn stays owed until the tool runs. Document beside a weather
    ask is that case: exactness only tagged weather, and the file is still
    missing.

    A shorter name is not still owed when a longer tool that extends it
    already ran. "grayscale image" mentions image after image_edit ran.
    That is the edit, not a second tool.
    """
    kind_set = set(kinds)
    missing_set = set(missing)
    kept: list[str] = []
    for name in owed:
        if name in kind_set and name not in missing_set:
            continue
        if any(other.startswith(name + "_") for other in used):
            continue
        kept.append(name)
    return kept


async def _ship_algebra_result_if_missing(
    loop: Any, ctx: TurnContext, r: RoundScratch
) -> bool:
    """Ship the calculator line when chat is filler without the number.

    This does not pick a tool. The calculator already ran. A filler that
    leaves the number out is replaced with the plain result.
    """
    name = ctx.last_ok_tool_name
    out = ctx.last_ok_tool_out
    if not (
        out
        and should_nudge_write_after_algebra(name)
        and _algebra_was_asked(ctx.text)
        and not answer_looks_like_refusal(r.content)
        and not reply_states_algebra_result(r.content, name, out)
    ):
        return False
    line = chat_followup_from_tool(name, out, ask=ctx.text)
    await loop._retract()
    await loop.bus.publish(
        Event(
            EventType.THINKING,
            {"text": "algebra result missing from chat; shipping a plain answer"},
        )
    )
    await loop._finish(line, r.sources, streamed="")
    return True


async def run_finish_steps(loop: Any, ctx: TurnContext, r: RoundScratch, round_i: int) -> str:
    # Hold while a tool the user named has not run and its evidence is
    # still missing. Turn state decides this. The native flag does not.
    # Negation and the nudge cap still do. This does not invent a call.
    owed = named_tools_owed_runnable(loop, ctx, r.fail_counts)
    negated = negated_tool_mentions(ctx.text, owed)
    owed = [n for n in owed if n not in negated]
    kinds = tuple(getattr(ctx.exact_need, "kinds", ()) or ())
    missing = ctx.ledger.missing_kinds(kinds)
    used = {str(name) for name in (getattr(loop, "tools_used", ()) or ())}
    owed = _still_owed(owed, kinds=kinds, missing=missing, used=used)
    if owed and ctx.nudges < _MAX_TOOL_NUDGES:
        ctx.nudges += 1
        await loop._retract()
        r.messages.append({"role": "assistant", "content": r.content})
        r.messages.append(
            {
                "role": "user",
                "content": (
                    "You still need to call these tools the user named: "
                    + ", ".join(owed)
                    + ". Call them now before answering."
                ),
            }
        )
        await loop.bus.publish(
            Event(
                EventType.THINKING,
                {"text": "named tools owed; asking to continue"},
            )
        )
        return NUDGE
    if await _ship_algebra_result_if_missing(loop, ctx, r):
        return FINISH
    fixed = theme_reply_if_needed(ctx.text, r.content)
    if fixed is not None:
        await loop._retract()
        await loop.bus.publish(
            Event(EventType.THINKING, {"text": "theme ask; saying the screen theme"})
        )
        if loop._timer is not None:
            loop._timer.mark("theme", action="name")
        await loop._finish(fixed, r.sources, streamed="")
        return FINISH
    refuse = _exactness_finish_refuse(
        r.content,
        exact_need=ctx.exact_need,
        ledger=ctx.ledger,
        numeric_gate=ctx.numeric_gate,
        evidence_gate=ctx.evidence_gate,
        send_path=ctx.is_send_path(loop._expected_tools),
        declined_tools=ctx.declined_tools,
        declined_calls=ctx.declined_calls,
        requested_tools=_turn_requested_tools(loop, ctx),
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
