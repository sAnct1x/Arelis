""" "The tests pass" must never be something she remembers.

Found 2026-09-17 by generalising the `document` finding: `apply_force_gates`
only nudges, so every row in that table wants an inject behind it. This row is
the worst of them. A model that keeps answering in prose produced

    "Yes, the tests pass — the suite is green."

with **no tool call at all**. That is the top complaint in the audit — a
confidently wrong answer the user will act on — in one line.

Two separate bugs, and the detection one is larger. `_DIAGNOSTICS_ASK` matched
the literal phrase `run diagnostics` and nothing else, so *"run the tests"*,
*"run pytest"*, *"run the test suite"* and *"do the tests pass?"* all armed
nothing. Same class as `_TASKS_UTTERANCE` and the day-planning gap: a regex
written for the phrasing a developer types, not the one a person says. Nobody
says "run diagnostics".

The inject itself is the easiest in the file, because `diagnostics` takes no
meaningful arguments — `suite` is an enum of one — so there is nothing to
synthesise and no way for the injected call to be subtly wrong.
"""

from __future__ import annotations

import pytest

from arelis.core.claims import detect_diagnostics_ask, detect_exactness_need
from arelis.core.no_call_steps import INJECT_STEPS, try_diagnostics
from tests.test_no_call_path import _ctx, _FakeLoop, _scratch


@pytest.mark.parametrize(
    "ask",
    [
        "run diagnostics",
        "run the tests",
        "run the tests and tell me if they pass",
        "run pytest",
        "run the test suite",
        "do the tests pass?",
        "are all the tests passing",
        "is the suite green",
    ],
)
def test_the_ways_people_actually_ask_are_recognised(ask: str) -> None:
    assert detect_diagnostics_ask(ask)
    assert detect_exactness_need(ask).needs_diagnostics


@pytest.mark.parametrize(
    "ask",
    [
        "don't run the tests",
        "do not run diagnostics",
        "run diagnostics on my car",
        "run the tests on the staging server",
        # A question about the command, not a request to execute it.
        "how do I run the tests?",
        "what does pytest -q do",
        "the test of a good design is whether it survives",
    ],
)
def test_it_does_not_fire_on_things_that_only_look_like_it(ask: str) -> None:
    assert not detect_diagnostics_ask(ask)


def _diag_turn(text: str, content: str) -> tuple[object, object, object]:
    loop = _FakeLoop()
    r = _scratch(
        text=text,
        content=content,
        exact_need=detect_exactness_need(text),
        tool_names={"diagnostics"},
        available={"diagnostics"},
        visible={"diagnostics"},
        available_all={"diagnostics"},
    )
    ctx = _ctx(text=text)
    ctx.tool_names = {"diagnostics"}
    return loop, ctx, r


@pytest.mark.asyncio
async def test_an_invented_pass_is_replaced_by_an_actual_run() -> None:
    loop, ctx, r = _diag_turn(
        "run the tests and tell me if they pass",
        "Yes, the tests pass — the suite is green.",
    )

    assert await try_diagnostics(loop, ctx, r) != "skip"
    assert r.calls, "she asserted a test result she never checked"
    assert r.calls[0][0] == "diagnostics"


@pytest.mark.asyncio
async def test_it_does_not_run_the_suite_twice() -> None:
    loop, ctx, r = _diag_turn("run the tests", "They pass.")
    loop.tools_used = {"diagnostics"}

    assert await try_diagnostics(loop, ctx, r) == "skip"
    assert not r.calls


@pytest.mark.asyncio
async def test_an_unrelated_turn_does_not_trigger_a_full_suite_run() -> None:
    """Running pytest is expensive; a false positive costs real minutes."""
    loop, ctx, r = _diag_turn("what's the weather tomorrow", "Mild and dry.")

    assert await try_diagnostics(loop, ctx, r) == "skip"
    assert not r.calls


@pytest.mark.asyncio
async def test_it_is_skipped_when_the_gate_is_off() -> None:
    loop, ctx, r = _diag_turn("run the tests", "They pass.")
    r.agent_cfg["diagnostics_force_call"] = False

    assert await try_diagnostics(loop, ctx, r) == "skip"
    assert not r.calls


def test_the_step_is_registered() -> None:
    assert try_diagnostics in INJECT_STEPS
