"""Dispatch runs the call the model made.

Redirects that rewrote a call from the user's words are gone. Confirm
cards, send locks, and the unknown-tool check still run in dispatch.
"""

from __future__ import annotations

from typing import Any

from arelis.core.turn_context import TurnContext
from arelis.core.turn_scratch import RoundScratch


async def apply_redirects(
    loop: Any,
    ctx: TurnContext,
    r: RoundScratch,
    name: str,
    args: dict[str, Any],
    drop_wander: Any,
) -> tuple[Any, ...]:
    """Run the call the model made. Redirects from the user's words are gone."""
    del loop, ctx, r, drop_wander
    return ("run", name, args)
