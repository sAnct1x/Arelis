"""Units / calculator empty-followup must ship clean spoken numbers, not Pint dumps."""

from __future__ import annotations

import asyncio
import re

from arelis.core.failure_copy import chat_followup_from_tool, plain_algebra_chat
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


def test_units_fahrenheit_to_celsius_is_spoken_not_pint() -> None:
    ask = "convert 100 degrees Fahrenheit to Celsius"
    line = asyncio.run(_units_followup("convert", ask, quantity="100 degF", to="degC"))
    _assert_clean_spoken(line)
    # The model-only temperature note is dropped; the reading is rounded.
    assert line == "That works out to about 37.78 degrees Celsius."


def test_units_constant_g_is_not_a_raw_codata_line() -> None:
    ask = "what is the gravitational constant G"
    line = asyncio.run(_units_followup("constant", ask, name="G"))
    _assert_clean_spoken(line)
    assert _DATA in line.lower()


def test_units_speed_of_light_is_not_a_raw_codata_line() -> None:
    ask = "what is the speed of light"
    line = asyncio.run(_units_followup("constant", ask, name="speed of light"))
    _assert_clean_spoken(line)
    assert _DATA in line.lower()


def test_units_height_in_cm_uses_plain_unit_word() -> None:
    ask = "how tall is 5 ft 8 in in cm"
    line = asyncio.run(_units_followup("convert", ask, quantity="5 ft 8 in", to="cm"))
    _assert_clean_spoken(line)
    assert line == "That works out to 172.72 centimeters."


def test_units_miles_to_km_rounds_and_pluralizes() -> None:
    ask = "convert 5 miles to kilometers"
    line = asyncio.run(_units_followup("convert", ask, quantity="5 mi", to="km"))
    _assert_clean_spoken(line)
    assert line == "That works out to about 8.05 kilometers."


def test_clean_degree_celsius_is_humanized_and_rounded() -> None:
    """When the RHS is clean number + unit, round and say degrees Celsius."""
    line = plain_algebra_chat("100 degF = 37.77777777777783 degree_Celsius")
    assert line == "That works out to about 37.78 degrees Celsius."


def test_exact_half_has_no_about() -> None:
    assert plain_algebra_chat("5 / 2 = 2.5") == "That works out to 2.5."


def test_percent_keeps_the_percent_sign() -> None:
    raw = "((349.54 - 287.20) / 287.20) * 100 = 21.706128133704734 (exactly 15585/718)"
    line = plain_algebra_chat(raw, ask="what percent change is that?")
    assert line == "That works out to about 21.7%."


def test_huge_number_is_readable_not_309_digits() -> None:
    from arelis.tools.calculator import CalculatorTool

    result = asyncio.run(CalculatorTool().run(expression="1e308*10"))
    assert result.ok, result.output
    line = chat_followup_from_tool("calculator", result.output, ask="what is 1e308 times 10")
    assert "works out" in line.lower()
    assert len(line) < 80
    assert "309" in line
    assert "1" * 50 not in line.replace(" ", "")


def test_large_integer_uses_thousands_separators() -> None:
    assert plain_algebra_chat("1234567") == "That works out to 1,234,567."


def test_same_call_units_uses_the_same_spoken_line() -> None:
    ask = "convert 5 miles to kilometers"
    result = asyncio.run(UnitsTool().run(action="convert", quantity="5 mi", to="km"))
    assert result.ok, result.output
    follow = chat_followup_from_tool("units", result.output, ask=ask)
    same = same_call_finish_line("units", result.output)
    assert same == follow
    assert same == "That works out to about 8.05 kilometers."
