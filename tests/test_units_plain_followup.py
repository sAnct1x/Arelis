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
    assert line == "That works out to 1 followed by 309 zeros."
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


# --- plurals and big / tiny numbers said in plain words ---------------------

_E_NOTATION = re.compile(r"\d[eE][+-]?\d")


def _assert_no_e_notation(line: str) -> None:
    assert not _E_NOTATION.search(line), line


def test_knots_to_mph_says_miles_per_hour() -> None:
    ask = "how fast is 10 knots in miles per hour?"
    line = asyncio.run(_units_followup("convert", ask, quantity="10 knot", to="mph"))
    _assert_clean_spoken(line)
    assert "mile per hours" not in line
    assert line == "That works out to about 11.51 miles per hour."


def test_years_to_centuries_is_a_real_plural() -> None:
    ask = "convert 300 years to centuries"
    line = asyncio.run(_units_followup("convert", ask, quantity="300 year", to="century"))
    _assert_clean_spoken(line)
    assert "centurys" not in line
    assert line == "That works out to 3 centuries."


def test_kilohertz_to_hertz_stays_hertz() -> None:
    ask = "convert 1 kHz to Hz"
    line = asyncio.run(_units_followup("convert", ask, quantity="1 kHz", to="Hz"))
    _assert_clean_spoken(line)
    assert "hertzs" not in line
    assert line == "That works out to 1,000 hertz."


def test_light_year_in_km_is_said_in_trillions() -> None:
    ask = "how many kilometers are in a light year?"
    line = asyncio.run(
        _units_followup("convert", ask, quantity="1 light_year", to="km")
    )
    _assert_clean_spoken(line)
    _assert_no_e_notation(line)
    assert "9.461e+12" not in line
    assert line == "That works out to about 9.46 trillion kilometers."


def test_earth_sun_distance_in_km_is_said_in_millions() -> None:
    ask = "convert one astronomical unit to kilometers"
    line = asyncio.run(
        _units_followup("convert", ask, quantity="1 astronomical_unit", to="km")
    )
    _assert_clean_spoken(line)
    _assert_no_e_notation(line)
    assert line == "That works out to about 149.6 million kilometers."


def test_electron_volt_in_joules_has_no_e_notation() -> None:
    ask = "convert 1 electron volt to joules"
    line = asyncio.run(_units_followup("convert", ask, quantity="1 eV", to="J"))
    _assert_clean_spoken(line)
    _assert_no_e_notation(line)
    assert "1.602e-19" not in line
    # Too small to say cleanly in words, so the plain give-up line ships.
    assert _DATA in line.lower()


def test_angstrom_in_meters_has_no_e_notation() -> None:
    ask = "how many meters is an angstrom?"
    line = asyncio.run(_units_followup("convert", ask, quantity="1 angstrom", to="m"))
    _assert_clean_spoken(line)
    _assert_no_e_notation(line)
    assert _DATA in line.lower()


def test_minus_forty_fahrenheit_is_exactly_minus_forty_celsius() -> None:
    ask = "what is -40 degrees Fahrenheit in Celsius?"
    line = asyncio.run(_units_followup("convert", ask, quantity="-40 degF", to="degC"))
    _assert_clean_spoken(line)
    assert line == "That works out to -40 degrees Celsius."


def test_psi_in_pascals_gets_thousands_separator() -> None:
    ask = "convert 1 psi to pascals"
    line = asyncio.run(_units_followup("convert", ask, quantity="1 psi", to="Pa"))
    _assert_clean_spoken(line)
    assert line == "That works out to about 6,894.76 pascals."


def test_two_to_the_64_is_said_in_quintillions() -> None:
    from arelis.tools.calculator import CalculatorTool

    result = asyncio.run(CalculatorTool().run(expression="2**64"))
    assert result.ok, result.output
    line = chat_followup_from_tool("calculator", result.output, ask="what is 2 to the 64?")
    _assert_no_e_notation(line)
    assert line == "That works out to about 18.45 quintillion."


def test_ten_to_the_30_is_said_as_zeros() -> None:
    from arelis.tools.calculator import CalculatorTool

    result = asyncio.run(CalculatorTool().run(expression="10**30"))
    assert result.ok, result.output
    line = chat_followup_from_tool("calculator", result.output, ask="what is 10 to the 30?")
    _assert_no_e_notation(line)
    assert line == "That works out to 1 followed by 30 zeros."


def test_small_fraction_is_written_out_not_e_notation() -> None:
    line = plain_algebra_chat("1/300000 = 3.3333333333333333e-06 (exactly 1/300000)")
    _assert_no_e_notation(line)
    assert line == "That works out to about 0.00000333."


def test_exact_trillions_have_no_about() -> None:
    assert plain_algebra_chat("7*10**12 = 7000000000000") == (
        "That works out to 7 trillion."
    )
