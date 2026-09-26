"""The most ordinary way to ask for your to-dos reached no rule at all.

Found 2026-09-17 with scripts/measure_tool_choice.py and confirmed against
preflight directly. The tool-choice corpus expects `tasks` (or `agenda`) for
"What do I have to do today?", and:

    detect_intents("What do I have to do today?")   -> []
    looks_like_tasks_utterance("...")               -> False

Nothing fired. No preflight nudge, no _expected_tools seeding, and `try_tasks`
never reached its inject, so the turn was the model's unaided guess.

The cause is narrow and unglamorous: `_TASKS_UTTERANCE` requires the literal
token "task", "todo" or "checklist". "what do I have **to do** today" is two
words, so `to-?dos?` never matches it. Every phrasing a person actually uses
fell through a regex written for the phrasings a developer types.

This regex lives in sms_complete for a reason — it separates a to-do ask from
an SMS body — so widening it has to leave the SMS path alone. That is the last
test here, and it is the one that matters.
"""

from __future__ import annotations

import pytest

from arelis.core.no_call_steps import try_tasks
from arelis.core.sms_complete import looks_like_tasks_utterance
from tests.test_no_call_path import _ctx, _FakeLoop, _scratch


@pytest.mark.parametrize(
    "utterance",
    [
        "What do I have to do today?",
        "what do i have to do today",
        "what do I need to do today",
        "anything I need to do today?",
        "what do I have to do this week",
        "what's on my plate today",
        "what is on my plate",
    ],
)
def test_the_ordinary_phrasings_are_recognised(utterance: str) -> None:
    assert looks_like_tasks_utterance(utterance)


@pytest.mark.parametrize(
    "utterance",
    [
        "what are my tasks?",
        "show me my todos",
        "add a task to call the dentist",
        "mark that task done",
    ],
)
def test_the_phrasings_that_already_worked_still_work(utterance: str) -> None:
    """A widened regex that drops its original cases is a trade, not a fix."""
    assert looks_like_tasks_utterance(utterance)


@pytest.mark.parametrize(
    "utterance",
    [
        "what's the weather going to be like tomorrow?",
        "what do you think of this design",
        "what do I owe you",
        "tell me what you can do",
        "what did I say about the Sherpa work",
    ],
)
def test_it_does_not_swallow_unrelated_questions(utterance: str) -> None:
    assert not looks_like_tasks_utterance(utterance)


def test_an_sms_body_is_not_mistaken_for_a_to_do_ask() -> None:
    """The reason this regex lives in sms_complete.

    It separates "show me my tasks" from a text that happens to mention them.
    Widening it to catch natural phrasing must not start eating outbound
    messages, or the fix costs more than the bug.
    """
    assert not looks_like_tasks_utterance(
        "text my wife and tell her I have to do the shopping today"
    )
    assert not looks_like_tasks_utterance("send Sam a message saying what do I need to bring")


@pytest.mark.asyncio
async def test_the_day_ask_now_reaches_the_tasks_backstop() -> None:
    """Recognising it is only half the fix; the inject has to fire."""
    loop = _FakeLoop()
    text = "What do I have to do today?"
    r = _scratch(
        text=text,
        content="You've got a few things on.",
        tool_names={"tasks"},
        available={"tasks"},
        visible={"tasks"},
        available_all={"tasks"},
    )
    ctx = _ctx(text=text)
    ctx.tool_names = {"tasks"}

    assert await try_tasks(loop, ctx, r) != "skip"
    assert r.calls, "she answered about the user's day without reading it"
    assert r.calls[0][0] == "tasks"
