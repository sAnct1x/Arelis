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


def append_operating_context(
    messages: list[dict[str, str]],
    loop: Any,
    *,
    role: str,
    model: str,
    skill_ids: list[str],
    active_room: Any,
) -> None:
    """Append project, room, user, memory, and world-state context in order."""
    workspace = loop.config.get("_workspace")
    if workspace is not None and _wants_project_context(
        role=role,
        skill_ids=skill_ids,
        expected_tools=loop._expected_tools,
    ):
        project_line = workspace.prompt_line()
        if project_line:
            messages.append({"role": "system", "content": project_line})
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
    facts_line = loop._active_facts_line()
    if facts_line:
        messages.append({"role": "system", "content": facts_line})

    store = loop.memory.sink if isinstance(loop.memory.sink, MemoryStore) else None
    if store is not None:
        episode_line = episodes_prompt_line(store, limit=3)
        if episode_line:
            messages.append({"role": "system", "content": episode_line})
    world_line = world_state_prompt_line(
        loop.config,
        role=role,
        model=model,
        workspace=workspace,
        store=store,
    )
    if world_line:
        messages.append({"role": "system", "content": world_line})


def append_delivery_context(
    messages: list[dict[str, str]],
    loop: Any,
    *,
    speak: bool,
) -> None:
    """Append spoken-answer policy, language, the screen theme, then the clock.

    The clock stays last. It is the line that changes on its own. The theme
    changes only when they pick one, so it sits just ahead of the clock and
    never in the cached prefix.
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
    messages.append({"role": "system", "content": now_line()})
