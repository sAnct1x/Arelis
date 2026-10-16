"""Stop a turn when the same exception type keeps coming back.

``fail_counts`` keys the whole argument blob. A rewritten cell is a new
key every time, so the identical-args fuse never trips and the model
keeps calling the code tool until the round budget. The tool result
carries ``status`` and the exception type. This counts that type.
"""

from __future__ import annotations

from typing import Any


def same_error_limit(agent_cfg: dict[str, Any] | None) -> int:
    """How many times one exception type may fail before the turn ends.

    ``0`` disables. Missing or junk config stays at 3.
    """
    raw = (agent_cfg or {}).get("same_error_limit", 3)
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        return 3
    return limit


def note_same_error(
    counts: dict[str, int],
    data: dict[str, Any] | None,
    *,
    limit: int,
) -> bool:
    """True when this result is the one that hits the cap.

    Only ``status == "error"`` plus an exception type counts. The output
    text is not read. A non-identifier is not a type, so a sentence
    stuffed into the field cannot open a new bucket.
    """
    if limit <= 0 or not isinstance(data, dict):
        return False
    if data.get("status") != "error":
        return False
    exc_type = data.get("exception_type")
    if not isinstance(exc_type, str) or not exc_type.isidentifier():
        return False
    counts[exc_type] = int(counts.get(exc_type, 0)) + 1
    return counts[exc_type] >= limit


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
