"""A leftover SMS draft must not ride into another tool's arguments."""

from __future__ import annotations

import asyncio

import pytest

from arelis.core.sms_complete import looks_like_math_ask, looks_like_stale_sms_skip
from arelis.core.tool_args import cross_tool_arg_error, schema_keys
from arelis.tools.calculator import CalculatorTool

_CALC = schema_keys(CalculatorTool.parameters_schema)


def test_a_send_shaped_calculator_call_is_rejected() -> None:
    err = cross_tool_arg_error(
        "calculator", {"to": "wife", "body": "I love you."}, declared=_CALC
    )
    assert err is not None
    assert "send_sms" in err


def test_a_real_calculator_call_is_left_alone() -> None:
    assert (
        cross_tool_arg_error("calculator", {"expression": "17*19"}, declared=_CALC)
        is None
    )


def test_send_sms_itself_is_never_rejected() -> None:
    declared = {"to", "body"}
    assert (
        cross_tool_arg_error(
            "send_sms", {"to": "wife", "body": "I love you."}, declared=declared
        )
        is None
    )


def test_a_tool_that_declares_the_keys_is_not_second_guessed() -> None:
    """browser declares both text and phone for form fill. Judging on keyword
    shape alone would have rejected its own autofill call."""
    declared = {"action", "text", "phone", "url"}
    assert (
        cross_tool_arg_error(
            "browser",
            {"action": "autofill", "phone": "5555550123", "text": "hello"},
            declared=declared,
        )
        is None
    )


def test_without_a_schema_nothing_is_rejected() -> None:
    assert cross_tool_arg_error("calculator", {"to": "wife", "body": "hi"}) is None


def test_an_open_schema_declares_nothing_and_rejects_nothing() -> None:
    """`properties: {}` with `additionalProperties: true` means anything goes.

    Read strictly, an empty declared set says the tool accepts no arguments, so
    every call became "takes none of query". No shipped tool has an open schema,
    but the test doubles do, and the gate silently failed 21 tests.
    """
    declared = schema_keys(
        {"type": "object", "properties": {}, "additionalProperties": True}
    )
    assert declared == set()
    assert cross_tool_arg_error("web_search", {"query": "x"}, declared=declared) is None


def test_all_foreign_arguments_is_the_previous_call_verbatim() -> None:
    err = cross_tool_arg_error("weather", {"to": "wife"}, declared={"location"})
    assert err is not None
    assert "location" in err


def test_a_partly_valid_call_is_not_rejected_on_one_extra_key() -> None:
    """Models add junk keys constantly. One stray next to a real argument is a
    sloppy call, not the wrong tool, and the tool ignores it."""
    assert (
        cross_tool_arg_error(
            "calculator", {"expression": "2+2", "note": "for wife"}, declared=_CALC
        )
        is None
    )


def test_the_calculator_says_wrong_tool_not_missing_expression() -> None:
    """Second line of defence: fanout and direct calls bypass the loop check.
    "Missing expression." reads as a bad call the model then retries."""
    result = asyncio.run(CalculatorTool().run(to="wife", body="I love you."))
    assert not result.ok
    assert "send_sms" in result.output
    assert "Missing expression" not in result.output


@pytest.mark.parametrize(
    "text",
    [
        "what is 17 times 19?",
        "What's 17 times 19",
        "17 * 19",
        "calculate 145 divided by 5",
        "how much is 20 percent of 60",
        "WHAT IS 17 TIMES 19",
    ],
)
def test_math_asks_are_read_as_math(text: str) -> None:
    assert looks_like_math_ask(text)
    assert looks_like_stale_sms_skip(text)


@pytest.mark.parametrize(
    "text",
    [
        "text Brian that 2 + 2 = 4",
        "tell my wife I love her",
        "send a text to my wife saying I am 5 minutes out",
    ],
)
def test_a_real_send_is_not_mistaken_for_math(text: str) -> None:
    assert not looks_like_math_ask(text)


def test_one_undeclared_argument_among_good_ones_is_a_correction() -> None:
    """The partial case was the silent one.

    Tools take **kwargs, so weather(days=2, latitude=39.7) drops the coordinate
    and answers for the profile location without saying it ignored anything.
    Being told beats being obeyed halfway.
    """
    declared = {"days"}
    args = {"days": 2, "latitude": 39.7}

    assert cross_tool_arg_error("weather", args, declared=declared) is None

    strict = cross_tool_arg_error("weather", args, declared=declared, strict=True)
    assert strict is not None
    assert "latitude" in strict
    # It should say what was fine, so the retry keeps it.
    assert "days" in strict


def test_strict_leaves_a_clean_call_alone() -> None:
    for args in ({"days": 2}, {"days": 2, "DAYS": 3}):
        assert (
            cross_tool_arg_error("weather", args, declared={"days"}, strict=True)
            is None
        )


def test_strict_does_not_second_guess_an_open_schema() -> None:
    """An open schema declares nothing; strict must not read that as "takes nothing"."""
    assert (
        cross_tool_arg_error(
            "growth_stub", {"anything": 1}, declared=set(), strict=True
        )
        is None
    )


def test_the_all_foreign_case_still_reads_as_the_wrong_tool() -> None:
    err = cross_tool_arg_error(
        "calculator", {"path": "x.csv"}, declared=_CALC, strict=True
    )
    assert err is not None
    assert "takes none of" in err
