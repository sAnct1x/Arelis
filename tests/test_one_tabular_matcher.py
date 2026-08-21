"""Preflight, the plan and the exactness gate agree on what a table is.

Three modules each carried their own copy of the same regex. Preflight's and
plan_nudge's were byte-identical; claims' differed by one flag (re.S), so a
sentence that wrapped across a newline was tabular to the finish gate and not to
the nudge that was supposed to have sent a tool at it.

Nothing failed when they drifted. The gate refused a row count the model had no
warrant for, while the nudge that would have produced the warrant never fired —
which reads, from the outside, as Arelis being unable to answer a question about
a spreadsheet she can see.
"""

from __future__ import annotations

import pytest

from arelis.core.claims import detect_analyze_ask
from arelis.core.intent_catalog import mentions_tabular_data
from arelis.core.plan_nudge import plan_system_message
from arelis.core.preflight import detect_intents

TABULAR = [
    "summarize data.csv",
    "what's in results.xlsx",
    "describe the table for me",
    "analyze this spreadsheet",
    "open the tsv and tell me the columns",
    # The case that used to split them: an action and its noun across a newline.
    "summarize\nthis table",
]

NOT_TABULAR = [
    "what's the weather",
    "text Sam that I'm running late",
    "document this decision in the readme",
    "read the pdf I gave you",
    "",
    "   ",
]


@pytest.mark.parametrize("text", TABULAR)
def test_a_tabular_ask_is_recognised(text: str) -> None:
    assert mentions_tabular_data(text)


@pytest.mark.parametrize("text", NOT_TABULAR)
def test_a_non_tabular_ask_is_not(text: str) -> None:
    assert not mentions_tabular_data(text)


@pytest.mark.parametrize("text", TABULAR)
def test_the_plan_and_the_matcher_agree(text: str) -> None:
    """If it is a table, the turn gets a plan that names the analyze tool."""
    assert "analyze" in (plan_system_message(text) or "").lower()


@pytest.mark.parametrize("text", TABULAR)
def test_preflight_and_the_matcher_agree(text: str) -> None:
    """And a nudge that expects the analyze tool, so the gate has its warrant."""
    kinds = {hint.kind for hint in detect_intents(text)}
    assert "analyze" in kinds


def test_the_finish_gate_reads_the_same_fact() -> None:
    """detect_analyze_ask adds its own guards, but not its own patterns."""
    assert detect_analyze_ask("summarize data.csv")
    assert not detect_analyze_ask("what's the weather")


def test_the_finish_gate_keeps_its_own_exception() -> None:
    """Sharing the matcher must not flatten the guards built on top of it.

    "the file is at C:/x/y.csv" names a table but is a path correction, not a
    request to analyse one.
    """
    assert mentions_tabular_data("the correct path is data/results.csv")
    assert not detect_analyze_ask("the correct path is data/results.csv")
