"""Pound-force is force. Mass does not convert to it, and newtons do."""

from __future__ import annotations

import asyncio

from arelis.tools.units import UnitsTool

_LBF_IN_NEWTONS = 4.4482216152605
_MASS_FORCE = "Those units do not convert (mass vs force)."


def test_lbf_converts_to_newtons_and_mass_does_not() -> None:
    """kg to lbf is mass vs force. lbf to N, and the hyphenated spelling, convert.

    Pint reads "-" as subtraction, so "pound-force" used to die in ParserHelper
    ("cannot add or subtract units") instead of reaching force_pound.
    """
    tool = UnitsTool()
    for dest in ("lbf", "pound-force", "pound force"):
        mismatch = asyncio.run(tool.run(action="convert", quantity="10 kg", to=dest))
        assert mismatch.ok is False
        assert mismatch.output == _MASS_FORCE
        assert mismatch.data["fail_class"] == "fail:dimensionality"
        assert "ParserHelper" not in mismatch.output
        assert "add or subtract" not in mismatch.output

    to_n = asyncio.run(tool.run(action="convert", quantity="5 lbf", to="N"))
    assert to_n.ok, to_n.output
    assert abs(float(to_n.data["value"]) - 5 * _LBF_IN_NEWTONS) < 1e-9

    spelled = asyncio.run(tool.run(action="convert", quantity="5 pound-force", to="N"))
    assert spelled.ok, spelled.output
    assert abs(float(spelled.data["value"]) - 5 * _LBF_IN_NEWTONS) < 1e-9

    to_lbf = asyncio.run(tool.run(action="convert", quantity="5 N", to="lbf"))
    assert to_lbf.ok, to_lbf.output
    assert abs(float(to_lbf.data["value"]) - 5 / _LBF_IN_NEWTONS) < 1e-9

    # A pound of mass is still mass. The force rewrite must not eat "lb".
    mass = asyncio.run(tool.run(action="convert", quantity="5 lb", to="kg"))
    assert mass.ok, mass.output
    assert abs(float(mass.data["value"]) - 2.26796185) < 1e-6
