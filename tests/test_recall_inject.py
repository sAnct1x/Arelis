"""A recall ask must not end in "I don't know" with recall sitting right there.

Roadmap 4.0, found 2026-09-17 while building the eval board.

`"What did I say about the Sherpa work last night?"` is detected — the RECALL
IntentSpec matches it, preflight writes a nudge, and `recall` lands in
`_expected_tools`. If the model then calls `web_search` instead, that call is
hidden before dispatch (recall is in `_HIDE_WANDER_FOR`), so it never runs,
and nothing puts `recall` in its place. The turn ends:

    "I don't know — that isn't in what I can recall from our conversation
     right now."

Safe, and wrong. Every other intent of this weight has a backstop in
`no_call_steps.INJECT_STEPS`; recall had none, so ignoring the nudge cost
nothing.

Two near-misses the roadmap warns about, both avoided here. Adding `recall` to
`call_redirects.redirect_local_store` does nothing — that path never sees the
call, because the wander tool is already hidden by then. And
`local_store_inject_args` has no `recall` branch; it would fall through to
`{"action": "list"}`, which is not recall's shape (`action=search` plus a
`query`).
"""

from __future__ import annotations

import pytest

from arelis.core.intent_catalog import looks_like_recall_utterance, recall_query
from arelis.core.no_call_steps import INJECT_STEPS, try_recall
from arelis.core.turn_round import apply_no_call_path
from tests.test_no_call_path import _ctx, _FakeLoop, _scratch

# --------------------------------------------------------------------------
# The query has to come out of the sentence, because recall refuses a blank one
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("utterance", "expected"),
    [
        ("What did I say about the Sherpa work last night?", "Sherpa work"),
        ("What did I say yesterday?", "yesterday"),
        ("what did I say about arelis?", "arelis"),
        ("do you remember the rebar estimate", "rebar estimate"),
        ("you told me about a book on Rust", "book on Rust"),
        ("what did I tell you about my sister's wedding", "sister's wedding"),
        ("from our chat about the eval harness yesterday", "eval harness"),
    ],
)
def test_the_search_terms_survive_the_question_wrapper(utterance: str, expected: str) -> None:
    """The trigger phrase and the time reference are not search terms.

    Handing recall the whole sentence would search for "what did i say about",
    which appears in no transcript and ranks nothing.
    """
    assert recall_query(utterance) == expected


@pytest.mark.parametrize(
    "utterance",
    [
        "do you remember?",
        "do you remember",
        "what did I say",
        "what did i say said something how i don't remember what are you doing to night",
    ],
)
def test_a_recall_ask_with_no_subject_yields_no_query(utterance: str) -> None:
    """There is nothing to search for, and a blank query is a tool error."""
    assert recall_query(utterance) == ""


def test_the_detector_agrees_with_the_preflight_pattern() -> None:
    assert looks_like_recall_utterance("what did I say about the deck?")
    assert looks_like_recall_utterance("do you remember the rebar estimate")
    assert not looks_like_recall_utterance("what's the weather tomorrow")
    assert not looks_like_recall_utterance("remember that I climb on Tuesdays")
    assert not looks_like_recall_utterance("what did I say")
    assert not looks_like_recall_utterance(
        "what did i say said something how i don't remember what are you doing to night"
    )


# --------------------------------------------------------------------------
# The backstop
# --------------------------------------------------------------------------


def _recall_scratch(text: str) -> object:
    return _scratch(
        text=text,
        content="I don't know, that isn't in what I can recall.",
        tool_names={"recall"},
        available={"recall"},
        visible={"recall"},
        available_all={"recall"},
    )


@pytest.mark.asyncio
async def test_a_recall_ask_gets_a_recall_search() -> None:
    loop = _FakeLoop()
    text = "What did I say about the Sherpa work last night?"
    r = _recall_scratch(text)
    ctx = _ctx(text=text)
    ctx.tool_names = {"recall"}

    assert await try_recall(loop, ctx, r) != "skip"
    assert r.calls, "she ignored the nudge and nothing forced the search"
    name, args = r.calls[0]
    assert name == "recall"
    assert args.get("action") == "search"
    assert args.get("query") == "Sherpa work"


@pytest.mark.asyncio
async def test_the_expected_tool_alone_is_enough_to_fire() -> None:
    """Preflight puts recall in _expected_tools; the backstop honours that."""
    loop = _FakeLoop()
    loop._expected_tools = {"recall"}
    text = "any idea what the rebar number was"
    r = _recall_scratch(text)
    ctx = _ctx(text=text)
    ctx.tool_names = {"recall"}

    assert await try_recall(loop, ctx, r) != "skip"
    assert r.calls
    assert r.calls[0][0] == "recall"


@pytest.mark.asyncio
async def test_spoken_mush_is_not_injected_as_a_search() -> None:
    loop = _FakeLoop()
    text = "what did i say said something how i don't remember what are you doing to night"
    r = _recall_scratch(text)
    ctx = _ctx(text=text)
    ctx.tool_names = {"recall"}

    assert await try_recall(loop, ctx, r) == "skip"
    assert not r.calls


@pytest.mark.asyncio
async def test_a_recall_ask_with_nothing_to_search_for_is_left_alone() -> None:
    """Injecting action=search with a blank query just produces a tool error."""
    loop = _FakeLoop()
    text = "do you remember?"
    r = _recall_scratch(text)
    ctx = _ctx(text=text)
    ctx.tool_names = {"recall"}

    assert await try_recall(loop, ctx, r) == "skip"
    assert not r.calls


@pytest.mark.asyncio
async def test_it_does_not_fire_when_recall_already_ran() -> None:
    """She searched and genuinely found nothing. That answer is allowed to stand."""
    loop = _FakeLoop()
    loop.tools_used = {"recall"}
    text = "What did I say about the Sherpa work last night?"
    r = _recall_scratch(text)
    ctx = _ctx(text=text)
    ctx.tool_names = {"recall"}

    assert await try_recall(loop, ctx, r) == "skip"
    assert not r.calls


@pytest.mark.asyncio
async def test_a_plain_chat_line_is_not_dragged_into_a_search() -> None:
    loop = _FakeLoop()
    text = "thanks, that's great"
    r = _recall_scratch(text)
    ctx = _ctx(text=text)
    ctx.tool_names = {"recall"}

    assert await try_recall(loop, ctx, r) == "skip"
    assert not r.calls


@pytest.mark.asyncio
async def test_it_is_skipped_when_the_gate_is_off() -> None:
    loop = _FakeLoop()
    text = "What did I say about the Sherpa work last night?"
    r = _recall_scratch(text)
    r.agent_cfg["recall_force_call"] = False
    ctx = _ctx(text=text)
    ctx.tool_names = {"recall"}

    assert await try_recall(loop, ctx, r) == "skip"
    assert not r.calls


def test_the_step_is_registered() -> None:
    """A step that is never reached is not a backstop."""
    assert try_recall in INJECT_STEPS


@pytest.mark.asyncio
async def test_the_whole_no_call_path_reaches_it() -> None:
    """Calling try_recall directly proves the step works, not that it runs.

    Twenty-odd steps run before it and any of them could claim this turn
    first. This drives the real entry point instead.
    """
    loop = _FakeLoop()
    text = "What did I say about the Sherpa work last night?"
    r = _recall_scratch(text)
    ctx = _ctx(text=text)
    ctx.tool_names = {"recall"}

    await apply_no_call_path(loop, ctx, r, 0)

    assert r.calls, "no step claimed the turn, so she answered from nothing"
    name, args = r.calls[0]
    assert name == "recall"
    assert args.get("query") == "Sherpa work"
