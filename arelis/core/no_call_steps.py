"""No-call path. The model picks the tool.

Nothing is invented from the user's words. A round with no call falls
through to the finish path.
"""

from __future__ import annotations

from typing import Any

from arelis.core.turn_context import TurnContext
from arelis.core.turn_scratch import RoundScratch

NUDGE = "nudge"


async def run_inject_steps(loop: Any, ctx: TurnContext, r: RoundScratch) -> str:
    """The model picks the tool. Nothing is invented from the user's words."""
    del loop, ctx, r
    return "none"
