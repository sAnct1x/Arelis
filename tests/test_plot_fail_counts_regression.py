"""Regression test for plot tool fail_counts bug (C03 matrix item).

The bug: fail_counts >= 2 check blocks plot calls even when the failures
were NOT from duplicate/same calls, but from legitimately different attempts
in a multi-tool chain. This caused C03 (python > plot > document) to fail
in the demo app but pass in the matrix.

Root cause: fail_counts persists across all rounds in a turn and blocks
based solely on tool name + args, without considering whether the call is
actually a retry of the same work or a new legitimate call in a chain.
"""

from __future__ import annotations

import pytest

from arelis.core.turn_confirm import SKIP, confirm_call
from arelis.core.turn_context import TurnContext


class _FakeLoop:
    def __init__(self):
        self.bus = None
        self.tools = None
        self._expected_tools = set()
        self.tools_used = set()
        self.config = {}
        self._timer = None

    class _FakeTools:
        def needs_confirm(self, *args, **kwargs):
            return False

        def summarize_call(self, name, args):
            return f"{name}({args})"

    def __init__(self):
        self.tools = self._FakeTools()
        self._expected_tools = set()
        self.tools_used = set()
        self.config = {}
        self._timer = None


class _FakeBus:
    async def publish(self, event):
        pass


@pytest.mark.no_ui
@pytest.mark.asyncio
async def test_plot_not_blocked_after_python_failures():
    """Plot should not be blocked just because python failed twice.

    This is the C03 scenario:
    1. Model calls python(code="...") - works
    2. Model calls plot(xs="...", ys="...") with bad args - fails
    3. Model retries plot with same bad args - fails again (fail_counts=2)
    4. Model calls plot with DIFFERENT args (corrected) - should work, but gets blocked

    The bug: fail_counts >= 2 blocks the third plot call even though
    it has different arguments and should be allowed to proceed.
    """
    loop = _FakeLoop()
    loop.bus = _FakeBus()
    ctx = TurnContext(text="compute squares and plot them", role="fast")

    messages: list[dict] = []
    fail_counts: dict[str, int] = {}
    skip_counts: dict[str, int] = {}
    tool_names = {"python", "plot", "document"}

    def drop_wander(name: str) -> None:
        pass

    # Round 1: python succeeds (not testing this, just context)
    # Round 2: plot with missing ys - should fail
    from arelis.core.loop_helpers import _tool_fail_fingerprint

    bad_args_1 = {"xs": "1,2,3", "ys": ""}  # Missing ys
    call_fp_1 = _tool_fail_fingerprint("plot", bad_args_1)

    # Simulate the tool actually failing (would happen in execute_call)
    fail_counts[call_fp_1] = 1

    # Round 3: plot retry with same bad args - should fail again
    action_2, _, fp_2 = await confirm_call(
        loop,
        ctx,
        "plot",
        bad_args_1,
        text=ctx.text,
        fail_counts=fail_counts,
        skip_counts=skip_counts,
        messages=messages,
        tool_names=tool_names,
        drop_wander=drop_wander,
    )
    # Simulate second failure
    fail_counts[call_fp_1] = 2

    # Round 4: plot with CORRECTED args - should NOT be blocked
    good_args = {"xs": "1,2,3,4,5,6,7,8", "ys": "1,4,9,16,25,36,49,64"}
    call_fp_good = _tool_fail_fingerprint("plot", good_args)

    # The bug: this call gets blocked because fail_counts[call_fp_1] >= 2
    # even though call_fp_good != call_fp_1
    action_3, _, fp_3 = await confirm_call(
        loop,
        ctx,
        "plot",
        good_args,
        text=ctx.text,
        fail_counts=fail_counts,
        skip_counts=skip_counts,
        messages=messages,
        tool_names=tool_names,
        drop_wander=drop_wander,
    )

    # This should NOT be SKIP - the args are different
    assert action_3 != SKIP, (
        f"plot with corrected args should not be blocked. "
        f"fp_1={call_fp_1}, fp_good={call_fp_good}"
    )


@pytest.mark.no_ui
@pytest.mark.asyncio
async def test_plot_correctly_blocked_for_same_args():
    """Plot SHOULD be blocked after failing twice with the SAME args."""
    loop = _FakeLoop()
    loop.bus = _FakeBus()
    ctx = TurnContext(text="plot this", role="fast")

    messages: list[dict] = []
    fail_counts: dict[str, int] = {}
    skip_counts: dict[str, int] = {}
    tool_names = {"plot"}

    def drop_wander(name: str) -> None:
        pass

    from arelis.core.loop_helpers import _tool_fail_fingerprint

    # Same bad args every time
    bad_args = {"xs": "", "ys": ""}
    call_fp = _tool_fail_fingerprint("plot", bad_args)

    # First failure
    fail_counts[call_fp] = 1

    # Second attempt with same args
    action_2, _, _ = await confirm_call(
        loop,
        ctx,
        "plot",
        bad_args,
        text=ctx.text,
        fail_counts=fail_counts,
        skip_counts=skip_counts,
        messages=messages,
        tool_names=tool_names,
        drop_wander=drop_wander,
    )

    # Simulate second failure
    fail_counts[call_fp] = 2

    # Third attempt with SAME args - should be blocked
    action_3, _, _ = await confirm_call(
        loop,
        ctx,
        "plot",
        bad_args,
        text=ctx.text,
        fail_counts=fail_counts,
        skip_counts=skip_counts,
        messages=messages,
        tool_names=tool_names,
        drop_wander=drop_wander,
    )

    # This SHOULD be SKIP - same args failed twice
    assert action_3 == SKIP, "plot should be blocked after failing twice with same args"
