"""Pixel pointer gate — x,y only after screenshot + vision this turn."""

from __future__ import annotations

from typing import Any


def parse_xy(kwargs: dict[str, Any]) -> tuple[float | None, float | None]:
    raw_x = kwargs.get("x")
    raw_y = kwargs.get("y")
    if raw_x in (None, "") or raw_y in (None, ""):
        return None, None
    try:
        return float(raw_x), float(raw_y)
    except (TypeError, ValueError):
        return None, None


def parse_to_xy(kwargs: dict[str, Any]) -> tuple[float | None, float | None]:
    raw_x = kwargs.get("to_x")
    raw_y = kwargs.get("to_y")
    if raw_x in (None, "") or raw_y in (None, ""):
        return None, None
    try:
        return float(raw_x), float(raw_y)
    except (TypeError, ValueError):
        return None, None


def xy_refused() -> str:
    return (
        "x,y needs screenshot then vision this turn. "
        "Prefer a snapshot ref. Not computer-use by default."
    )
