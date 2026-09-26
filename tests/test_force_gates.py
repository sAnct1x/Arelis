"""The six exactness force gates are one table, not six copies.

They used to be pasted inline in AgentLoop._run, each closing over its own
flag. A new tool that needed the same rule had to be taught in a seventh
block, or it was only refused at the finish and never forced. The table is
the rule; these tests hold the shape that would silently drop a row.
"""

from __future__ import annotations

from typing import Any

import pytest

from arelis.core.claims import ExactnessNeed
from arelis.core.gates import FORCE_GATE_KINDS, FORCE_GATES, apply_force_gates
from arelis.core.turn_context import TurnContext


class _Loop:
    def __init__(self) -> None:
        self.retracts = 0
        self.published: list[Any] = []
        self._timer = None
        self.bus = self

    async def _retract(self) -> None:
        self.retracts += 1

    async def publish(self, event: Any) -> None:
        self.published.append(event)


def test_every_force_gate_has_a_unique_flag() -> None:
    flags = [g.flag for g in FORCE_GATES]
    assert len(flags) == len(set(flags))


def test_every_force_gate_flag_exists_on_the_context() -> None:
    ctx = TurnContext(text="hi", role="fast")
    for gate in FORCE_GATES:
        assert hasattr(ctx, gate.flag)
        assert getattr(ctx, gate.flag) is False


def test_document_does_not_require_the_numeric_switch() -> None:
    """The original block did not gate document on numeric_gate. Keep that."""
    doc = next(g for g in FORCE_GATES if g.name == "document")
    assert doc.require_numeric is False
    assert all(
        g.require_numeric
        for g in FORCE_GATES
        if g.name not in {"document", "diagnostics"}
    )


def test_the_evidence_filter_knows_every_dedicated_kind() -> None:
    """Kinds with their own force row must not also fire the generic evidence gate."""
    for gate in FORCE_GATES:
        assert gate.name in FORCE_GATE_KINDS or gate.ledger_kind in FORCE_GATE_KINDS


def test_needed_reads_the_exactness_field() -> None:
    empty = ExactnessNeed(False, False, False, False)
    math = ExactnessNeed(True, False, False, False)
    gate = next(g for g in FORCE_GATES if g.name == "math")
    assert not gate.needed(empty)
    assert gate.needed(math)


@pytest.mark.asyncio
async def test_a_matching_gate_fires_once_then_stays_quiet() -> None:
    ctx = TurnContext(
        text="what is 2+2",
        role="fast",
        exact_need=ExactnessNeed(True, False, False, False),
        tool_names={"calculator"},
    )
    loop = _Loop()
    first = await apply_force_gates(loop, ctx, "4", refused=False)
    assert first is not None and first.name == "math"
    assert ctx.math_nudge_used
    assert loop.retracts == 1
    assert any(m.get("role") == "user" for m in ctx.messages)

    second = await apply_force_gates(loop, ctx, "4", refused=False)
    assert second is None
    assert loop.retracts == 1


@pytest.mark.asyncio
async def test_a_refusal_is_not_forced() -> None:
    ctx = TurnContext(
        text="what is 2+2",
        role="fast",
        exact_need=ExactnessNeed(True, False, False, False),
        tool_names={"calculator"},
    )
    fired = await apply_force_gates(_Loop(), ctx, "I don't know", refused=True)
    assert fired is None
    assert not ctx.math_nudge_used


@pytest.mark.asyncio
async def test_diagnostics_gate_fires_when_pytest_was_skipped() -> None:
    ctx = TurnContext(
        text="run diagnostics",
        role="fast",
        exact_need=ExactnessNeed(
            False, False, False, False, needs_diagnostics=True
        ),
        tool_names={"diagnostics"},
    )
    first = await apply_force_gates(_Loop(), ctx, "everything is fine", refused=False)
    assert first is not None and first.name == "diagnostics"
    assert ctx.diagnostics_nudge_used
    second = await apply_force_gates(_Loop(), ctx, "everything is fine", refused=False)
    assert second is None
