"""Whether this turn has used up its wall clock.

Repeated tool failures are counted on ``TurnContext.fail_counts`` with
``_bad_args_key``. This module does not keep a second counter.
"""

from __future__ import annotations

from typing import Any


def turn_wall_exceeded(loop: Any) -> bool:
    """True when this turn has used up ``ui.hung_turn_cap_s``.

    No key in config means there is no budget. Confirm waits are paused
    on the timer, so they do not count. ``0`` disables the cap.
    """
    config = getattr(loop, "config", None) or {}
    if not isinstance(config, dict):
        return False
    ui = config.get("ui")
    if not isinstance(ui, dict) or "hung_turn_cap_s" not in ui:
        return False
    try:
        cap_s = float(ui.get("hung_turn_cap_s") or 0)
    except (TypeError, ValueError):
        return False
    if cap_s <= 0:
        return False
    timer = getattr(loop, "_timer", None)
    if timer is None:
        return False
    elapsed = int(timer.elapsed_ms()) - int(getattr(timer, "confirm_ms", 0) or 0)
    if elapsed < 0:
        elapsed = 0
    return elapsed >= int(cap_s * 1000)
