from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from arelis.config import shipped_num_ctx
from arelis.core.agenda_complete import (
    complete_agenda_draft,
    looks_like_calendar_create,
    looks_like_calendar_delete,
    looks_like_calendar_read,
)
from arelis.core.agent_loop import (
    _SEE_NO_SMS_REDIRECT,
    _SPEAK_TOOL_OUTPUT_CHARS,
    disconnected_integration_reply,
    should_offer_tools,
    static_system_prefix,
    turn_expects_tool_round,
    wants_fresh_page_ask,
)
from arelis.core.cell_work import begin_cell_work
from arelis.core.claims import (
    apply_research_web_need,
    detect_exactness_need,
)
from arelis.core.context import context_budget
from arelis.core.email_complete import (
    complete_email_draft,
    looks_like_compose_email,
    looks_like_mailbox_mutate,
    looks_like_schedule_manage,
    looks_like_scheduled_send,
)
from arelis.core.events import Event, EventType
from arelis.core.image_refs import CAMERA_FRESH_S, latest_camera_image_file
from arelis.core.look import LookTurn, classify_look, frame_sha256
from arelis.core.other_work import looks_like_other_work
from arelis.core.prompt_sections import (
    append_delivery_context,
    append_operating_context,
    append_plan_and_lessons,
    append_preflight_guidance,
    append_stopped_turn_note,
    append_turn_goal,
)
from arelis.core.skills import select_skill_ids_detailed
from arelis.core.sms_complete import (
    complete_sms_draft,
    looks_like_closing_chitchat,
    sms_intent_this_turn,
)
from arelis.core.tool_subset import (
    is_research_mode,
    turn_round_budget,
)
from arelis.core.tool_surface import (
    apply_expected,
    base_surface,
    cap_to_room,
    session_tool_schemas,
)
from arelis.core.turn_context import TurnContext
from arelis.core.turn_telemetry import TurnTimer, turn_telemetry_enabled
from arelis.llm.router import ModelRole

log = logging.getLogger(__name__)


@dataclass
class _TurnStart:
    model: str
    speak: bool
    agent_cfg: dict[str, Any]
    ratio: float
    research_mode: bool
    available_all: set[str]
    active_room: Any
    available: set[str]
    visible: set[str]


async def _begin_turn(
    loop: Any,
    text: str,
    role: ModelRole,
    *,
    source: str,
    route_reason: str,
) -> _TurnStart:
    """Reset turn-local state, select the model, and build the base tool surface."""
    model = loop.router.model_for(role)
    # Phone conversation is this seat only. PC conversation being on
    # must not shorten phone replies, and the reverse is also true.
    if source == "mobile":
        speak = bool(loop.config.get("_phone_speak"))
    else:
        speak = bool(loop.config.get("_speak_replies"))
    loop._turn_source = source
    sink = loop.memory.sink
    session_id = str(getattr(sink, "session_id", None) or "")
    loop._timer = TurnTimer(
        source=source,
        role=role,
        speak=speak,
        user_chars=len(text),
        enabled=turn_telemetry_enabled(loop.config),
        session_id=session_id,
        route_reason=route_reason,
        user_text=text,
    )
    begin_cell_work(loop._timer.id)
    # Per-turn state — must not leak across conversation turns (soak found
    # tools_used accumulating and poisoning vision/image duplicate gates).
    loop.tools_used = set()
    browser = loop.tools.get("browser")
    if browser is not None:
        browser.pixel_ok = False
    desktop = loop.tools.get("desktop")
    if desktop is not None:
        desktop.pixel_ok = False
    from arelis.look_scratch import clear_look_pending, hold_look_files, keep_look_files

    clear_look_pending()
    hold_look_files(keep_look_files(text))
    loop._trace = []
    loop._agenda_create_ok = False
    loop._agenda_create_failed = False
    loop._agenda_create_where = ""
    loop._painted = ""
    loop._round_gap = False
    loop.model_started = False
    loop._cut_short_noted = False
    loop._tool_arg_line = ""
    # Mutable so mid-turn escalate (W2) can retarget the hot model.
    loop._turn_role = role
    loop._escalated = False
    loop._expected_tools = set()
    loop._fail_replan_used = False
    loop._think_off_next = False
    loop._active_plan = None
    loop._receipts = []
    dock_live = callable(loop.config.get("_camera_capture"))
    fresh = latest_camera_image_file(max_age_s=CAMERA_FRESH_S)
    look_intent = classify_look(
        text,
        dock_live=dock_live,
        fresh_path=fresh,
        history=loop.memory.messages,
    )
    loop._look = None
    if look_intent is not None:
        loop._look = LookTurn(
            intent=look_intent,
            path=str(look_intent.path or ""),
        )
        if loop._look.path:
            loop._look.sha = frame_sha256(loop._look.path)
    agent_cfg = loop.config.get("agent") or {}
    loop.max_rounds = turn_round_budget(role, text, agent_cfg, loop._default_max_rounds)
    active = getattr(loop.router, "active_model", None)
    if active and active != model:
        await loop.bus.publish(
            Event(
                EventType.MODEL_SWITCH,
                {"from": active, "to": model, "role": role},
            )
        )
    await loop.bus.publish(
        Event(EventType.STATUS, {"message": f"Role `{role}` -> model `{model}`"})
    )
    if (role or "").strip().lower() == "research":
        from arelis.llm.wire import same_model

        needs_swap = True
        try:
            fast_tag = str(loop.router.model_for("fast") or "")
            needs_swap = not same_model(fast_tag, model)
        except Exception:
            needs_swap = True
        if active and same_model(str(active), model):
            needs_swap = False
        if needs_swap:
            from arelis.llm.vram import free_gpu_neighbors

            await free_gpu_neighbors(loop.config, loop.bus)
            await loop.bus.publish(
                Event(
                    EventType.STATUS,
                    {
                        "message": (
                            f"Loading `{model}`, previous chat model was unloaded so it can fit."
                        )
                    },
                )
            )
    await loop.bus.publish(
        Event(
            EventType.THINKING,
            {"text": f"round 0/{loop.max_rounds}  composing with {model}"},
        )
    )

    ratio = loop._token_ratios.get(model)
    loop.memory.chars_per_token = ratio
    loop.memory.add("user", text)
    agent_cfg = loop.config.get("agent") or {}
    research_mode = is_research_mode(role, text)
    available_all = set(loop.tools.names())
    # Cap the source so every later recompute inherits a room's explicit cage.
    active_room = getattr(loop.config.get("_rooms"), "active", None)
    if active_room is not None:
        available_all = cap_to_room(available_all, active_room)
    available, visible = base_surface(
        loop,
        available_all,
        role=role,
        text=text,
        agent_cfg=agent_cfg,
        active_room=active_room,
    )
    if loop._timer is not None and len(visible) < len(available_all):
        loop._timer.mark(
            "tool_subset",
            visible=len(visible),
            available=len(available_all),
        )
    return _TurnStart(
        model=model,
        speak=speak,
        agent_cfg=agent_cfg,
        ratio=ratio,
        research_mode=research_mode,
        available_all=available_all,
        active_room=active_room,
        available=available,
        visible=visible,
    )


@dataclass
class _TurnDrafts:
    sms: Any
    email: Any
    agenda: Any
    skip_sms: bool


def _reconstruct_turn_drafts(loop: Any, text: str) -> _TurnDrafts:
    """Rebuild current SMS, email, and agenda drafts from live history."""
    # Image-gen / goals / file-write / calendar-create must not revive a
    # stale SMS draft unless this turn itself starts with an SMS verb.
    other_work = looks_like_other_work(text, loop.memory.messages)
    skip_sms = other_work and not re.match(
        r"(?i)^\s*(?:text|sms|txt|send\s+(?:a\s+)?(?:text|sms|message))\b",
        text or "",
    )
    sms_draft = (
        None
        if skip_sms
        else complete_sms_draft(text, history=loop.memory.messages)
    )
    # Scheduled sends and mailbox operations can contain "email" without
    # being letter composition.
    skip_email = other_work and (
        looks_like_scheduled_send(text)
        or looks_like_schedule_manage(text)
        or looks_like_mailbox_mutate(text)
        or not looks_like_compose_email(text)
    )
    email_draft = (
        None
        if skip_email
        else complete_email_draft(text, history=loop.memory.messages)
    )
    return _TurnDrafts(
        sms=sms_draft,
        email=email_draft,
        agenda=complete_agenda_draft(text, history=loop.memory.messages),
        skip_sms=skip_sms,
    )


async def _provider_context_tokens(loop: Any, role: ModelRole) -> int | None:
    """Server window when the provider can measure one."""
    router = getattr(loop, "router", None)
    provider = getattr(router, "provider", None)
    probe = getattr(provider, "context_tokens", None)
    if not callable(probe):
        return None
    model = ""
    model_for = getattr(router, "model_for", None)
    if callable(model_for):
        try:
            model = str(model_for(role) or "")
        except (RuntimeError, TypeError, ValueError) as exc:
            log.warning("Could not resolve the model for the context budget: %s", exc)
            model = ""
    try:
        found = await probe(model)
    except Exception as exc:
        log.warning("Could not read the server context window: %s", exc)
        return None
    try:
        value = int(found)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


async def _context_limits(
    loop: Any,
    role: ModelRole,
    *,
    speak: bool,
    skill_ids: list[str],
) -> tuple[int, int]:
    """Reserve context for pinned prompt sections and possible tool output."""
    lc = loop.config.get("llamacpp") or {}
    num_ctx = int(lc.get("default_cap") or shipped_num_ctx())
    measured = await _provider_context_tokens(loop, role)
    if measured:
        num_ctx = measured
    # Sticky for the turn so mid-escalate does not shrink under a built prompt.
    loop._turn_num_ctx = num_ctx
    tool_reserve_chars = (
        min(loop.tool_output_chars, _SPEAK_TOOL_OUTPUT_CHARS)
        if speak
        else loop.tool_output_chars
    )
    # Spoken small-talk should not sacrifice history to a scrape slab.
    if speak and not loop._expected_tools and not skill_ids:
        tool_reserve_chars = 0
    return num_ctx, tool_reserve_chars


async def _attach_tool_schemas_and_history(
    loop: Any,
    ctx: TurnContext,
    system_messages: list[dict[str, str]],
    *,
    num_ctx: int,
    tool_reserve_chars: int,
    ratio: float,
    role: ModelRole,
    text: str,
    wants_fresh_page: bool,
    offer_tools: bool,
    expect_tool_round: bool,
    chat_tools: list[dict[str, Any]],
    turn_tail: list[dict[str, str]],
    staged_files: Any = None,
) -> None:
    """Pay for tool schemas, then append as much conversation history as fits."""
    budget = context_budget(
        num_ctx,
        tool_output_chars=tool_reserve_chars,
        chars_per_token=ratio,
        schema_chars=len(json.dumps(chat_tools)) if chat_tools else 0,
    )
    ctx.wants_fresh_page = wants_fresh_page
    ctx.offer_tools = offer_tools
    ctx.expect_tool_round = expect_tool_round
    ctx.chat_tools = chat_tools
    ctx.messages = await loop._messages_for_turn(
        system_messages,
        budget,
        ratio,
        role,
        user_text=text,
        turn_tail=turn_tail,
    )
    from arelis.attachments import apply_images_to_last_user

    apply_images_to_last_user(ctx.messages, text, staged_files)
    # The wire tells this question apart from the notes added later in the
    # turn, which must not render as new questions (#278).
    for index in range(len(ctx.messages) - 1, -1, -1):
        if ctx.messages[index].get("role") == "user":
            ctx.messages[index] = {**ctx.messages[index], "turn_query": True}
            break


_SHORT_ASK_WORDS = 12
_SLASH_DATE = re.compile(r"(?<![\d/.])\d{1,2}/\d{1,2}/\d{2,4}(?![\d/])")
_PAST_MONTH_DAY = re.compile(
    r"(?i)^\s*what\s+was\s+(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])\s*\??\s*$"
)
_WHAT_IS_MONTH_DAY = re.compile(
    r"(?i)^\s*what\s+is\s+(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])\s*\??\s*$"
)
_HAPPENED_ON_MONTH_DAY = re.compile(
    r"(?i)\b(?:what\s+happened|happened\s+on)\b.{0,40}"
    r"(?<![\d/.])(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])(?:/\d{2,4})?(?![\d/])"
)




def _looks_like_date_or_event_ask(text: str) -> bool:
    """True when the person is asking about a slash date or event, not math."""
    raw = text or ""
    if re.search(r"(?i)as\s+a\s+(?:decimal|fraction|percent)", raw):
        return False
    if _WHAT_IS_MONTH_DAY.match(raw) or _PAST_MONTH_DAY.match(raw):
        return True
    if re.search(
        r"(?i)(?:what\s+happened|happened\s+on).{0,48}"
        r"(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])(?!\d)",
        raw,
    ):
        return True
    return False


def calculator_blocked_for_date_ask(user_text: str, expression: str) -> str | None:
    """Refuse calculator when a date/event ask is being evaluated as that M/D."""
    return _date_ask_ratio_block(user_text, expression or "")


def python_blocked_for_date_ask(user_text: str, code: str) -> str | None:
    """Refuse a python one-liner that only divides the ask's month/day."""
    if not _looks_like_date_or_event_ask(user_text):
        return None
    hit = re.search(
        r"(?<![\d/.])(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])(?![\d/])",
        user_text or "",
    )
    if not hit:
        return None
    month, day = int(hit.group(1)), int(hit.group(2))
    blob = code or ""
    # Allow real date math (datetime / month names / day-of-year loops).
    if re.search(r"(?i)datetime|timedelta|date\(|September|October|memorial|attack", blob):
        return None
    if re.search(rf"(?<!\d){month}\s*/\s*{day}(?!\d)", blob) and len(blob) < 80:
        return (
            "That looks like a date or event in the ask, not a division. "
            "Answer in words about the date or event."
        )
    return None


def _date_ask_ratio_block(user_text: str, expression: str) -> str | None:
    if not _looks_like_date_or_event_ask(user_text):
        return None
    hit = re.search(
        r"(?<![\d/.])(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])(?![\d/])",
        user_text or "",
    )
    if not hit:
        return None
    month, day = int(hit.group(1)), int(hit.group(2))
    from arelis.tools.calculator import normalize_expression

    try:
        source = normalize_expression(expression or "")
    except Exception:
        # Not a date-ratio we can match; leave the tool call alone.
        return None
    src = (source or "").strip()
    if re.fullmatch(rf"0?{month}/0?{day}", src):
        return (
            "That looks like a date or event in the ask, not a division. "
            "Answer in words about the date or event."
        )
    return None


_ASK_BODY_BLANK = re.compile(r"\n[ \t]*\n")
_HTTP_URL = re.compile(r"https?://\S+", re.I)
_PASTE_IS_NOT_A_FETCH = frozenset({"web", "attachments"})
_SHORT_BLOCK_CHARS = 280
_LARGE_BODY_CHARS = 400


@dataclass(frozen=True)
class _AskSplit:
    instruction: str
    body: str
    trailing: str


def split_user_ask(text: str) -> tuple[str, str]:
    """Split a short instruction from a pasted body, when one is present.

    Structural: a large middle with a short first block and/or a short last
    block. The instruction is those short ends. The body is only the middle.
    When there is no dump, the whole text is the instruction. The paste is
    not truncated for the model; callers classify on the instruction only.
    """
    parts = _split_user_ask(text)
    return parts.instruction, parts.body


def _split_user_ask(text: str) -> _AskSplit:
    raw = (text or "").strip()
    if not raw:
        return _AskSplit("", "", "")
    blocks = [part.strip() for part in _ASK_BODY_BLANK.split(raw) if part.strip()]
    if len(blocks) >= 2:
        found = _ends_around_body(blocks)
        if found is not None:
            return found
        return _AskSplit(raw, "", "")
    found = _line_ends_around_body(raw)
    if found is not None:
        return found
    return _AskSplit(raw, "", "")


def _is_short_block(text: str) -> bool:
    if not text:
        return False
    if text.count("\n") > 2 or len(text) > _SHORT_BLOCK_CHARS:
        return False
    return True


def _is_large_body(body: str, instruction: str) -> bool:
    if not body:
        return False
    if len(body) < _LARGE_BODY_CHARS:
        return False
    if len(body) < 4 * max(len(instruction), 1):
        return False
    return True


def _join_instruction(*parts: str) -> str:
    return "\n\n".join(part for part in parts if part)


def _ends_around_body(blocks: list[str]) -> _AskSplit | None:
    first = blocks[0]
    last = blocks[-1]
    first_short = _is_short_block(first)
    last_short = _is_short_block(last)
    if len(blocks) == 2:
        if first_short and last_short:
            return None
        if first_short and _is_large_body(last, first):
            return _AskSplit(first, last, "")
        if last_short and _is_large_body(first, last):
            return _AskSplit(last, first, last)
        return None
    middle = "\n\n".join(blocks[1:-1])
    if first_short and last_short:
        instruction = _join_instruction(first, last)
        if _is_large_body(middle, instruction):
            return _AskSplit(instruction, middle, last)
    if first_short and not last_short:
        rest = "\n\n".join(blocks[1:])
        if _is_large_body(rest, first):
            return _AskSplit(first, rest, "")
    if last_short and not first_short:
        rest = "\n\n".join(blocks[:-1])
        if _is_large_body(rest, last):
            return _AskSplit(last, rest, last)
    return None


def _line_ends_around_body(raw: str) -> _AskSplit | None:
    line, _sep, rest = raw.partition("\n")
    head = line.strip()
    tail = rest.strip()
    if not tail or not _is_short_block(head):
        return None
    last_line, _last_sep, prefix_rev = tail[::-1].partition("\n")
    last = last_line[::-1].strip()
    mid = prefix_rev[::-1].strip()
    if mid and _is_short_block(last):
        instruction = _join_instruction(head, last)
        if _is_large_body(mid, instruction):
            return _AskSplit(instruction, mid, last)
    if _is_large_body(tail, head):
        return _AskSplit(head, tail, "")
    return None


def _trailing_selects_web(
    trailing: str,
    available_tools: set[str] | None,
) -> bool:
    """True when the last short block alone is a web ask, not a byline."""
    if not trailing:
        return False
    ids, fallback_only = select_skill_ids_detailed(
        trailing, available_tools=available_tools
    )
    return bool(not fallback_only and "web" in ids)


def _body_already_here(
    instruction: str,
    provided_body: str,
    *,
    trailing: str,
    available_tools: set[str] | None,
) -> bool:
    """True when a pasted body is the page and this ask is not a fetch.

    A URL in the instruction is a fetch. A trailing block that alone
    selects web is a live fetch after the paste. Other short last
    blocks (bylines, sign-offs, CAS) keep the page as already here.
    """
    if not provided_body:
        return False
    if _HTTP_URL.search(instruction or ""):
        return False
    if _trailing_selects_web(trailing, available_tools):
        return False
    return True


async def prepare_turn(
    loop: Any,
    text: str,
    role: ModelRole,
    *,
    source: str = "chat",
    route_reason: str = "default",
    stopped_ask: str = "",
    typed_text: str | None = None,
    staged_files: Any = None,
) -> TurnContext | None:
    """Build the prompt and TurnContext. None if the turn already finished."""
    start = await _begin_turn(
        loop,
        text,
        role,
        source=source,
        route_reason=route_reason,
    )
    model = start.model
    speak = start.speak
    agent_cfg = start.agent_cfg
    ratio = start.ratio
    research_mode = start.research_mode
    available_all = start.available_all
    active_room = start.active_room
    available = start.available
    visible = start.visible
    # Persona and the tool policy stay at the front so they can be cached.
    # Everything that changes per turn is collected on its own list and placed
    # after history, immediately before this ask.
    system_messages = static_system_prefix(loop.persona)
    turn_tail: list[dict[str, str]] = []
    append_stopped_turn_note(turn_tail, stopped_ask)
    drafts = _reconstruct_turn_drafts(loop, text)
    sms_draft = drafts.sms
    email_draft = drafts.email
    agenda_draft = drafts.agenda
    skip_sms_draft = drafts.skip_sms
    preflight_kinds = append_preflight_guidance(
        turn_tail,
        loop,
        text,
        agent_cfg,
        see_no_sms_redirect=_SEE_NO_SMS_REDIRECT,
    )
    # Room extras stay on filter_tool_names (keep analyze/cas in reach).
    # Mixing them into skill_ids made select_plan treat the lean as
    # this-turn intent, so an analysis room demanded a CSV on
    # "how do toroids relate to physics?".
    # Classifiers read the instruction only. A pasted article that says
    # "article" or "integral of" is not this-turn intent. A short last
    # block after the dump is part of that instruction.
    parts = _split_user_ask(text)
    instruction, provided_body = parts.instruction, parts.body
    classify_text = instruction or text
    body_already_here = _body_already_here(
        instruction,
        provided_body,
        trailing=parts.trailing,
        available_tools=available,
    )
    skill_ids, fallback_only = select_skill_ids_detailed(
        classify_text, available_tools=available
    )
    # The unmatched "what is" web floor is a tool-menu hint, not a scrape
    # plan. Clock asks already special-case this; definitional physics
    # questions used to get the same cage once room extras stopped
    # suppressing the fallback.
    plan_ids = () if fallback_only else skill_ids
    if body_already_here:
        # The page is already in the message. A web card from "article" in
        # the instruction, or attachments from "summarize this", is a menu
        # hint, not a scrape or file-read plan. Plot and CAS stay on plan_ids.
        plan_ids = [sid for sid in plan_ids if sid not in _PASTE_IS_NOT_A_FETCH]
    # Short thanks/bye must not revive weather (or a stale web_search habit).
    if looks_like_closing_chitchat(text):
        available = set(available)
        available.discard("weather")
        available.discard("web_search")
        visible = available
        loop._expected_tools.discard("weather")
        loop._expected_tools.discard("web_search")
    turn_goal = append_turn_goal(
        turn_tail,
        loop,
        text,
        role,
        preflight_kinds=preflight_kinds,
        sms_draft=sms_draft,
        email_draft=email_draft,
        research_mode=research_mode,
    )
    # The vision tool used to be hidden behind a keyword list, because
    # looking cost an unload, a cold VL load, and a re-warm. A multimodal
    # chat model sees at the window it is already loaded with (see
    # ModelRouter.run_vision), so the schema is the only cost left and the
    # window has room for it. The list was also a trap: any phrasing outside
    # it — "what is this?" beside a fresh attachment — left the model
    # schema-blind and it invented a caption.
    available, visible = apply_expected(loop, available, text=text, available_all=available_all)
    active_plan = None
    disconnected = disconnected_integration_reply(
        expected=loop._expected_tools,
        available=available_all,
        want_sms=bool(
            (sms_draft is not None and sms_draft.complete and not skip_sms_draft)
            or sms_intent_this_turn(text)
        ),
        want_mail=bool(
            (email_draft is not None and email_draft.complete) or looks_like_compose_email(text)
        ),
        want_calendar=bool(
            (agenda_draft is not None and agenda_draft.complete)
            or looks_like_calendar_read(text)
            or looks_like_calendar_create(text)
            or looks_like_calendar_delete(text)
        ),
    )
    if disconnected:
        await loop._finish(disconnected, [])
        return None
    loop._active_plan = active_plan
    append_plan_and_lessons(
        turn_tail,
        loop,
        text,
        agent_cfg,
        preflight_kinds=preflight_kinds,
        skill_ids=skill_ids,
        active_plan=active_plan,
    )
    append_operating_context(
        turn_tail,
        loop,
        role=role,
        model=model,
        skill_ids=skill_ids,
        active_room=active_room,
    )
    append_delivery_context(turn_tail, loop, speak=speak)
    num_ctx, tool_reserve_chars = await _context_limits(
        loop,
        role,
        speak=speak,
        skill_ids=skill_ids,
    )
    exact_cfg = bool(agent_cfg.get("exactness", True))
    exact_need = detect_exactness_need(
        classify_text, data_cell="data_cell" in set(visible)
    )
    from arelis.core.turn_scratch import staged_file_rows

    ctx = TurnContext(
        text=text,
        typed_text=typed_text,
        staged_files=staged_file_rows(staged_files),
        role=role,
        speak=speak,
        research_mode=research_mode,
        agent_cfg=agent_cfg,
        available_all=available_all,
        available=set(available),
        visible=set(visible),
        tool_names=set(visible),
        skill_ids=tuple(skill_ids),
        preflight_kinds=list(preflight_kinds),
        active_plan=active_plan,
        sms_draft=sms_draft,
        email_draft=email_draft,
        agenda_draft=agenda_draft,
        skip_sms_draft=skip_sms_draft,
        active_room=active_room,
        numeric_gate=exact_cfg and bool(agent_cfg.get("numeric_gate", True)),
        evidence_gate=exact_cfg and bool(agent_cfg.get("evidence_gate", True)),
        research_dual=exact_cfg and bool(agent_cfg.get("research_dual_hit", True)),
        research_min_sources=max(1, int(agent_cfg.get("research_min_sources", 2))),
        exact_need=exact_need,
        goal=turn_goal,
    )
    exact_need = apply_research_web_need(
        exact_need, research_mode=research_mode, text=classify_text
    )
    ctx.exact_need = exact_need
    # News / current-events turns should not end on search snippets alone.
    wants_fresh_page = (
        exact_need.needs_web_evidence
        or research_mode
        or (not fallback_only and "web" in skill_ids)
        or ("research" in skill_ids)
        or wants_fresh_page_ask(classify_text)
    )
    # "weather today" must not arm scrape-after-search.
    if exact_need.needs_weather or (
        "weather" in loop._expected_tools
        and "web_search" not in loop._expected_tools
        and "scrape" not in loop._expected_tools
    ):
        wants_fresh_page = False
    # A YouTube / Chrome drive is not a scrape-the-web turn.
    if "browser" in loop._expected_tools:
        wants_fresh_page = False
    if body_already_here:
        # They already pasted the page. A URL-less instruction is not a fetch.
        wants_fresh_page = False
    # Chat fast path still skips the tool round and hold-paint. Schemas stay
    # on anyway: dropping them changes the front of the prompt.
    offer_tools = should_offer_tools(
        chat_fast_path=bool(agent_cfg.get("chat_fast_path", True)),
        skill_ids=skill_ids,
        preflight_kinds=preflight_kinds,
        research_mode=research_mode,
        expected_tools=loop._expected_tools,
        exact_need=exact_need,
        wants_fresh_page=wants_fresh_page,
        active_plan=active_plan,
    )
    # Schemas can stay on (prefix cache) without treating chitchat as a
    # tool round. The unmatched web floor is a menu hint, not a scrape.
    expect_tool_round = turn_expects_tool_round(
        skill_ids=plan_ids,
        preflight_kinds=preflight_kinds,
        research_mode=research_mode,
        expected_tools=loop._expected_tools,
        exact_need=exact_need,
        wants_fresh_page=wants_fresh_page,
        active_plan=active_plan,
    )
    # A short ask that expects no tool round answers from what the model
    # knows. Thinking first was most of a 9 to 21 s first token (#368).
    # Only the first request: a tool round still thinks as before.
    if not expect_tool_round and len(text.split()) <= _SHORT_ASK_WORDS:
        loop._think_off_next = True
    chat_tools = session_tool_schemas(loop.tools, agent_cfg)
    loop.memory.remember_turn_block(turn_tail)
    if loop._timer is not None and not offer_tools:
        loop._timer.mark("chat_fast_path", tools=0)
    await _attach_tool_schemas_and_history(
        loop,
        ctx,
        system_messages,
        num_ctx=num_ctx,
        tool_reserve_chars=tool_reserve_chars,
        ratio=ratio,
        role=role,
        text=text,
        wants_fresh_page=wants_fresh_page,
        offer_tools=offer_tools,
        expect_tool_round=expect_tool_round,
        chat_tools=chat_tools,
        turn_tail=turn_tail,
        staged_files=staged_files,
    )
    return ctx
