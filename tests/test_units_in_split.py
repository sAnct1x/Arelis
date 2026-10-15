"""``in`` is both the inch and a conversion word. ``to`` and ``into`` win."""

from __future__ import annotations

import asyncio

from arelis.tools.units import UnitsTool


def _run(**kwargs: str):
    return asyncio.run(UnitsTool().run(**kwargs))


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


def test_a_real_constant_is_not_hijacked_by_the_fallback() -> None:
    result = _run(action="constant", name="speed of light")
    assert result.ok
    assert "299792458" in result.output


