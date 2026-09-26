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
