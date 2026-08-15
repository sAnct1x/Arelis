"""The tool-choice corpus has to keep pointing at tools that exist.

The scripted foundation board cannot measure tool choice: 49 of its 59 scenarios
emit their own tool_calls, so the script makes the pick and every gate built to
correct a pick sits idle. The corpus in arelis/eval/tool_choice.py is what a live
model is measured against instead, and it is only worth anything if the tools it
names are still offered. Deleting briefing and attention left three cases naming
tools the registry no longer has — cases that could never pass, in a file nobody
runs without a GPU warm. These checks are the cheap half, and they run offline.
"""

from __future__ import annotations

from arelis.config import load_config
from arelis.eval.tool_choice import CHOICE_CASES, ChoiceCase, case_tools, score
from arelis.tools import build_tool_registry
from arelis.workspace import WorkspaceRoots


def _offered() -> set[str]:
    config = load_config()
    workspace = WorkspaceRoots.from_config(config)
    registry = build_tool_registry(
        config, workspace, allow_send=True, memory_store=None
    )
    return set(registry.names())


def test_every_acceptable_tool_is_one_the_registry_offers() -> None:
    offered = _offered()
    # camera and vision depend on optional local models, so a machine without
    # them would fail this for reasons that are not drift. Judge against the
    # union of what is offered and what the package knows how to build.
    import arelis.tools as tools_pkg

    buildable = {
        getattr(getattr(tools_pkg, attr), "name", "")
        for attr in dir(tools_pkg)
        if attr.endswith("Tool")
    }
    known = offered | {n for n in buildable if n}

    unknown = sorted(case_tools() - known)
    assert not unknown, (
        f"corpus names tools that no longer exist: {unknown}. "
        "Either the tool came back or the case needs retargeting."
    )


def test_no_case_still_points_at_the_two_deleted_tools() -> None:
    for gone in ("briefing", "attention"):
        assert gone not in case_tools(), f"{gone} was deleted on 2026-08-14"


def test_no_duplicate_utterances() -> None:
    seen = [c.utterance.strip().lower() for c in CHOICE_CASES]
    assert len(seen) == len(set(seen)), "a repeated utterance is scored twice"


def test_every_case_accepts_something() -> None:
    for case in CHOICE_CASES:
        assert case.accepts, case.utterance


def test_the_owners_own_multimodal_words_are_in_the_corpus() -> None:
    """These are the phrasings that routed nowhere until 2026-08-14.

    A regression here is invisible in ordinary testing, because "analyze" is a
    real tool name and the call looks well-formed right up to
    "Unsupported file type: .png".
    """
    text = " | ".join(c.utterance.lower() for c in CHOICE_CASES)
    assert "analyze the picture" in text
    assert "analyze the document" in text


def test_scoring_counts_a_silent_answer_as_a_miss() -> None:
    hits, misses = score({})
    assert hits == 0
    assert len(misses) == len(CHOICE_CASES)
    assert "called nothing" in misses[0]


def test_scoring_accepts_any_defensible_pick() -> None:
    case = ChoiceCase("read the text in the shot", ("ocr", "vision"))
    assert case.hit("ocr")
    assert case.hit("vision")
    assert not case.hit("analyze")

    picks = {c.utterance: c.accepts[0] for c in CHOICE_CASES}
    hits, misses = score(picks)
    assert hits == len(CHOICE_CASES)
    assert not misses
