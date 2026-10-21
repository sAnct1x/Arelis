"""Spoken temperature phrases must convert, not bounce off Pint."""

from __future__ import annotations

import asyncio

from arelis.tools.units import UnitsTool


def test_fahrenheit_to_celsius_spoken() -> None:
    tool = UnitsTool()
    result = asyncio.run(
        tool.run(action="convert", quantity="90 degrees Fahrenheit", to="Celsius")
    )
    assert result.ok, result.output
    assert "32.2" in result.output


def test_bare_f_and_c_are_temperature_offset_not_farad() -> None:
    """Bare F/C in a temperature pair are degF/degC, not farad/coulomb.

    98.6 F is 37 C (offset). A delta would be 98.6 * 5/9. Prefixed charge
    and capacitance stay electrical.
    """
    tool = UnitsTool()
    pairs = (
        ("98.6 F", "C"),
        ("98.6 degF", "degC"),
        ("98.6 °F", "°C"),
        ("98.6 fahrenheit", "celsius"),
        ("98.6 degF", "C"),
        ("98.6 F", "celsius"),
        ("98.6 °F", "C"),
    )
    for quantity, dest in pairs:
        result = asyncio.run(tool.run(action="convert", quantity=quantity, to=dest))
        assert result.ok, (quantity, dest, result.output)
        value = float(result.data["value"])
        assert abs(value - 37.0) < 1e-6, (quantity, dest, value, result.output)
    farad = asyncio.run(tool.run(action="convert", quantity="10 uF", to="nF"))
    assert farad.ok, farad.output
    assert abs(float(farad.data["value"]) - 10_000) < 1e-6
    still_farad = asyncio.run(tool.run(action="convert", quantity="10 F", to="uF"))
    assert still_farad.ok, still_farad.output
    assert abs(float(still_farad.data["value"]) - 1e7) < 1e-3
    coulomb = asyncio.run(tool.run(action="convert", quantity="5 C", to="mC"))
    assert coulomb.ok, coulomb.output
    assert abs(float(coulomb.data["value"]) - 5_000) < 1e-6


def test_fahrenheit_phrase_in_quantity_only() -> None:
    tool = UnitsTool()
    result = asyncio.run(
        tool.run(action="convert", quantity="90 degrees Fahrenheit to Celsius")
    )
    assert result.ok, result.output
    assert "32.2" in result.output


def test_spoken_height_without_inch_word() -> None:
    tool = UnitsTool()
    result = asyncio.run(tool.run(action="convert", quantity="6 foot 2", to="meter"))
    assert result.ok, result.output
    assert "1.8" in result.output
    value = float(result.data["value"])
    assert 1.87 < value < 1.89


def test_height_with_inch_word() -> None:
    tool = UnitsTool()
    result = asyncio.run(tool.run(action="convert", quantity="5 ft 8 in", to="meter"))
    assert result.ok, result.output
    value = float(result.data["value"])
    assert 1.72 < value < 1.74
