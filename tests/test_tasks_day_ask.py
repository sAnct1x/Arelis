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

from arelis.core.sms_complete import looks_like_tasks_utterance


def test_an_sms_body_is_not_mistaken_for_a_to_do_ask() -> None:
    """The reason this regex lives in sms_complete.

    It separates "show me my tasks" from a text that happens to mention them.
    Widening it to catch natural phrasing must not start eating outbound
    messages, or the fix costs more than the bug.
    """
    assert not looks_like_tasks_utterance(
        "text my wife and tell her I have to do the shopping today"
    )
    assert not looks_like_tasks_utterance(
        "send Sam a message saying what do I need to bring"
    )

