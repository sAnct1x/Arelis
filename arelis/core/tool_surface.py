"""Which tools the model is offered this round. Two phases, one copy each.

`turn_prepare` builds the surface for round one and `turn_round` rebuilds it
when the turn escalates to a bigger model. The two had the same seven steps in
the same order, written twice, and they had drifted: the escalate copy did not
pass `extra_skill_ids`, so the active room's skills were in reach on round one
and gone on round two. The comment in `turn_prepare` explaining why room extras
ride on `filter_tool_names` — "keep analyze/cas in reach" — was true for
exactly as long as the turn did not escalate.

The roadmap called this "one function, called twice". It is two, and that is
the reason the drift was invisible. In `turn_prepare` the steps are 130 lines
apart, because everything between them is what decides `loop._expected_tools`:
preflight hints add to it, the weather narrowing discards from it, and the turn
goal rewrites it. The second phase reads that set, so it cannot move up. In
`turn_round` the two run back to back, because on escalate the set was settled
last round.

So: `base_surface` is what the role, the text and the room allow, and
`apply_expected` is what this turn's intent then does to it.
"""

from __future__ import annotations

import logging
from typing import Any

from arelis.core.agent_loop import (
    _HIDE_WANDER_FOR,
    _hide_daily_wander,
    _offer_expected,
)
from arelis.core.look import LOOK_TOOL_SUBSET
from arelis.core.sms_complete import looks_like_stale_sms_skip
from arelis.core.tool_subset import filter_tool_names

log = logging.getLogger(__name__)


def cap_to_room(available_all: set[str], active_room: Any) -> set[str]:
    """Apply a room's explicit `tools:` cage, and say so when it cannot hold.

    Rooms lean rather than cage by default — `rooms.py` argues the point at
    length, that a caged agent which has to refuse the time of day teaches you
    to stop asking. So a `tools:` list is not a side effect of naming a folder,
    it is a decision somebody made, and it is worth a line in the log when it
    does not mean what it says.

    A name that is not installed drops out of the cage silently: a typo, a tool
    since renamed, a room written against a build that had it. When *every*
    name drops out the cage disappears and the room gets the whole registry —
    while the rooms tool goes on printing "limited to tools: …" either way.

    The fail-open is deliberate and stays. A room cut down to nothing could not
    answer anything, which is worse than an unenforced cage and is the exact
    failure rooms lean to avoid. What changes is that it is no longer quiet.
    """
    named = {n for n in (getattr(active_room, "tools", None) or ()) if n}
    if not named:
        return available_all
    missing = named - available_all
    capped = available_all & named
    if not capped:
        log.warning(
            "Room %r limits tools to %s, none of which are installed — the "
            "limit cannot be applied and the room is leaning on the full tool "
            "set instead.",
            getattr(active_room, "name", "?"),
            ", ".join(sorted(named)),
        )
        return available_all
    if missing:
        log.warning(
            "Room %r limits tools to %s, but %s %s not installed and will be ignored.",
            getattr(active_room, "name", "?"),
            ", ".join(sorted(named)),
            ", ".join(sorted(missing)),
            "is" if len(missing) == 1 else "are",
        )
    return capped


def base_surface(
    loop: Any,
    available_all: set[str],
    *,
    role: str,
    text: str,
    agent_cfg: dict[str, Any],
    active_room: Any = None,
) -> tuple[set[str], set[str]]:
    """The surface before this turn's intent narrows it. Returns (available, visible).

    `active_room` is not optional in spirit — omitting it drops the room's
    skills, which is the bug this module exists to close. It is keyword-only
    and defaulted so the caller that has no room does not have to say so.
    """
    room_skills = tuple(active_room.spec.skills) if active_room is not None else ()
    visible = filter_tool_names(
        available_all,
        role=role,
        text=text,
        enabled=bool(agent_cfg.get("research_tool_subset", False)),
        skill_subset=bool(agent_cfg.get("skill_tool_subset", False)),
        history=loop.memory.messages,
        extra_skill_ids=room_skills,
    )
    available = visible
    if loop._look is not None:
        look_tools = {n for n in available_all if n in LOOK_TOOL_SUBSET}
        if look_tools:
            available = look_tools
            visible = look_tools
    return set(available), set(visible)


def apply_expected(
    loop: Any,
    available: set[str],
    *,
    text: str,
    available_all: set[str],
) -> tuple[set[str], set[str]]:
    """Narrow and widen by `loop._expected_tools`. Returns (available, visible).

    Must run after `_expected_tools` is final. In `turn_prepare` that is after
    the preflight hints, the weather narrowing and the turn goal have all had
    their say.
    """
    if loop._expected_tools & _HIDE_WANDER_FOR:
        available = _hide_daily_wander(set(available), loop._expected_tools)
    available = _offer_expected(available, loop._expected_tools, available_all)
    if (
        looks_like_stale_sms_skip(text, loop.memory.messages)
        and "send_sms" not in loop._expected_tools
    ) or loop._look is not None:
        available = set(available)
        available.discard("send_sms")
        available.discard("send_email")
    return set(available), set(available)
