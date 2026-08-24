"""Finish-path force gates, as data rather than six copy-pasted blocks.

Each gate is the same shape: if the ask needs a tool, the ledger has no
warrant, the tool is offered, and this gate has not already fired, retract
the draft answer and force the call. They lived inline in AgentLoop._run
because each one closed over its own ``*_nudge_used`` flag. TurnContext
owns the flags, so the loop can be a table.

Gates that are not this shape (evidence, quote-first, dual-hit, file-answer,
the hard refuse) stay as methods on the loop — they have extra arguments
or they end the turn. Putting those in the table would just hide a
different function behind a flag.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from arelis.core.claims import (
    ExactnessNeed,
    cas_force_notice,
    catalog_force_notice,
    document_force_notice,
    math_force_notice,
    plot_force_notice,
    units_force_notice,
    diagnostics_force_notice,
)
from arelis.core.events import Event, EventType
from arelis.core.turn_context import TurnContext


@dataclass(frozen=True)
class ForceGate:
    """One 'you answered without the tool that would make this true' rule."""

    name: str
    ledger_kind: str
    tool: str
    need_attr: str
    flag: str
    notice: Callable[[], str]
    thinking: str
    timer_gate: str
    require_numeric: bool = True

    def needed(self, exact_need: ExactnessNeed) -> bool:
        return bool(getattr(exact_need, self.need_attr))


FORCE_GATES: tuple[ForceGate, ...] = (
    ForceGate(
        name="math",
        ledger_kind="calc",
        tool="calculator",
        need_attr="needs_calculator",
        flag="math_nudge_used",
        notice=math_force_notice,
        thinking="exactness  math without calculator; forcing tool",
        timer_gate="math",
    ),
    ForceGate(
        name="symbolic",
        ledger_kind="cas",
        tool="cas",
        need_attr="needs_cas",
        flag="cas_nudge_used",
        notice=cas_force_notice,
        thinking="exactness  symbolic without cas; forcing tool",
        timer_gate="symbolic",
    ),
    ForceGate(
        name="units",
        ledger_kind="units",
        tool="units",
        need_attr="needs_units",
        flag="units_nudge_used",
        notice=units_force_notice,
        thinking="exactness  units without tool; forcing tool",
        timer_gate="units",
    ),
    ForceGate(
        name="plot",
        ledger_kind="plot",
        tool="plot",
        need_attr="needs_plot",
        flag="plot_nudge_used",
        notice=plot_force_notice,
        thinking="exactness  plot without file; forcing tool",
        timer_gate="plot",
    ),
    ForceGate(
        name="document",
        ledger_kind="document",
        tool="document",
        need_attr="needs_document",
        flag="document_nudge_used",
        notice=document_force_notice,
        thinking="exactness  document without file; forcing tool",
        timer_gate="document",
        require_numeric=False,
    ),
    ForceGate(
        name="diagnostics",
        ledger_kind="diagnostics",
        tool="diagnostics",
        need_attr="needs_diagnostics",
        flag="diagnostics_nudge_used",
        notice=diagnostics_force_notice,
        thinking="exactness  diagnostics without pytest; forcing tool",
        timer_gate="diagnostics",
        require_numeric=False,
    ),
    ForceGate(
        name="catalog",
        ledger_kind="catalog",
        tool="catalog",
        need_attr="needs_catalog",
        flag="catalog_nudge_used",
        notice=catalog_force_notice,
        thinking="exactness  catalog without fetch; forcing tool",
        timer_gate="catalog",
    ),
)

# Kinds the generic evidence gate must not double-force — each has a row above.
FORCE_GATE_KINDS = frozenset(
    {
        "math",
        "weather",
        "symbolic",
        "units",
        "plot",
        "catalog",
        "document",
        "diagnostics",
    }
)


async def apply_force_gates(
    loop: Any,
    ctx: TurnContext,
    content: str,
    *,
    refused: bool,
) -> ForceGate | None:
    """Fire the first matching force gate. None means the answer may proceed.

    ``refused`` is passed in so the caller decides what a refusal looks like;
    this module does not import the hedge detector.
    """
    if refused:
        return None
    for gate in FORCE_GATES:
        if getattr(ctx, gate.flag):
            continue
        if gate.require_numeric and not ctx.numeric_gate:
            continue
        if not gate.needed(ctx.exact_need):
            continue
        if ctx.ledger.has_ok(gate.ledger_kind):
            continue
        if gate.tool not in ctx.tool_names:
            continue
        setattr(ctx, gate.flag, True)
        await loop._retract()
        ctx.messages.append({"role": "assistant", "content": content})
        ctx.messages.append({"role": "user", "content": gate.notice()})
        await loop.bus.publish(
            Event(EventType.THINKING, {"text": gate.thinking})
        )
        if loop._timer is not None:
            loop._timer.mark("exactness", gate=gate.timer_gate, action="force")
        return gate
    return None
