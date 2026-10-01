"""``in`` is both the inch and a conversion word. ``to`` and ``into`` win."""

from __future__ import annotations

import asyncio

import pytest

from arelis.tools.units import UnitsTool, _split_conversion


def _run(**kwargs: str):
    return asyncio.run(UnitsTool().run(**kwargs))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("10 in to cm", ("10 in", "cm")),
        ("10 in into cm", ("10 in", "cm")),
        ("90 degrees Fahrenheit to Celsius", ("90 degrees Fahrenheit", "Celsius")),
        ("90 degrees Fahrenheit in Celsius", ("90 degrees Fahrenheit", "Celsius")),
        ("5 miles in km", ("5 miles", "km")),
        ("5 ft 8 in in cm", ("5 ft 8 in", "cm")),
        ("10 in", None),
        ("speed of light", None),
        ("2 apples in bananas", None),
    ],
)
def test_split_conversion(text: str, expected: tuple[str, str] | None) -> None:
    assert _split_conversion(text) == expected


def test_inches_to_centimetres_in_one_string_still_converts() -> None:
    result = _run(action="convert", quantity="10 in to cm")
    assert result.ok, result.output
    assert "25.4" in result.output


def test_inches_still_convert_when_to_is_given_separately() -> None:
    result = _run(action="convert", quantity="10 in", to="cm")
    assert result.ok, result.output
    assert "25.4" in result.output


def test_a_constant_call_for_a_fahrenheit_question_falls_back_to_convert() -> None:
    result = _run(action="constant", name="90 degrees Fahrenheit in Celsius")
    assert result.ok, result.output
    assert "32.2" in result.output


def test_a_constant_call_for_inches_to_cm_falls_back_to_convert() -> None:
    result = _run(action="constant", name="10 in to cm")
    assert result.ok, result.output
    assert "25.4" in result.output


def test_a_real_constant_is_not_hijacked_by_the_fallback() -> None:
    result = _run(action="constant", name="speed of light")
    assert result.ok
    assert "299792458" in result.output


def test_an_unknown_constant_that_is_not_a_conversion_still_fails() -> None:
    result = _run(action="constant", name="nonsense in bananas")
    assert not result.ok
