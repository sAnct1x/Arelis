"""One hand sentence. Desk, shapes, and solar all ask this.

click: one pinch that has not moved.
grab: that pinch has traveled.
resize: two hands are closed. Spread is the stretch.
open: anything else, including a hand that is only resting.
"""

from __future__ import annotations

from typing import Literal

HandAct = Literal["open", "click", "grab", "resize"]


def hand_act(*, closed: bool, dragging: bool, company: int) -> HandAct:
    """What this hand is doing, given how many hands are closed."""
    if closed and company >= 2:
        return "resize"
    if closed and dragging:
        return "grab"
    if closed:
        return "click"
    return "open"
