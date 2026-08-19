"""Units tool — Pint conversions and cited constants."""

from __future__ import annotations

import pytest

from arelis.science.constants import lookup_constant
from arelis.tools import build_tool_registry
from arelis.tools.units import UnitsTool
from arelis.workspace import WorkspaceRoots


@pytest.mark.asyncio
async def test_convert_five_foot_eight() -> None:
    tool = UnitsTool()
    result = await tool.run(
        action="convert", quantity="5 ft 8 in", to="meter"
    )
    assert result.ok, result.output
    value = float(result.data["value"])
    assert 1.70 < value < 1.75


@pytest.mark.asyncio
async def test_cmb_frame_is_not_a_conversion() -> None:
    tool = UnitsTool()
    result = await tool.run(
        action="convert", quantity="2.7 K", to="CMB frame"
    )
    assert not result.ok
    assert "not a unit" in result.output.lower() or "doppler" in result.output.lower()


@pytest.mark.asyncio
async def test_constant_g_cites_codata() -> None:
    tool = UnitsTool()
    result = await tool.run(action="constant", name="G")
    assert result.ok, result.output
    assert "CODATA 2022" in result.output
    assert "not measured this turn" in result.output.lower()


@pytest.mark.asyncio
async def test_hubble_returns_both_published_figures() -> None:
    tool = UnitsTool()
    result = await tool.run(action="constant", name="hubble constant")
    assert result.ok
    assert "Planck" in result.output
    assert "tension" in result.output.lower()
    ids = result.data.get("ids") or []
    assert "H0_planck" in ids and "H0_sh0es" in ids


@pytest.mark.asyncio
async def test_unknown_constant_refuses() -> None:
    tool = UnitsTool()
    result = await tool.run(action="constant", name="made-up-constant")
    assert not result.ok
    assert "will not recite" in result.output.lower()


def test_lookup_aliases() -> None:
    g = lookup_constant("gravitational constant")
    assert g is not None and not isinstance(g, tuple)
    assert g.id == "G"


def test_units_is_registered_without_confirm(tmp_path) -> None:
    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(tmp_path)]}})
    registry = build_tool_registry({"tools": {}, "agent": {}}, workspace)
    assert registry.get("units") is not None
    assert not registry.needs_confirm(
        "units", {"action": "convert", "quantity": "1 m", "to": "ft"}
    )
