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
