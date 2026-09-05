"""First-match inject steps for ``apply_no_call_path``.

The no-call path used to be one if/elif chain. Order is load-bearing: SMS
beats email beats inbox beats agenda, the same way the chain did. Each
step returns ``skip``, ``nudge`` (another round), or ``inject`` (fill
``r.calls`` and stop trying later steps).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from arelis.attachments import (
    overlay_text_from_ask,
    parse_attachments_from_turn,
    split_attachments_turn,
    wants_image_edit,
)
from arelis.core.agenda_complete import (
    agenda_force_call_notice,
    agenda_force_close_notice,
    agenda_force_delete_notice,
    agenda_force_open_notice,
    agenda_force_read_notice,
    agenda_read_action,
    draft_agenda_create_args,
    draft_agenda_delete_args,
    looks_like_calendar_close,
    looks_like_calendar_delete,
    looks_like_calendar_open,
    looks_like_calendar_read,
)
from arelis.core.agent_loop import _native_tool_call
from arelis.core.claims import (
    catalog_force_notice,
    contact_who_from_text,
    draft_catalog_args,
    last_store_ids_from_context,
    local_store_inject_args,
    weather_force_notice,
)
from arelis.core.email_complete import (
    draft_send_email_args,
    email_force_call_notice,
    email_remaining,
    looks_like_mailbox_mutate,
    looks_like_schedule_manage,
    looks_like_scheduled_send,
)
from arelis.core.events import Event, EventType
from arelis.core.image_refs import (
    fill_image_edit_args,
    fill_image_gen_args,
    fill_vision_args,
    image_force_call_notice,
    latest_generated_image_path,
)
from arelis.core.intent_catalog import (
    EARTH_STATUS,
    SOLAR_STATUS,
    earth_status_action,
    solar_status_action,
)
from arelis.core.look import next_look_call
from arelis.core.preflight import (
    draft_browser_args,
    draft_rooms_create_args,
    draft_signin_click_args,
    looks_like_browser_click_signin,
    looks_like_room_create,
)
from arelis.core.sms_complete import (
    draft_send_sms_args,
    looks_like_browser_or_url,
    looks_like_contacts_followup,
    looks_like_contacts_utterance,
    looks_like_goals_utterance,
    looks_like_image_gen,
    looks_like_memory_utterance,
    looks_like_tasks_utterance,
    sms_force_call_notice,
)
from arelis.core.tile_complete import match_tile_intent, tile_tool_args
from arelis.core.turn_context import TurnContext
from arelis.tools.inbox import draft_inbox_mutate_args
from arelis.tools.weather import draft_weather_args, weather_places_missing

SKIP = "skip"
NUDGE = "nudge"
INJECT = "inject"
# Matched the original elif but did nothing. Must not fall through.
STOP = "stop"

StepFn = Callable[[Any, TurnContext, Any], Awaitable[str]]


async def _nudge(
    loop: Any,
    r: Any,
    *,
    notice: str,
    thinking: str,
    gate: str = "",
) -> str:
    await loop._retract()
    r.messages.append({"role": "assistant", "content": r.content})
    r.messages.append({"role": "user", "content": notice})
    await loop.bus.publish(Event(EventType.THINKING, {"text": thinking}))
    if loop._timer is not None and gate:
        loop._timer.mark("exactness", gate=gate, action="nudge")
    return NUDGE


async def _inject(
    loop: Any,
    r: Any,
    name: str,
    args: dict[str, Any],
    *,
    thinking: str,
    gate: str = "",
    calls: list[tuple[str, dict[str, Any]]] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> str:
    r.calls = calls if calls is not None else [(name, args)]
    r.tool_calls = (
        tool_calls
        if tool_calls is not None
        else [_native_tool_call(n, a) for n, a in r.calls]
    )
    await loop._retract()
    await loop.bus.publish(Event(EventType.THINKING, {"text": thinking}))
    if loop._timer is not None and gate:
        loop._timer.mark("exactness", gate=gate, action="inject")
    return INJECT


async def try_sms(loop: Any, ctx: TurnContext, r: Any) -> str:
    sms_draft = r.sms_draft
    sms_remaining: list[str] = []
    if sms_draft is not None and sms_draft.complete:
        sent_l = {s.lower() for s in r.sms_sent}
        sms_remaining = [
            a
            for a in sms_draft.resolved_aliases
            if a and a.lower() not in sent_l
        ]
        if not sms_remaining and not r.sms_sent and sms_draft.tool_to:
            sms_remaining = [sms_draft.tool_to]
    if not (
        bool(r.agent_cfg.get("sms_force_call", True))
        and sms_draft is not None
        and sms_draft.complete
        and sms_remaining
        and "send_sms" in r.tool_names
    ):
        return SKIP
    if ctx.sms_nudge_used < 1:
        ctx.sms_nudge_used += 1
        return await _nudge(
            loop,
            r,
            notice=sms_force_call_notice(sms_draft, already_sent=r.sms_sent),
            thinking="SMS draft ready; asking for a real send_sms call",
            gate="sms_force",
        )
    if ctx.sms_failed:
        return STOP
    return await _inject(
        loop,
        r,
        "send_sms",
        draft_send_sms_args(sms_draft, already_sent=r.sms_sent),
        thinking="inject  send_sms from draft",
        gate="sms_force",
    )


async def try_email(loop: Any, ctx: TurnContext, r: Any) -> str:
    email_draft = r.email_draft
    if not (
        bool(r.agent_cfg.get("email_force_call", True))
        and email_draft is not None
        and email_draft.complete
        and email_remaining(email_draft, ctx.email_sent)
        and "send_email" in r.tool_names
    ):
        return SKIP
    if ctx.email_nudge_used < 1:
        ctx.email_nudge_used += 1
        return await _nudge(
            loop,
            r,
            notice=email_force_call_notice(email_draft, already_sent=ctx.email_sent),
            thinking="email draft ready; asking for a real send_email call",
            gate="email_force",
        )
    return await _inject(
        loop,
        r,
        "send_email",
        draft_send_email_args(email_draft, already_sent=ctx.email_sent),
        thinking="inject  send_email from draft",
        gate="email_force",
    )


async def try_inbox(loop: Any, ctx: TurnContext, r: Any) -> str:
    if not (
        looks_like_mailbox_mutate(r.text)
        and "inbox" in r.tool_names
        and not ctx.inbox_mutated_ok
    ):
        return SKIP
    inbox = loop.tools.get("inbox")
    hits = getattr(inbox, "last_hits", None) if inbox is not None else None
    inj = draft_inbox_mutate_args(
        r.text,
        last_hits=hits if isinstance(hits, list) else None,
    )
    action = str(inj.get("action") or "").lower()
    if action == "search" and "inbox" in loop.tools_used:
        inj = {}
    if not inj:
        return STOP
    return await _inject(
        loop,
        r,
        "inbox",
        inj,
        thinking="inject  inbox from intent",
        gate="inbox_mutate",
    )


async def try_agenda_create(loop: Any, ctx: TurnContext, r: Any) -> str:
    agenda_draft = r.agenda_draft
    if not (
        bool(r.agent_cfg.get("agenda_force_call", True))
        and agenda_draft is not None
        and agenda_draft.complete
        and "agenda" in r.tool_names
        and not ctx.agenda_create_ok
    ):
        return SKIP
    if ctx.agenda_nudge_used < 1:
        ctx.agenda_nudge_used += 1
        return await _nudge(
            loop,
            r,
            notice=agenda_force_call_notice(agenda_draft),
            thinking="agenda draft ready; asking for a real agenda create call",
            gate="agenda_force",
        )
    return await _inject(
        loop,
        r,
        "agenda",
        draft_agenda_create_args(agenda_draft),
        thinking="inject  agenda create from draft",
        gate="agenda_force",
    )


async def try_agenda_delete(loop: Any, ctx: TurnContext, r: Any) -> str:
    if not (
        bool(r.agent_cfg.get("agenda_force_call", True))
        and looks_like_calendar_delete(r.text)
        and "agenda" in r.tool_names
        and "agenda" not in loop.tools_used
        and "agenda" in loop._expected_tools
    ):
        return SKIP
    if ctx.agenda_nudge_used < 1:
        ctx.agenda_nudge_used += 1
        return await _nudge(
            loop,
            r,
            notice=agenda_force_delete_notice(),
            thinking="agenda delete ready; asking for a real agenda delete call",
        )
    return await _inject(
        loop,
        r,
        "agenda",
        draft_agenda_delete_args(
            r.text,
            receipts=loop._receipts,
            history=loop.memory.messages,
        ),
        thinking="inject  agenda delete",
    )


async def try_agenda_close(loop: Any, ctx: TurnContext, r: Any) -> str:
    if not (
        bool(r.agent_cfg.get("agenda_force_call", True))
        and looks_like_calendar_close(r.text)
        and "agenda" in r.tool_names
        and "agenda" not in loop.tools_used
    ):
        return SKIP
    if ctx.agenda_nudge_used < 1:
        ctx.agenda_nudge_used += 1
        return await _nudge(
            loop,
            r,
            notice=agenda_force_close_notice(),
            thinking="agenda close ready; asking for a real agenda close call",
        )
    return await _inject(
        loop, r, "agenda", {"action": "close"}, thinking="inject  agenda close from intent"
    )


async def try_agenda_open(loop: Any, ctx: TurnContext, r: Any) -> str:
    if not (
        bool(r.agent_cfg.get("agenda_force_call", True))
        and looks_like_calendar_open(r.text)
        and "agenda" in r.tool_names
        and "agenda" not in loop.tools_used
    ):
        return SKIP
    if ctx.agenda_nudge_used < 1:
        ctx.agenda_nudge_used += 1
        return await _nudge(
            loop,
            r,
            notice=agenda_force_open_notice(),
            thinking="agenda open ready; asking for a real agenda open call",
        )
    return await _inject(
        loop, r, "agenda", {"action": "open"}, thinking="inject  agenda open from intent"
    )


async def try_tile(loop: Any, ctx: TurnContext, r: Any) -> str:
    if not (
        match_tile_intent(r.text)
        and "tile" in r.tool_names
        and "tile" not in loop.tools_used
    ):
        return SKIP
    from arelis.tools.tile import TileTool

    hit = match_tile_intent(r.text)
    calendar_uses_agenda = (
        hit is not None and hit[1] == "calendar" and "agenda" in r.tool_names
    )
    inj = None if calendar_uses_agenda else tile_tool_args(r.text, last_name=TileTool.last_name)
    if not inj:
        return STOP
    return await _inject(loop, r, "tile", inj, thinking="inject  tile from intent")


async def try_agenda_read(loop: Any, ctx: TurnContext, r: Any) -> str:
    if not (
        bool(r.agent_cfg.get("agenda_force_call", True))
        and looks_like_calendar_read(r.text)
        and "agenda" in r.tool_names
        and "agenda" not in loop.tools_used
        and ("agenda" in loop._expected_tools or r.exact_need.needs_agenda)
    ):
        return SKIP
    if ctx.agenda_nudge_used < 1:
        ctx.agenda_nudge_used += 1
        return await _nudge(
            loop,
            r,
            notice=agenda_force_read_notice(agenda_read_action(r.text)),
            thinking="agenda read ready; asking for a real agenda list call",
        )
    return await _inject(
        loop,
        r,
        "agenda",
        {"action": agenda_read_action(r.text)},
        thinking="inject  agenda read from intent",
    )


async def try_image(loop: Any, ctx: TurnContext, r: Any) -> str:
    if not (
        bool(r.agent_cfg.get("image_force_call", True))
        and "image_edit" not in loop._expected_tools
        and "image_edit" not in r.preflight_kinds
        and not wants_image_edit(split_attachments_turn(r.text)[1] or r.text)
        and "image" in loop._expected_tools
        and "image" not in loop.tools_used
        and not ctx.image_attempted
        and "image" in r.tool_names
        and (looks_like_image_gen(r.text) or "image_gen" in r.preflight_kinds)
    ):
        return SKIP
    if ctx.image_nudge_used < 1:
        ctx.image_nudge_used += 1
        return await _nudge(
            loop,
            r,
            notice=image_force_call_notice(prompt_hint=r.text),
            thinking="image ask ready; asking for a real image call",
            gate="image_force",
        )
    ask = split_attachments_turn(r.text)[1] or r.text
    history = getattr(getattr(loop, "memory", None), "messages", None)
    inj_image: dict[str, Any] = {"prompt": ask.strip()[:300]}
    inj_image = fill_image_gen_args(inj_image, history=history, user_text=ask)
    return await _inject(
        loop,
        r,
        "image",
        inj_image,
        thinking="inject  image from intent",
    )


async def try_image_edit(loop: Any, ctx: TurnContext, r: Any) -> str:
    if not (
        bool(r.agent_cfg.get("image_force_call", True))
        and "image_edit" in loop._expected_tools
        and "image_edit" not in loop.tools_used
        and "image_edit" in r.tool_names
        and (
            wants_image_edit(split_attachments_turn(r.text)[1] or r.text)
            or "image_edit" in r.preflight_kinds
        )
    ):
        return SKIP
    ask = split_attachments_turn(r.text)[1] or r.text
    rows = parse_attachments_from_turn(r.text)
    path = str(rows[0].get("path") or "") if rows else ""
    history = getattr(getattr(loop, "memory", None), "messages", None)
    inj_edit: dict[str, Any] = {"path": path} if path else {}
    if re.search(r"(?i)youtube|\bthumbnail\b", ask):
        inj_edit["preset"] = "youtube_thumbnail"
    if re.search(r"(?i)vibrant|vibrance|saturat", ask):
        inj_edit["vibrance"] = 1.3
    if re.search(r"(?i)grayscale|greyscale|black[\s-]?and[\s-]?white|\bb\s*&\s*w\b", ask):
        inj_edit["grayscale"] = True
    if re.search(r"(?i)\b(?:flip|mirror)\b", ask):
        inj_edit["flip"] = (
            "vertical" if re.search(r"(?i)vertical|upside", ask) else "horizontal"
        )
    rot = re.search(r"(?i)rotate(?:\s+(?:it|this|that))?\s+(\d{1,3})", ask)
    if rot:
        inj_edit["rotate"] = int(rot.group(1))
    elif re.search(r"(?i)upside[\s-]?down", ask):
        inj_edit["rotate"] = 180
    elif re.search(r"(?i)rotate\s+(?:left|ccw|counter)", ask):
        inj_edit["rotate"] = 270
    elif re.search(r"(?i)\brotate\b", ask):
        inj_edit["rotate"] = 90
    if re.search(r"(?i)\bblur", ask):
        inj_edit["blur"] = 4.0
    size = re.search(r"(?i)(\d{2,5})\s*(?:x|\u00d7|by)\s*(\d{2,5})", ask)
    if size:
        inj_edit["width"] = int(size.group(1))
        inj_edit["height"] = int(size.group(2))
        inj_edit.pop("preset", None)
    overlay = overlay_text_from_ask(ask)
    if overlay:
        inj_edit["text"] = overlay
        inj_edit["text_align"] = "center"
    inj_edit = fill_image_edit_args(inj_edit, history=history, user_text=ask)
    if not str(inj_edit.get("path") or "").strip():
        fallback = latest_generated_image_path(history)
        if fallback:
            inj_edit["path"] = fallback
    if not str(inj_edit.get("path") or "").strip():
        return STOP
    return await _inject(loop, r, "image_edit", inj_edit, thinking="inject  image_edit from intent")


async def try_look(loop: Any, ctx: TurnContext, r: Any) -> str:
    if loop._look is None:
        return SKIP
    nxt = next_look_call(
        loop._look.intent,
        path=loop._look.path,
        camera_done=loop._look.camera_snaps > 0,
        ocr_done=loop._look.ocr_done,
        vision_done=loop._look.vision_done,
        deferral=loop._look.deferral,
    )
    if nxt is None:
        return STOP
    inj_name, inj = nxt
    if inj_name not in r.tool_names:
        return STOP
    hit = await _inject(
        loop,
        r,
        inj_name,
        inj,
        thinking=f"inject  look {loop._look.intent.act} {inj_name}",
    )
    if loop._timer is not None:
        loop._timer.mark("look", act=loop._look.intent.act, tool=inj_name, action="inject")
    return hit


async def try_vision(loop: Any, ctx: TurnContext, r: Any) -> str:
    if not (
        bool(r.agent_cfg.get("vision_force_call", True))
        and "vision" in loop._expected_tools
        and "vision" not in loop.tools_used
        and "vision" in r.tool_names
    ):
        return SKIP
    filled = fill_vision_args({}, history=loop.memory.messages, user_text=r.text)
    path = str(filled.get("path") or "")
    from arelis.attachments import attachment_kinds_from_turn

    attached = "image" in attachment_kinds_from_turn(r.text)
    label = "attached" if attached else "generated"
    if ctx.vision_nudge_used < 1:
        ctx.vision_nudge_used += 1
        return await _nudge(
            loop,
            r,
            notice=(
                f"Call vision now with the {label} image path"
                + (f" path={path}" if path else "")
                + ". Do not web_search."
            ),
            thinking="vision ask ready; asking for vision call",
        )
    if not path:
        return STOP
    return await _inject(loop, r, "vision", {"path": path}, thinking="inject  vision from intent")


async def try_weather(loop: Any, ctx: TurnContext, r: Any) -> str:
    if not (
        bool(r.agent_cfg.get("weather_force_call", True))
        and r.exact_need.needs_weather
        and not looks_like_scheduled_send(r.text)
        and not looks_like_schedule_manage(r.text)
        and not ctx.schedule_managed_ok
        and weather_places_missing(r.text, r.weather_ok_places)
        and "weather" in r.tool_names
    ):
        return SKIP
    if ctx.weather_nudge_used < 1 and not r.weather_ok_places:
        ctx.weather_nudge_used += 1
        return await _nudge(
            loop,
            r,
            notice=weather_force_notice(),
            thinking="weather ask; asking for a real weather call",
            gate="weather_force",
        )
    inj = draft_weather_args(r.text)
    missing = weather_places_missing(r.text, r.weather_ok_places)
    if missing:
        if missing[0]:
            inj["place"] = missing[0]
        else:
            inj.pop("place", None)
    return await _inject(
        loop, r, "weather", inj, thinking="inject  weather from intent", gate="weather_force"
    )


async def try_catalog(loop: Any, ctx: TurnContext, r: Any) -> str:
    if not (
        not (r.content or "").strip()
        and r.numeric_gate
        and r.exact_need.needs_catalog
        and not r.ledger.has_ok("catalog")
        and "catalog" in r.tool_names
        and "catalog" not in loop.tools_used
    ):
        return SKIP
    if not ctx.catalog_nudge_used:
        ctx.catalog_nudge_used = True
        return await _nudge(
            loop,
            r,
            notice=catalog_force_notice(),
            thinking="catalog ask; asking for a real catalog call",
            gate="catalog_force",
        )
    return await _inject(
        loop,
        r,
        "catalog",
        draft_catalog_args(r.text),
        thinking="inject  catalog from intent",
        gate="catalog_force",
    )


async def try_tasks(loop: Any, ctx: TurnContext, r: Any) -> str:
    if not (
        bool(r.agent_cfg.get("tasks_force_call", True))
        and (
            r.exact_need.needs_tasks
            or "tasks" in loop._expected_tools
            or looks_like_tasks_utterance(r.text)
        )
        and "tasks" not in loop.tools_used
        and "tasks" in r.tool_names
    ):
        return SKIP
    return await _inject(
        loop,
        r,
        "tasks",
        local_store_inject_args(
            "tasks", r.text, receipts=loop._receipts, history=loop.memory.messages
        ),
        thinking="inject  tasks from intent",
        gate="tasks_force",
    )


async def try_goals(loop: Any, ctx: TurnContext, r: Any) -> str:
    if not (
        bool(r.agent_cfg.get("goals_force_call", True))
        and (
            r.exact_need.needs_goals
            or "goals" in loop._expected_tools
            or looks_like_goals_utterance(r.text)
        )
        and "goals" not in loop.tools_used
        and "goals" in r.tool_names
    ):
        return SKIP
    ids = last_store_ids_from_context(loop.memory.messages, loop._receipts)
    if re.search(r"(?i)\b(?:both|all)\b", r.text or "") and len(ids) > 1:
        calls = [("goals", {"action": "remove", "id": gid}) for gid in ids]
        return await _inject(
            loop,
            r,
            "goals",
            {},
            thinking="inject  goals from intent",
            gate="goals_force",
            calls=calls,
        )
    return await _inject(
        loop,
        r,
        "goals",
        local_store_inject_args(
            "goals", r.text, receipts=loop._receipts, history=loop.memory.messages
        ),
        thinking="inject  goals from intent",
        gate="goals_force",
    )


async def try_memory(loop: Any, ctx: TurnContext, r: Any) -> str:
    if not (
        ("memory" in loop._expected_tools or looks_like_memory_utterance(r.text))
        and "memory" not in loop.tools_used
        and "memory" in r.tool_names
    ):
        return SKIP
    if ctx.memory_nudge_used < 1:
        ctx.memory_nudge_used += 1
        return await _nudge(
            loop,
            r,
            notice=(
                "Call the memory tool now. Use action=remember "
                "or action=forget with the fact quoted from "
                "the user. Do not call recall instead, and "
                "do not open a browser."
            ),
            thinking="memory ask; asking for a real memory call",
        )
    return await _inject(
        loop,
        r,
        "memory",
        local_store_inject_args("memory", r.text),
        thinking="inject  memory from intent",
    )


async def try_contacts(loop: Any, ctx: TurnContext, r: Any) -> str:
    if not (
        (
            "contacts" in loop._expected_tools
            or looks_like_contacts_utterance(r.text)
            or looks_like_contacts_followup(r.text, loop.memory.messages)
        )
        and "contacts" not in loop.tools_used
        and "contacts" in r.tool_names
    ):
        return SKIP
    who = contact_who_from_text(r.text)
    if not who:
        for item in reversed(loop.memory.messages[-8:]):
            role = getattr(item, "role", "")
            content_h = getattr(item, "content", "") or ""
            if role == "user":
                who = contact_who_from_text(str(content_h))
                if who:
                    break
    return await _inject(
        loop,
        r,
        "contacts",
        {"action": "get", "who": who or "wife"},
        thinking="inject  contacts from intent",
    )


async def try_solar_status(loop: Any, ctx: TurnContext, r: Any) -> str:
    if not (
        SOLAR_STATUS.matches(r.text)
        and "solar" in r.tool_names
        and "solar" not in loop.tools_used
    ):
        return SKIP
    return await _inject(
        loop,
        r,
        "solar",
        {"action": solar_status_action(r.text)},
        thinking="inject  solar from status/dump ask",
    )


async def try_earth_status(loop: Any, ctx: TurnContext, r: Any) -> str:
    if not (
        EARTH_STATUS.matches(r.text)
        and "earth" in r.tool_names
        and "earth" not in loop.tools_used
    ):
        return SKIP
    return await _inject(
        loop,
        r,
        "earth",
        {"action": earth_status_action(r.text)},
        thinking="inject  earth from status/dump ask",
    )


async def try_browser(loop: Any, ctx: TurnContext, r: Any) -> str:
    if not (
        ("browser" in loop._expected_tools or looks_like_browser_or_url(r.text))
        and not looks_like_calendar_open(r.text)
        and not looks_like_calendar_close(r.text)
        and not match_tile_intent(r.text)
        and not SOLAR_STATUS.matches(r.text)
        and not EARTH_STATUS.matches(r.text)
        and "browser" not in loop.tools_used
        and "browser" in r.tool_names
    ):
        return SKIP
    return await _inject(
        loop,
        r,
        "browser",
        draft_browser_args(r.text),
        thinking="inject  browser from intent",
    )


async def try_browser_signin(loop: Any, ctx: TurnContext, r: Any) -> str:
    if not (
        looks_like_browser_click_signin(r.text)
        and "browser" in loop.tools_used
        and not ctx.browser_clicked
        and "browser" in r.tool_names
    ):
        return SKIP
    inj = draft_signin_click_args(ctx.last_browser_snapshot)
    if not inj:
        return STOP
    return await _inject(
        loop,
        r,
        "browser",
        inj,
        thinking=f"inject  browser click Sign in ref={inj.get('ref')}",
    )


async def try_rooms(loop: Any, ctx: TurnContext, r: Any) -> str:
    if not (
        ("rooms" in loop._expected_tools or looks_like_room_create(r.text))
        and "rooms" not in loop.tools_used
        and "rooms" in r.tool_names
    ):
        return SKIP
    return await _inject(
        loop,
        r,
        "rooms",
        draft_rooms_create_args(r.text),
        thinking="inject  rooms create from intent",
    )


# Order matches the original if/elif chain. Do not reorder without a test.
INJECT_STEPS: tuple[StepFn, ...] = (
    try_sms,
    try_email,
    try_inbox,
    try_agenda_create,
    try_agenda_delete,
    try_agenda_close,
    try_agenda_open,
    try_tile,
    try_agenda_read,
    try_image,
    try_image_edit,
    try_look,
    try_vision,
    try_weather,
    try_catalog,
    try_tasks,
    try_goals,
    try_memory,
    try_contacts,
    try_solar_status,
    try_earth_status,
    try_browser,
    try_browser_signin,
    try_rooms,
)


async def run_inject_steps(loop: Any, ctx: TurnContext, r: Any) -> str:
    """First matching step wins. ``nudge`` / ``inject`` / ``none``."""
    for step in INJECT_STEPS:
        hit = await step(loop, ctx, r)
        if hit != SKIP:
            return hit
    return "none"

