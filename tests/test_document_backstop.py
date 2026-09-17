""""Create a pdf about X" has to end in a file, not a chat message.

Found 2026-09-17 by adding the board's first `document` scenario. The
`document` ForceGate in gates.py has always existed and `needs_document` arms
correctly on all six phrasings — and `apply_force_gates` only *nudges*: it
appends the notice, retries once, and a nudge is a request the model can
decline. Every other intent of this weight has an inject behind the nudge.
This one had nothing, so declining cost nothing, and the turn ended with the
research in the chat log and no file. The tool's own description says "do not
dump the document into chat", which describes the failure it was losing to.

The fix works because she already wrote the content — she put it in the wrong
container. The injected body is her prose verbatim, so nothing is invented.
That is the property worth protecting here: a guessed document body would be
worse than no document, which is why there is a length floor rather than an
inject on an empty answer.
"""

from __future__ import annotations

import pytest

from arelis.core.claims import detect_exactness_need
from arelis.core.no_call_steps import INJECT_STEPS, try_document
from arelis.tools.document import (
    document_format_from_ask,
    document_title_from_ask,
    draft_document_args,
)
from tests.test_no_call_path import _ctx, _FakeLoop, _scratch

PROSE = (
    "# The Dirac Equation\n\nThe Dirac equation is a relativistic wave "
    "equation formulated by Paul Dirac in 1928. It describes spin-1/2 "
    "particles and predicts antimatter."
)


# ------------------------------------------------------------------ container


@pytest.mark.parametrize(
    ("ask", "fmt"),
    [
        ("create a pdf about the dirac equation", "pdf"),
        ("export this as a csv", "csv"),
        ("make me a word doc about rebar", "docx"),
        ("build a spreadsheet of the numbers", "xlsx"),
        ("write it up in markdown", "md"),
        ("save that as a text file", "txt"),
        # No format named. PDF is what "make me a document" means to almost
        # everyone, and every other type here gets asked for explicitly.
        ("write me a report on the dirac equation", "pdf"),
    ],
)
def test_the_format_comes_from_the_ask(ask: str, fmt: str) -> None:
    assert document_format_from_ask(ask) == fmt


@pytest.mark.parametrize(
    ("ask", "title"),
    [
        ("create a pdf about the dirac equation", "the dirac equation"),
        ("make a document titled Board log", "Board log"),
        ("write a report on rebar corrosion", "rebar corrosion"),
        ("create a pdf about the dirac equation please", "the dirac equation"),
    ],
)
def test_the_title_comes_from_the_ask(ask: str, title: str) -> None:
    assert document_title_from_ask(ask) == title


def test_an_ask_with_no_subject_still_gets_a_title() -> None:
    assert document_title_from_ask("make me a pdf", fallback="Document") == (
        "Document"
    )


def test_a_long_ask_does_not_become_a_long_filename() -> None:
    assert len(document_title_from_ask("write a pdf about " + "x " * 200)) <= 80


# ------------------------------------------------------------------ the body


def test_the_body_is_hers_verbatim() -> None:
    """The safety argument for this whole feature.

    If anything ever paraphrases, summarises or truncates the body here, the
    injected file stops being the thing she wrote and this test is what says
    so.
    """
    args = draft_document_args("create a pdf about the dirac equation", PROSE)
    assert args["body"] == PROSE
    assert args["format"] == "pdf"
    assert args["title"] == "the dirac equation"


# ------------------------------------------------------------------ the step


def _doc_turn(text: str, content: str) -> tuple[object, object, object]:
    """Uses the real exactness detector rather than a hand-set flag.

    Hard-coding `needs_document=True` would make the negative tests below
    vacuous — they would only prove that a flag someone set by hand was
    honoured. Running the detector means "what is the dirac equation?" is
    rejected by the same code that decides it in production.
    """
    loop = _FakeLoop()
    r = _scratch(
        text=text,
        content=content,
        exact_need=detect_exactness_need(text),
        tool_names={"document", "web_search"},
        available={"document", "web_search"},
        visible={"document", "web_search"},
        available_all={"document", "web_search"},
    )
    ctx = _ctx(text=text)
    ctx.tool_names = {"document", "web_search"}
    return loop, ctx, r


@pytest.mark.asyncio
async def test_prose_that_should_have_been_a_file_becomes_one() -> None:
    loop, ctx, r = _doc_turn("create a pdf about the dirac equation", PROSE)

    assert await try_document(loop, ctx, r) != "skip"
    assert r.calls, "the answer stayed in the chat log"
    name, args = r.calls[0]
    assert name == "document"
    assert args["format"] == "pdf"
    assert args["body"] == PROSE


@pytest.mark.asyncio
async def test_a_short_acknowledgement_is_not_turned_into_a_document() -> None:
    """"Sure, I'll put that together" is not a document.

    An empty or near-empty answer is the force gate nudge's job. Writing a PDF
    containing one sentence of filler would be a worse outcome than the bug.
    """
    loop, ctx, r = _doc_turn(
        "create a pdf about the dirac equation", "Sure, I'll put that together."
    )

    assert await try_document(loop, ctx, r) == "skip"
    assert not r.calls


@pytest.mark.asyncio
async def test_it_does_not_fire_once_the_file_exists() -> None:
    loop, ctx, r = _doc_turn("create a pdf about the dirac equation", PROSE)
    loop.tools_used = {"document"}

    assert await try_document(loop, ctx, r) == "skip"
    assert not r.calls


@pytest.mark.asyncio
async def test_an_ordinary_question_is_not_filed_as_a_document() -> None:
    """A long answer to a plain question must stay a plain answer."""
    loop, ctx, r = _doc_turn("what is the dirac equation?", PROSE)

    assert await try_document(loop, ctx, r) == "skip"
    assert not r.calls


@pytest.mark.asyncio
async def test_it_is_skipped_when_the_gate_is_off() -> None:
    loop, ctx, r = _doc_turn("create a pdf about the dirac equation", PROSE)
    r.agent_cfg["document_force_call"] = False

    assert await try_document(loop, ctx, r) == "skip"
    assert not r.calls


def test_the_step_is_registered() -> None:
    assert try_document in INJECT_STEPS
