"""Isolated auto-routing heuristics. Same patterns; no product change."""

from __future__ import annotations

import pytest

from arelis.core.orchestrator import FILE_LOOP_HINT, RESEARCH_HINTS, TOOL_LOOP_HINT
from arelis.core.route_hints import (
    is_file_loop,
    is_research_hint,
    is_tool_loop,
)


def test_orchestrator_reexports_the_same_objects() -> None:
    from arelis.core import route_hints

    assert TOOL_LOOP_HINT is route_hints.TOOL_LOOP_HINT
    assert FILE_LOOP_HINT is route_hints.FILE_LOOP_HINT
    assert RESEARCH_HINTS is route_hints.RESEARCH_HINTS


@pytest.mark.parametrize(
    "text",
    (
        "search the web for lithium prices",
        "what's the weather today",
        "https://example.com/page",
        "research cyclospora outbreaks briefly",
    ),
)
def test_tool_loop_category(text: str) -> None:
    assert is_tool_loop(text)


@pytest.mark.parametrize(
    "text",
    (
        "please edit the python file and lint it",
        "git commit the workspace",
    ),
)
def test_file_loop_category(text: str) -> None:
    assert is_file_loop(text)
    assert is_tool_loop(text)


@pytest.mark.parametrize(
    "text",
    (
        "Investigate recent battery recycling and write a report",
        "i want you to deeply research the best piezoelectric material",
        "in-depth analysis of the spectrum",
        "cite sources for fusion",
    ),
)
def test_research_category(text: str) -> None:
    assert is_research_hint(text)


@pytest.mark.parametrize(
    "text",
    (
        "hey how are you",
        "thanks",
        "research",
        "cite",
    ),
)
def test_bare_words_are_not_research(text: str) -> None:
    assert not is_research_hint(text)


def test_a_sourced_pdf_is_a_research_hint() -> None:
    text = (
        "Research what the lab measured. "
        "Write the result as a PDF. Search the web, then open the papers."
    )
    assert is_research_hint(text)


def test_a_pdf_with_no_search_is_not_a_research_hint() -> None:
    assert not is_research_hint("Write the result as a PDF I can open.")


def test_a_check_in_does_not_need_a_page() -> None:
    from arelis.core.claims import apply_research_web_need, detect_exactness_need
    from arelis.core.route_hints import research_chip_needs_a_page
    from arelis.core.tool_subset import is_research_mode
    from arelis.core.turn_goal import derive_turn_goal

    ask = "hey i got some questions and testing to do, ready?"
    assert not research_chip_needs_a_page(ask)
    assert not is_research_mode("research", ask)
    need = apply_research_web_need(
        detect_exactness_need(ask), research_mode=True, text=ask
    )
    assert not need.needs_web_evidence
    assert "web" not in need.kinds
    goal = derive_turn_goal(ask, role="research", research_mode=True)
    assert goal.kind == "none"


def test_a_real_question_on_the_research_chip_still_needs_a_page() -> None:
    from arelis.core.route_hints import research_chip_needs_a_page
    from arelis.core.tool_subset import is_research_mode
    from arelis.core.turn_goal import derive_turn_goal

    ask = "What did the lab actually measure, and which paper states it?"
    assert research_chip_needs_a_page(ask)
    assert is_research_mode("research", ask)
    goal = derive_turn_goal(ask, role="research", research_mode=True)
    assert goal.kind == "research"


def test_derive_is_not_a_research_hint() -> None:
    assert not is_research_hint(
        "derive the equation for F=ma. show me how it was derived."
    )
