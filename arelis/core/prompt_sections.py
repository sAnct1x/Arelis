from __future__ import annotations

from typing import Any

from arelis.contacts import contacts_prompt_line
from arelis.core.agent_loop import _wants_project_context, now_line, theme_line
from arelis.core.episodes import episodes_prompt_line
from arelis.core.lessons import format_lessons, select_lessons
from arelis.core.world_state import world_state_prompt_line
from arelis.memory.store import MemoryStore
from arelis.profile import standing_profile_prompt_line


def append_stopped_turn_note(
    messages: list[dict[str, str]],
    stopped_ask: str,
) -> None:
    """Append the prior interrupted ask, when speech control supplied one."""
    if not (stopped_ask or "").strip():
        return
    from arelis.core.confirm_speech import stopped_ask_note

    hint = stopped_ask_note(stopped_ask)
    if hint:
        messages.append({"role": "system", "content": hint})


def append_nasa_fact_guidance(
    messages: list[dict[str, str]],
    text: str,
) -> bool:
    """Pin planet / Mars-moon numbers before the model answers. Native-safe."""
    from arelis.physics.fact_sheet import append_reference_facts

    return append_reference_facts(messages, text)


def append_preflight_guidance(
    messages: list[dict[str, str]],
    loop: Any,
    text: str,
    agent_cfg: dict[str, Any],
    *,
    see_no_sms_redirect: set[str] | frozenset[str],
) -> list[str]:
    """Pin NASA facts. Tool choice is the model's, from the schemas it was given."""
    del loop, agent_cfg, see_no_sms_redirect
    append_nasa_fact_guidance(messages, text)
    return []


def append_turn_goal(
    messages: list[dict[str, str]],
    loop: Any,
    text: str,
    role: str,
    *,
    preflight_kinds: list[str],
    sms_draft: Any,
    email_draft: Any,
    research_mode: bool,
) -> Any:
    """Append the turn objective after it has rewritten expected tools."""
    from arelis.core.turn_goal import apply_goal_to_expected, derive_turn_goal

    turn_goal = derive_turn_goal(
        text,
        role,
        kinds=preflight_kinds,
        sms_draft=sms_draft,
        email_draft=email_draft,
        research_mode=research_mode,
    )
    loop._expected_tools, dropped_for_goal = apply_goal_to_expected(
        loop._expected_tools, turn_goal
    )
    if turn_goal.line:
        messages.append({"role": "system", "content": f"Turn goal: {turn_goal.line}"})
    if loop._timer is not None and (turn_goal.kind != "none" or dropped_for_goal):
        loop._timer.mark(
            "goal",
            kind=turn_goal.kind,
            dropped=",".join(dropped_for_goal) or "-",
        )
    return turn_goal


def append_plan_and_lessons(
    messages: list[dict[str, str]],
    loop: Any,
    text: str,
    agent_cfg: dict[str, Any],
    *,
    preflight_kinds: list[str],
    skill_ids: list[str],
    active_plan: Any,
) -> None:
    """Append execution-plan guidance followed by matched failure lessons."""
    plan_msg = active_plan.message if active_plan else None
    if plan_msg:
        messages.append({"role": "system", "content": plan_msg})
        if loop._timer is not None:
            loop._timer.mark(
                "plan_nudge",
                skills=",".join(skill_ids) or "-",
                plan=active_plan.id if active_plan else "-",
            )
    if bool(agent_cfg.get("lessons", True)):
        lesson_block = format_lessons(
            select_lessons(
                skill_ids=skill_ids,
                preflight_kinds=preflight_kinds,
                user_text=text,
            )
        )
        if lesson_block:
            messages.append({"role": "system", "content": lesson_block})


def append_stable_operating_context(
    messages: list[dict[str, str]],
    loop: Any,
    *,
    active_room: Any,
) -> None:
    """Append slowly changing user and room context.

    These lines are byte-stable across ordinary turns, so they belong in the
    cached prefix, ahead of history. Putting them after history made the
    model re-prefill the same profile, contacts, facts, and location on
    every follow-up.
    """
    if active_room is not None:
        messages.append({"role": "system", "content": active_room.prompt_block()})

    location = loop.config.get("_location")
    if location is not None:
        place_line = location.prompt_line()
        if place_line:
            messages.append({"role": "system", "content": place_line})
    profile_line = standing_profile_prompt_line(config=loop.config)
    if profile_line:
        messages.append({"role": "system", "content": profile_line})
    contacts_line = contacts_prompt_line()
    if contacts_line:
        messages.append({"role": "system", "content": contacts_line})
    # Durable facts, preferences, and decisions are selected per turn in
    # memories_prompt_for_turn and appended to the volatile tail, so a
    # long unranked list cannot crowd the cached prefix.

    store = loop.memory.sink if isinstance(loop.memory.sink, MemoryStore) else None
    if store is not None:
        episode_line = episodes_prompt_line(store, limit=3)
        if episode_line:
            messages.append({"role": "system", "content": episode_line})


def append_volatile_operating_context(
    messages: list[dict[str, str]],
    loop: Any,
    *,
    role: str,
    model: str,
    skill_ids: list[str],
) -> None:
    """Append this-turn project and world-state lines after history."""
    workspace = loop.config.get("_workspace")
    if workspace is not None and _wants_project_context(
        role=role,
        skill_ids=skill_ids,
        expected_tools=loop._expected_tools,
    ):
        project_line = workspace.prompt_line()
        if project_line:
            messages.append({"role": "system", "content": project_line})
    store = loop.memory.sink if isinstance(loop.memory.sink, MemoryStore) else None
    world_line = world_state_prompt_line(
        loop.config,
        role=role,
        model=model,
        workspace=workspace,
        store=store,
    )
    if world_line:
        messages.append({"role": "system", "content": world_line})


def append_operating_context(
    messages: list[dict[str, str]],
    loop: Any,
    *,
    role: str,
    model: str,
    skill_ids: list[str],
    active_room: Any,
) -> None:
    """Append operating context in the historical combined order.

    Prefer the stable/volatile split at the call site so the stable
    half can sit in the cached prefix.
    """
    append_stable_operating_context(messages, loop, active_room=active_room)
    append_volatile_operating_context(
        messages, loop, role=role, model=model, skill_ids=skill_ids
    )


def append_stable_delivery_context(
    messages: list[dict[str, str]],
    loop: Any,
    *,
    speak: bool,
) -> None:
    """Append spoken policy, language, and the screen theme.

    These change only when conversation mode, the reply language, or the
    theme changes, so they belong in the cached prefix. The clock still
    goes after history, via append_clock.
    """
    if speak:
        from arelis.talk_language import spoken_policy

        messages.append(
            {
                "role": "system",
                "content": spoken_policy(loop.config.get("_reply_language")),
            }
        )
    from arelis.talk_language import reply_instruction

    lang_note = reply_instruction(loop.config.get("_reply_language"))
    if lang_note:
        messages.append({"role": "system", "content": lang_note})
    messages.append({"role": "system", "content": theme_line()})


def append_clock(
    messages: list[dict[str, str]],
    loop: Any,
) -> None:
    """Append the machine clock. It changes on its own, so it trails history."""
    messages.append({"role": "system", "content": now_line(loop.config)})


def append_delivery_context(
    messages: list[dict[str, str]],
    loop: Any,
    *,
    speak: bool,
) -> None:
    """Append spoken-answer policy, language, the screen theme, then the clock.

    The clock stays last. It is the line that changes on its own.
    """
    append_stable_delivery_context(messages, loop, speak=speak)
    append_clock(messages, loop)
