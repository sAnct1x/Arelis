"""Unit conversion and published constants — so numbers are not a vibe."""

from __future__ import annotations

import re
from typing import Any

from pint import DimensionalityError, UndefinedUnitError, UnitRegistry

from arelis.science.constants import format_constant, lookup_constant
from arelis.tools.base import ToolResult

_UREG = UnitRegistry()
_ACTIONS = frozenset({"convert", "constant"})
_FRAME_WORDS = ("cmb frame", "rest frame", "comoving", "peculiar velocity")
# Pint reads "5 ft 8 in" as a product (length²). A height is a sum.
_HEIGHT = re.compile(
    r"(?i)(?P<feet>\d+(?:\.\d+)?)\s*(?:ft|feet|foot)\s+"
    r"(?P<inches>\d+(?:\.\d+)?)\s*(?:in|inch|inches)\b"
)


class UnitsTool:
    name = "units"
    description = (
        "Convert physical quantities and look up published constants "
        "(CODATA / IAU / Planck) with the source year in the result. "
        "Use convert for '5 ft 8 in in meters'. Use constant for G, c, sigma, "
        "Hubble, solar mass. This is not a unit conversion into a cosmological "
        "frame — '2.7 K to the CMB frame' is a Doppler boost, not Pint. "
        "Do not recite CODATA from memory."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["convert", "constant"],
                "description": "convert a quantity, or look up a published constant",
            },
            "quantity": {
                "type": "string",
                "description": "Quantity to convert, e.g. '5 ft 8 in' or '2.7 K'",
            },
            "to": {
                "type": "string",
                "description": "Target unit, e.g. meter, kg, eV",
            },
            "name": {
                "type": "string",
                "description": "Constant id or phrase: G, c, hubble constant, solar mass",
            },
        },
        "required": ["action"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip().lower()
        if action not in _ACTIONS:
            return ToolResult(
                ok=False,
                output="Unknown action. Use convert or constant.",
                data={"fail_class": "fail:action"},
            )
        if action == "constant":
            return _lookup(str(kwargs.get("name") or ""))
        return _convert(
            str(kwargs.get("quantity") or ""),
            str(kwargs.get("to") or ""),
        )


def _lookup(name: str) -> ToolResult:
    found = lookup_constant(name)
    if found is None:
        return ToolResult(
            ok=False,
            output=(
                f"No published constant named {name!r} in the local table. "
                "I will not recite one from memory."
            ),
            data={"fail_class": "fail:unknown_constant", "name": name},
        )
    items = found if isinstance(found, tuple) else (found,)
    lines = [format_constant(item) for item in items]
    if len(items) > 1:
        lines.append(
            "Those are published figures, not a measurement this turn. "
            "Cosmology still has a Hubble tension — pick a value with its source."
        )
    return ToolResult(
        ok=True,
        output="\n".join(lines),
        data={
            "name": name,
            "ids": [item.id for item in items],
            "values": [
                {"id": item.id, "value": item.value, "unit": item.unit, "source": item.source}
                for item in items
            ],
        },
    )


def _convert(quantity: str, to_unit: str) -> ToolResult:
    qty = (quantity or "").strip()
    dest = (to_unit or "").strip()
    if not qty or not dest:
        return ToolResult(
            ok=False,
            output="convert needs quantity and to (a unit).",
            data={"fail_class": "fail:args"},
        )
    blob = f"{qty} {dest}".lower()
    if any(word in blob for word in _FRAME_WORDS) or "cmb" in dest.lower():
        return ToolResult(
            ok=False,
            output=(
                "That is not a unit conversion. A cosmological or CMB frame "
                "change is a Doppler / Lorentz boost with a published dipole, "
                "not a Pint conversion. I will not fake it as meters-per-second "
                "dressing."
            ),
            data={"fail_class": "fail:not_a_unit", "quantity": qty, "to": dest},
        )
    try:
        src = _UREG.Quantity(_normalize_quantity(qty))
        out = src.to(dest)
    except UndefinedUnitError as exc:
        return ToolResult(
            ok=False,
            output=f"Unknown unit: {exc}",
            data={"fail_class": "fail:unit", "quantity": qty, "to": dest},
        )
    except DimensionalityError as exc:
        return ToolResult(
            ok=False,
            output=f"Those units do not convert: {exc}",
            data={"fail_class": "fail:dimensionality", "quantity": qty, "to": dest},
        )
    except Exception as exc:
        return ToolResult(
            ok=False,
            output=f"Could not convert: {exc}",
            data={"fail_class": "fail:other", "quantity": qty, "to": dest},
        )
    magnitude = out.magnitude
    if hasattr(magnitude, "item"):
        try:
            magnitude = magnitude.item()
        except Exception:
            pass
    shown = f"{qty} = {out}"
    extra = ""
    dest_l = dest.lower()
    if "degc" in dest_l or "celsius" in dest_l or dest_l in {"c"}:
        extra = (
            " Temperature conversions use an offset (degC vs kelvin), "
            "not a scale factor."
        )
    return ToolResult(
        ok=True,
        output=shown + extra,
        data={
            "quantity": qty,
            "to": dest,
            "value": float(magnitude) if isinstance(magnitude, (int, float)) else str(out),
            "unit": str(out.units),
        },
    )


def _normalize_quantity(quantity: str) -> str:
    """Rewrite spoken heights so Pint adds feet and inches instead of multiplying."""
    return _HEIGHT.sub(r"(\g<feet> * foot + \g<inches> * inch)", quantity)
