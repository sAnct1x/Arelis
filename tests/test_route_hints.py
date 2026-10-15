"""Isolated auto-routing heuristics. Same patterns; no product change."""

from __future__ import annotations

import pytest

from arelis.core.route_hints import (
    is_file_loop,
    is_tool_loop,
)


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


