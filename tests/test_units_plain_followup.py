"""Units / calculator empty-followup must ship clean spoken numbers, not Pint dumps."""

from __future__ import annotations

import asyncio
import re

from arelis.core.failure_copy import chat_followup_from_tool
from arelis.core.same_call import same_call_finish_line
from arelis.tools.units import UnitsTool

_EM_DASH = "\u2014"
_EN_DASH = "\u2013"
_DATA = "could not put it into words"


def _assert_clean_spoken(line: str) -> None:
    assert line.strip(), "follow-up must not be empty"
    assert "degree_Celsius" not in line
    assert "**" not in line
    assert "source" not in line.lower()
    assert "this turn" not in line.lower()
    assert ".." not in line
    assert _EM_DASH not in line
    assert _EN_DASH not in line
    # No long unrounded float tails.
    assert not re.search(r"\d+\.\d{6,}", line)


async def _units_followup(action: str, ask: str, **kwargs: object) -> str:
    result = await UnitsTool().run(action=action, **kwargs)
    assert result.ok, result.output
    return chat_followup_from_tool("units", result.output, ask=ask)


def test_huge_number_is_readable_not_309_digits() -> None:
    from arelis.tools.calculator import CalculatorTool

    result = asyncio.run(CalculatorTool().run(expression="1e308*10"))
    assert result.ok, result.output
    line = chat_followup_from_tool("calculator", result.output, ask="what is 1e308 times 10")
    assert line == "That works out to 1 followed by 309 zeros."
    assert "1" * 50 not in line.replace(" ", "")


def test_same_call_units_uses_the_same_spoken_line() -> None:
    ask = "convert 5 miles to kilometers"
    result = asyncio.run(UnitsTool().run(action="convert", quantity="5 mi", to="km"))
    assert result.ok, result.output
    follow = chat_followup_from_tool("units", result.output, ask=ask)
    same = same_call_finish_line("units", result.output)
    assert same == follow
    assert same == "That works out to about 8.05 kilometers."


# --- plurals and big / tiny numbers said in plain words ---------------------

_E_NOTATION = re.compile(r"\d[eE][+-]?\d")


def _assert_no_e_notation(line: str) -> None:
    assert not _E_NOTATION.search(line), line


def test_ten_to_the_30_is_said_as_zeros() -> None:
    from arelis.tools.calculator import CalculatorTool

    result = asyncio.run(CalculatorTool().run(expression="10**30"))
    assert result.ok, result.output
    line = chat_followup_from_tool("calculator", result.output, ask="what is 10 to the 30?")
    _assert_no_e_notation(line)
    assert line == "That works out to 1 followed by 30 zeros."


def test_two_to_the_100_is_a_digit_count() -> None:
    from arelis.tools.calculator import CalculatorTool

    result = asyncio.run(CalculatorTool().run(expression="2**100"))
    assert result.ok, result.output
    line = chat_followup_from_tool("calculator", result.output, ask="what is 2 to the 100?")
    _assert_no_e_notation(line)
    assert "followed by" not in line
    assert line == "That works out to a number with 31 digits."


def test_avogadro_number_is_said_in_sextillions() -> None:
    from arelis.tools.calculator import CalculatorTool

    result = asyncio.run(CalculatorTool().run(expression="6.02214076e23"))
    assert result.ok, result.output
    line = chat_followup_from_tool(
        "calculator", result.output, ask="what is 6.02214076e23?"
    )
    _assert_no_e_notation(line)
    assert "followed by" not in line
    assert "602214076" not in line
    assert line == "That works out to about 602.21 sextillion."


