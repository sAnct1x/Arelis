"""The offline boards, run as tests.

`arelis/eval/` held 68 scenarios, 18 retrieval cases and 42 tool-choice cases
that nothing ever executed. Wiring them in was the obvious first move and the
wrong one: `scripts/audit_eval_scenarios.py` showed 35 of the 68 handed the
loop the exact call they then asserted was made, and
`scripts/mutate_guards.py` showed twelve guard rails could be switched off with
the board still perfectly green. A green light over that is worse than no
light.

The scenarios were inverted first — script the mistake, assert the correction —
and only then wired up here. The pass count is pinned exactly rather than to a
floor, because a floor tells you something broke without telling you what.

What this file does not cover: any guard that works purely by changing the
prompt. `_ScriptedRouter.stream` never reads `messages`, so lessons, the
preflight nudge *wording*, and the compact tool policy are invisible to every
scenario here. `scripts/mutate_guards.py` lists those as blind spots with
reasons; they belong to the live tool-choice runner.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from arelis.config import load_config
from arelis.eval.harness import run_all_scripted
from arelis.eval.scenarios import SCENARIOS
from arelis.eval.tool_choice import CHOICE_CASES, case_tools, score
from arelis.tools import build_tool_registry


def test_the_whole_scripted_board_passes() -> None:
    results = asyncio.run(run_all_scripted())
    failed = [f"{r.scenario_id}: {'; '.join(r.reasons)}" for r in results if not r.ok]
    assert not failed, "scripted board regressions:\n  " + "\n  ".join(failed)
    # Exact, not a floor: a scenario that stops running is as bad as one that
    # fails, and a floor cannot tell the difference.
    assert len(results) == len([s for s in SCENARIOS if s.script])


def test_scenario_ids_are_unique() -> None:
    """Two scenarios with one id means one of them never reports separately."""
    ids = [s.id for s in SCENARIOS]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"duplicate scenario ids: {dupes}"


def test_every_scenario_can_actually_run() -> None:
    """A scenario with no script is collected by nothing and guards nothing."""
    unscripted = [s.id for s in SCENARIOS if not s.script]
    assert not unscripted, (
        f"scenarios with no script never run offline: {unscripted}. "
        "Either give it a script or delete it; a scenario nothing executes is "
        "a comment that looks like a test."
    )


def test_forbidden_tools_are_never_also_expected() -> None:
    """A scenario asserting both would be unsatisfiable and always red."""
    bad = [
        f"{s.id}: {sorted(set(s.expect_tools) & set(s.forbid_tools))}"
        for s in SCENARIOS
        if set(s.expect_tools) & set(s.forbid_tools)
    ]
    assert not bad, "scenarios expecting and forbidding the same tool:\n  " + "\n  ".join(bad)


# --- tool-choice corpus coherence ------------------------------------------
#
# The corpus itself needs a live model to score, so the number it produces is a
# nightly job rather than a gate. What is checkable offline is whether a case
# could ever pass: `tool_choice.py` says so in its own docstring — "a case
# naming a tool the registry no longer offers is a case that can never pass,
# and that is the failure mode worth a test". This is that test.


@pytest.fixture(scope="module")
def registered() -> set[str]:
    router = SimpleNamespace(provider=SimpleNamespace(list_models=None))
    registry = build_tool_registry(
        load_config(), allow_send=True, attended=True, router=router
    )
    return set(registry.names())


def test_every_choice_case_names_a_tool_that_exists(registered: set[str]) -> None:
    from tests.test_eval_stub_schemas import CREDENTIAL_GATED

    missing = sorted(case_tools() - registered - CREDENTIAL_GATED)
    assert not missing, (
        f"tool_choice cases accept tools that do not exist: {missing}. "
        "Those cases can never be scored a hit, so they silently drag the "
        "board down and look like a model problem."
    )


def test_no_choice_case_is_unanswerable() -> None:
    empty = [c.utterance for c in CHOICE_CASES if not c.accepts]
    assert not empty, f"choice cases with no acceptable tool: {empty}"


def test_choice_utterances_are_unique() -> None:
    """score() keys on the utterance, so a duplicate silently drops a case."""
    said = [c.utterance for c in CHOICE_CASES]
    dupes = sorted({u for u in said if said.count(u) > 1})
    assert not dupes, f"duplicate choice utterances (score() would drop one): {dupes}"


def test_the_skill_retrieval_board_passes() -> None:
    """Pure functions over the skill cards; no model, no I/O.

    Held to the same standard as the scenarios: `scripts/mutate_guards.py`
    cannot reach this board, so if this ever becomes the thing standing between
    a refactor and production, check it can fail first.
    """
    from arelis.eval.skill_retrieval import run_retrieval_board

    board = run_retrieval_board()
    failed = [
        f"{c['id']}: {'; '.join(c['reasons'])}"
        for c in board["cases"]
        if not c["ok"]
    ]
    assert not failed, "skill retrieval regressions:\n  " + "\n  ".join(failed)
    assert board["passed"] == board["total"]
    assert board["false_positive_rate"] == 0.0


def test_scoring_counts_a_missing_answer_as_a_miss() -> None:
    """Pins the contract the nightly runner depends on."""
    hits, misses = score({})
    assert hits == 0
    assert len(misses) == len(CHOICE_CASES)
    assert "called nothing" in misses[0]

    first = CHOICE_CASES[0]
    hits, misses = score({first.utterance: first.accepts[0]})
    assert hits == 1
    assert len(misses) == len(CHOICE_CASES) - 1
