from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import uuid4

from arelis.attachments import (
    parse_attachments_from_turn,
    split_attachments_turn,
    wants_image_edit,
)
from arelis.config import shipped_num_ctx
from arelis.contacts import (
    contacts_prompt_line,
    format_contact_spoken,
    web_search_targets_known_contact,
)
from arelis.core.agenda_complete import (
    agenda_force_call_notice,
    agenda_force_close_notice,
    agenda_force_delete_notice,
    agenda_force_open_notice,
    agenda_force_read_notice,
    agenda_read_action,
    complete_agenda_draft,
    draft_agenda_create_args,
    draft_agenda_delete_args,
    fill_agenda_args,
    lock_agenda_delete_args,
    looks_like_calendar_close,
    looks_like_calendar_create,
    looks_like_calendar_delete,
    looks_like_calendar_open,
    looks_like_calendar_read,
)
from arelis.core.bus import EventBus
from arelis.core.claims import (
    answer_looks_like_ack_only,
    answer_looks_like_refusal,
    catalog_force_notice,
    contact_who_from_text,
    detect_exactness_need,
    draft_catalog_args,
    evidence_force_notice,
    file_answer_force_notice,
    last_store_ids_from_context,
    local_store_inject_args,
    lock_memory_forget_args,
    send_claim_missing_kinds,
    unsupported_exactness_reply,
    unsupported_send_claim_reply,
    weather_force_notice,
)
from arelis.core.context import (
    TokenRatios,
    allocate_history,
    context_budget,
    message_tokens,
    prompt_char_count,
    split_recent_history,
)
from arelis.core.document_refs import (
    fill_doc_extract_args,
    fill_document_args,
)
from arelis.core.email_complete import (
    complete_email_draft,
    draft_send_email_args,
    email_force_call_notice,
    fill_send_email_args,
    looks_like_bare_confirm,
    looks_like_compose_email,
    looks_like_mailbox_mutate,
    looks_like_schedule_manage,
    looks_like_scheduled_send,
    rewrite_schedule_calls,
)
from arelis.core.episodes import episodes_prompt_line
from arelis.core.events import Event, EventType
from arelis.core.evidence import (
    EvidenceLedger,
    classify_fetch_failure,
    dual_hit_notice,
    quote_first_notice,
)
from arelis.core.facts import facts_prompt_line
from arelis.core.fail_tags import tool_fail_replan_notice
from arelis.core.gates import FORCE_GATE_KINDS, apply_force_gates
from arelis.core.image_refs import (
    CAMERA_FRESH_S,
    fill_vision_args,
    image_force_call_notice,
    latest_camera_image_file,
)
from arelis.core.json_tools import (
    ThinkingStripper,
    extract_native_tool_calls,
    parse_fallback_payload,
    strip_thinking_text,
)
from arelis.core.lessons import format_lessons, select_lessons
from arelis.core.look import (
    LOOK_TOOL_SUBSET,
    LOOKING_STATUS,
    LookTurn,
    build_see_record,
    classify_look,
    format_see_record,
    frame_sha256,
    inspect_ocr_text,
    look_answer_refuse,
    look_call_blocked,
    look_receipt,
    next_look_call,
    ocr_deferral,
    vision_question,
)
from arelis.core.memory import SessionMemory, tool_trace_entry, tool_trace_note
from arelis.core.other_work import looks_like_other_work
from arelis.core.plan_nudge import (
    plan_progress_notice,
    select_plan,
)
from arelis.core.preflight import (
    detect_intents,
    draft_browser_args,
    draft_rooms_create_args,
    draft_signin_click_args,
    looks_like_browser_click_signin,
    looks_like_room_create,
    preflight_system_message,
    rewrite_browser_calls,
    user_asked_for_browser,
)
from arelis.core.read_fanout import should_fanout_reads
from arelis.core.receipts import (
    action_receipt,
    append_action_ledger,
    format_action_receipt,
)
from arelis.core.skills import (
    full_tool_policy,
    select_skill_ids,
)
from arelis.core.sms_complete import (
    complete_sms_draft,
    draft_send_sms_args,
    fill_send_sms_args,
    looks_like_browser_or_url,
    looks_like_closing_chitchat,
    looks_like_contact_email_ask,
    looks_like_contact_phone_ask,
    looks_like_contacts_followup,
    looks_like_contacts_utterance,
    looks_like_goals_utterance,
    looks_like_image_gen,
    looks_like_memory_utterance,
    looks_like_stale_sms_skip,
    looks_like_tasks_utterance,
    sms_force_call_notice,
    sms_intent_this_turn,
)
from arelis.core.tile_complete import match_tile_intent, tile_tool_args
from arelis.core.tool_args import cross_tool_arg_error, schema_keys
from arelis.core.tool_results import PreparedToolOutput, prepare_tool_output
from arelis.core.tool_subset import filter_tool_names, is_deep_dive_ask, is_research_mode
from arelis.core.turn_context import TurnContext
from arelis.core.turn_telemetry import TurnTimer, turn_telemetry_enabled
from arelis.core.untrusted import frame_external_tool_output
from arelis.core.world_state import world_state_prompt_line
from arelis.llm.errors import classify_ollama_failure, is_vram_failure
from arelis.llm.router import ModelRole, ModelRouter
from arelis.memory.store import MemoryStore
from arelis.profile import standing_profile_prompt_line
from arelis.tools.base import ToolRegistry, confirm_args_blocked
from arelis.tools.inbox import draft_inbox_mutate_args, fill_inbox_args
from arelis.tools.safety import redact_secrets, truncate_tool_output
from arelis.tools.weather import (
    draft_weather_args,
    fill_weather_args,
    weather_place_key,
    weather_places_missing,
    weather_wants_beyond_today,
)

# Conversation turns rarely scrape huge pages; reserving a full tool-output
# slab leaves almost no room for chat history, so after a few spoken turns the
# loop runs a full "summarizing earlier turns" model pass before every answer.
# That feels like the model going offline. Keep a smaller reserve when speaking.
_SPEAK_TOOL_OUTPUT_CHARS = 4000
# Prior user+assistant plus the current user line. Conversation mode used to
# keep only history[-1] when the system prefix ate the token budget, so turn
# N+1 never saw turn N.
_HISTORY_MIN_RECENT = 6

# Appended only on tool-bearing model rounds (dynamic trailer — not in the
# static cached prefix). Keeps decode short: call tools, don't narrate first.
_TOOL_ROUND_HINT = (
    "This round: emit any needed tool call immediately. "
    "Do not write prose, preamble, or a final answer before the tool call."
)

log = logging.getLogger(__name__)

ConfirmFn = Callable[[str, str, dict[str, Any], str], Awaitable[str]]
# confirm(id, tool, args, summary) -> "allow" | "allow_turn" | "skip"

# Reasoning text is shown in the thinking dock, not the chat. Token-sized
# Ollama `thinking` chunks are streamed into one wrapping paragraph. Discrete
# status/tool/round lines stay one per event. Preamble snippets still cap.
_MAX_THINKING_SNIPPET = 240

# Visible characters buffered before any of a round is painted into the chat.
# Enough to tell a JSON payload from prose, short enough that nobody sees the
# delay. See _LiveAnswer.
_STREAM_DECIDE_CHARS = 20

# Tools whose results are web sources and therefore have to be citable.
_WEB_TOOLS = {"web_fetch", "scrape", "research_report", "browser"}

# Outbound drafts must keep the full tool surface — never escalate away.
_OUTBOUND_LOCK = re.compile(
    r"(?i)\b(text|sms|send\s+(?:a\s+)?(?:text|sms|email|mail)|e-?mail)\b"
)

# How many times a turn will correct a model that writes tool calls as prose.
# Two is enough for a model having a bad round; past that it is not going to
# comply, and the round limit produces a plain answer instead of looping.
_MAX_TOOL_NUDGES = 2
_FILE_ANSWER_TOOLS = frozenset({"workspace", "analyze", "doc_extract"})
_DAILY_WANDER = frozenset({"weather", "send_sms", "send_email", "agenda"})
_LOCAL_STORE = frozenset({"memory", "tasks", "goals", "contacts", "recall"})
_SEE_TOOLS = frozenset(
    {"vision", "ocr", "camera", "clipboard", "image", "image_edit", "git_info"}
)
_WEATHER_WANDER = frozenset({"web_search", "scrape", "web_fetch"})
_SMS_WANDER = frozenset(
    {
        "web_search",
        "user_location",
        "browser",
        "scrape",
        "web_fetch",
        "image",
        "vision",
        "camera",
    }
)
_SEE_NO_SMS_REDIRECT = frozenset(
    {"vision", "ocr", "image", "image_edit", "camera"}
)
_BROWSER_WANDER = frozenset(
    {"web_search", "scrape", "web_fetch", "research_report"}
)
_HIDE_WANDER_FOR = _DAILY_WANDER | _LOCAL_STORE | _SEE_TOOLS | {"browser"}


def should_redirect_wander_to_sms(
    name: str,
    expected: set[str],
    *,
    tools_used: set[str] | None = None,
    sms_failed: bool = False,
) -> bool:
    """True when a wander tool should be rewritten to send_sms.

    Looking at or editing a picture is never a text. Even a leftover SMS
    expected-set must not steal vision / ocr / image / image_edit / camera.
    """
    used = tools_used or set()
    if name in _SEE_NO_SMS_REDIRECT:
        return False
    if "send_sms" not in expected or "send_sms" in used or sms_failed:
        return False
    return name in _SMS_WANDER


def _hide_daily_wander(visible: set[str], expected: set[str]) -> set[str]:
    """Drop tools that burn rounds on weather / SMS / email / agenda turns."""
    hide: set[str] = set()
    if "weather" in expected:
        hide |= _WEATHER_WANDER
    if expected & {"send_sms", "send_email", "agenda"}:
        hide.update(_SMS_WANDER)
        if "weather" not in expected:
            hide.add("weather")
    # A look/edit turn must still see those tools even if SMS leaked in.
    if expected & _SEE_NO_SMS_REDIRECT:
        hide -= set(_SEE_NO_SMS_REDIRECT)
        hide.add("send_sms")
    if "image_edit" in expected:
        hide.add("image")
    if "browser" in expected:
        hide.update(_BROWSER_WANDER)
    if expected & _LOCAL_STORE and "browser" not in expected:
        hide.update(
            {"browser", "scrape", "web_fetch", "weather", "web_search"}
        )
    # Calendar / memory / look / clipboard turns must not offer a leftover SMS.
    if "send_sms" not in expected and expected & (
        {"agenda", "weather"} | _LOCAL_STORE | _SEE_TOOLS
    ):
        hide.add("send_sms")
    if "send_email" not in expected and expected & (
        {"agenda", "weather"} | _LOCAL_STORE | _SEE_TOOLS
    ):
        hide.add("send_email")
    if not hide:
        return set(visible)
    return set(visible) - hide


def _offer_expected(
    visible: set[str], expected: set[str], available_all: set[str]
) -> set[str]:
    """Skill subset can drop a tool that preflight later marked expected."""
    return set(visible) | (expected & available_all)


def _normalize_ollama_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Make history safe to send back to Ollama after a tool round.

    Injected calls used to store ``arguments`` as a JSON string while native
    calls used a dict. Ollama then 400s with “can't find closing '}'” on the
    next step — including the no-tools JSON fallback — and the turn dies.
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        item = dict(msg)
        content = item.get("content")
        if content is not None and not isinstance(content, str):
            item["content"] = json.dumps(content, default=str)
        calls = item.get("tool_calls")
        if isinstance(calls, list):
            fixed: list[dict[str, Any]] = []
            for call in calls:
                if not isinstance(call, dict):
                    continue
                slot = dict(call)
                fn = dict(slot.get("function") or {})
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        fn["arguments"] = json.loads(args) if args.strip() else {}
                    except json.JSONDecodeError:
                        fn["arguments"] = {}
                elif not isinstance(args, dict):
                    fn["arguments"] = {}
                slot["function"] = fn
                fixed.append(slot)
            item["tool_calls"] = fixed
        out.append(item)
    return out


def _is_ollama_object_400(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "http 400" in text or "closing '}'" in text


def _tool_followup_fallback(out: str, tool: str = "") -> str:
    """Use the last successful tool output when the model cannot phrase it."""
    from arelis.core.failure_copy import chat_followup_from_tool

    return chat_followup_from_tool(tool, out)

# One extra round when the model tries to answer news from search snippets alone.
_SCRAPE_AFTER_SEARCH_NOTICE = (
    "You used web_search but have not scraped or fetched a page yet. "
    "Snippets are not enough for a current-events answer. Call scrape now "
    "with the URL: value from the best hit (must start with http), then answer."
)

_JS_SHELL_BROWSER_NOTICE = (
    "That page is a JavaScript shell — scrape cannot read it. Call "
    "browser(action=open, url={url}) so they can Allow her window. "
    "Read the tab after it loads. Do not invent what the page says."
)

# Room left for the summary pin when deciding what still fits as raw history.
# The real summary is capped separately; this only keeps allocate_history from
# filling the window so tightly that the pin itself would force another drop.
_SUMMARY_RESERVE_TOKENS = 256
_MAX_SUMMARY_CHARS = 800

_SUMMARY_SYSTEM = """
You compress older turns of a conversation so a later model call can still use them.
Write only the filled-in form. No preamble.

FACTS are rare. Only list durable identity or preference truths that should
still matter months from now (job, school, name preferences, standing project
ownership, lasting constraints). Do NOT list: questions asked, tasks in
progress, what was discussed, tool calls, file contents, one-off requests,
or anything that is only about this chat. When unsure, write NONE. Most
excerpts should have FACTS: NONE.
""".strip()

_SUMMARY_USER = """Previous summary (may be empty):
{previous}

New excerpt to fold in:
{excerpt}

Reply in exactly this form:
SUMMARY: <one short paragraph, at most {max_chars} characters>
FACTS:
- <durable fact, or NONE if none — usual answer is NONE>"""

# Hard cap: even a chatty compress pass cannot flood the History review queue.
_MAX_PROPOSED_FACTS = 2

# Every rule, in one block, on every turn. Cards remain how the text is
# authored and reviewed — one section per capability — but selection between
# them is no longer part of building a prompt.
TOOL_POLICY = full_tool_policy()

# The whole policy is the static prefix. It used to be SKILL_CORE alone (333
# tokens) with four matched cards trailing behind it, because at num_ctx 16384
# the full policy plus the tool schemas came to 108% of the window and did not
# fit. At 65536 the same prompt is 27% (persona 905 + policy 6,248 + schemas
# 10,674 = 17,827 tokens; see scripts/measure_prompt_budget.py), which buys back
# two things selection was costing:
#
#   A rule the model needs is always present. Selection is keyword matching, and
#   a miss shipped a turn with no rule for the tool it was about to call — the
#   failure mode the fallback bug showed when a local file path went to
#   web_fetch.
#
#   The prefix is byte-stable much deeper. The focus block sat ahead of the
#   conversation, so changing which cards matched re-prefilled all of history
#   behind it. Now only the short tail varies: preflight, facts, world state,
#   clock.
STATIC_TOOL_POLICY = TOOL_POLICY


def static_system_prefix(persona: str) -> list[dict[str, str]]:
    """Byte-stable system prefix for KV/prefix cache across turns.

    Persona + the whole tool policy. Everything turn-specific (clock, preflight,
    facts, …) must trail this list.
    """
    return [
        {"role": "system", "content": persona},
        {"role": "system", "content": STATIC_TOOL_POLICY},
    ]


def static_prefix_text(persona: str) -> str:
    """Concatenated static prefix for equality checks in tests."""
    return "\n".join(m["content"] for m in static_system_prefix(persona))


def _tool_intent_label(tool_calls: list[dict[str, Any]]) -> str:
    """Short Thinking/STATUS line once a native tool call is parsed."""
    if not tool_calls:
        return ""
    first = tool_calls[0] or {}
    fn = first.get("function") if isinstance(first, dict) else None
    if isinstance(fn, dict):
        name = str(fn.get("name") or "").strip()
        raw_args = fn.get("arguments")
    else:
        name = str(first.get("name") or "").strip()
        raw_args = first.get("arguments") or first.get("args")
    args: dict[str, Any] = {}
    if isinstance(raw_args, dict):
        args = raw_args
    elif isinstance(raw_args, str) and raw_args.strip():
        try:
            parsed = json.loads(raw_args)
            if isinstance(parsed, dict):
                args = parsed
        except (TypeError, ValueError, json.JSONDecodeError):
            args = {}
    if name == "browser":
        action = str(args.get("action") or "open").strip().lower() or "open"
        target = str(args.get("url") or args.get("target") or "").strip()
        if action == "open":
            return f"Opening {target or 'browser'}…"
        if target:
            return f"Browser {action}: {target}…"
        return f"Browser {action}…"
    if name:
        return f"Calling {name}…"
    return ""


def _native_tool_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Ollama-style tool_call dict for injected draft executions.

    ``arguments`` must be an object. A JSON string here is what triggers
    Ollama HTTP 400 “Value looks like object, but can't find closing '}'”.
    """
    return {
        "type": "function",
        "id": f"inject-{name}-{uuid4().hex[:8]}",
        "function": {
            "name": name,
            "arguments": dict(args),
        },
    }


def now_line() -> str:
    """The current local date and time, for the system prompt.

    The clock is the one fact about the present that needs no network and no
    tool call, and without it she answers "what day is it" with a web search or
    with the year she was trained in. It also lets her reason about "next
    Friday" well enough to hand the phrase to the schedule tool, which is what
    actually resolves it.
    """
    now = datetime.now().astimezone()
    stamp = now.strftime("%A, %d %B %Y, %H:%M").replace(" 0", " ")
    zone = now.strftime("%Z") or "local time"
    return (
        f"Right now it is {stamp} ({zone}). Use this for anything about today, "
        "tomorrow, or the current year. It is the clock on this machine, so it "
        "is reliable; do not search the web to find out the date."
    )


class _StoppedError(Exception):
    """Raised internally when the cooperative cancel flag is seen mid-stream."""


class _LiveAnswer:
    """Decides which part of a model stream is safe to paint into the chat now.

    Two kinds of text must not reach the bubble. Reasoning markup, which belongs
    in the thinking dock. And a JSON fallback payload, which is an instruction
    rather than an answer: streaming {"tool": "workspa... into the chat and
    deleting it a moment later is worse than showing nothing at all.

    Telling a payload from prose only needs the opening characters, so output is
    held until _STREAM_DECIDE_CHARS of them have arrived. That is under one
    word, so the pause is not perceptible.

    Prose that turns out to be a preamble to a tool call is not handled here.
    It cannot be: at the time the words arrive there is nothing to distinguish
    them from an answer. The caller retracts them once the round resolves.
    """

    def __init__(self) -> None:
        self._stripper = ThinkingStripper()
        self._hold = ""
        self._decided = False
        self._suppressed = False
        self.published = ""

    def feed(self, chunk: str) -> tuple[str, bool]:
        """Return (text to publish now, whether to retract what came before)."""
        visible = self._stripper.feed(chunk)
        retract = self._stripper.take_reset()
        if retract:
            self._reset()
        return self._absorb(visible), retract

    def flush(self) -> str:
        """Release held text once the stream is over."""
        return self._absorb(self._stripper.flush(), final=True)

    def _reset(self) -> None:
        self._hold = ""
        self._decided = False
        self._suppressed = False
        self.published = ""

    def _absorb(self, visible: str, *, final: bool = False) -> str:
        if self._suppressed:
            return ""
        if not self._decided:
            self._hold += visible
            candidate = self._hold.lstrip()
            if not final and len(candidate) < _STREAM_DECIDE_CHARS:
                return ""
            self._decided = True
            self._hold = ""
            if candidate.startswith(("{", "```")):
                self._suppressed = True
                return ""
            visible = candidate
        if not visible:
            return ""
        self.published += visible
        return visible


class AgentLoop:
    """One user turn: alternate model steps and tool calls until an answer.

    Invariants the rest of the app relies on:
    - Exactly one terminal event per turn (ASSISTANT_DONE or ERROR). The desktop
      UI clears its busy state on those, so an early return without one leaves
      the composer disabled. terminal_sent records that it happened, so the
      orchestrator does not add a second one on top.
    - Answer text is streamed as it arrives, but only text that is still a
      candidate answer. A round that ends in a tool call publishes
      ASSISTANT_RETRACT, so a preamble never sits in the chat pretending to be
      the reply.
    - Confirmation is requested before a write or image call, never after.
    """

    def __init__(
        self,
        bus: EventBus,
        router: ModelRouter,
        tools: ToolRegistry,
        memory: SessionMemory,
        persona: str,
        config: dict[str, Any],
        *,
        request_confirm: ConfirmFn,
        is_cancelled: Callable[[], bool],
        is_paused: Callable[[], bool] | None = None,
    ) -> None:
        self.bus = bus
        self.router = router
        self.tools = tools
        self.memory = memory
        self.persona = persona
        self.config = config
        self.request_confirm = request_confirm
        self.is_cancelled = is_cancelled
        self.is_paused = is_paused or (lambda: False)
        agent = config.get("agent") or {}
        self._default_max_rounds = int(agent.get("max_rounds", 8))
        self.max_rounds = self._default_max_rounds
        self.tool_output_chars = int(agent.get("tool_output_chars", 14000))
        self.confirm_writes = bool(agent.get("confirm_writes", True))
        self.confirm_image = bool(agent.get("confirm_image", True))
        self.confirm_send = bool(agent.get("confirm_send", True))
        self.confirm_browser = bool(agent.get("confirm_browser", True))
        self.confirm_vision = bool(agent.get("confirm_vision", True))
        self.json_fallback = bool(agent.get("json_fallback", True))
        self.terminal_sent = False
        # Tools that have actually run this turn. The orchestrator reads this
        # while building a confirm card, to warn when a send is being approved
        # in the same turn that read the inbox.
        self.tools_used: set[str] = set()
        # What is currently painted in the chat bubble, so a hard cancel can
        # keep it instead of replacing a half-written answer with "Stopped."
        self._painted = ""
        # One line per tool call, carried into memory so the next turn knows
        # which file was written or which page was read.
        self._trace: list[str] = []
        # Learned chars-per-token per model. Starts at 4.0 and corrects from
        # prompt_eval_count so fit_messages does not stay a permanent guess.
        self._token_ratios = TokenRatios()
        self._timer: TurnTimer | None = None
        self._look: LookTurn | None = None

    async def run(
        self,
        text: str,
        role: ModelRole,
        *,
        source: str = "chat",
        route_reason: str = "default",
    ) -> None:
        try:
            await self._run(
                text, role, source=source, route_reason=route_reason
            )
        except _StoppedError:
            if self._timer is not None:
                blurb = self._timer.finish("stopped")
                await self.bus.publish(Event(EventType.THINKING, {"text": blurb}))
            await self._cancel_notice()
        except asyncio.CancelledError:
            # Hard cancel from the stop button. Close the turn out properly on
            # the way past so the UI is not left with an orphaned draft, then
            # let the cancellation continue up to the orchestrator.
            if self._timer is not None:
                blurb = self._timer.finish("cancelled")
                await self.bus.publish(Event(EventType.THINKING, {"text": blurb}))
            await self._cancel_notice()
            raise

    async def _run(
        self,
        text: str,
        role: ModelRole,
        *,
        source: str = "chat",
        route_reason: str = "default",
    ) -> None:
        model = self.router.model_for(role)
        speak = bool(self.config.get("_speak_replies"))
        sink = self.memory.sink
        session_id = str(getattr(sink, "session_id", None) or "")
        self._timer = TurnTimer(
            source=source,
            role=role,
            speak=speak,
            user_chars=len(text),
            enabled=turn_telemetry_enabled(self.config),
            session_id=session_id,
            route_reason=route_reason,
            user_text=text,
        )
        # Per-turn state — must not leak across conversation turns (soak found
        # tools_used accumulating and poisoning vision/image duplicate gates).
        self.tools_used = set()
        self._trace = []
        self._painted = ""
        # Mutable so mid-turn escalate (W2) can retarget the hot model.
        self._turn_role: ModelRole = role
        self._escalated = False
        self._expected_tools: set[str] = set()
        self._fail_replan_used = False
        self._active_plan = None
        self._receipts: list[dict[str, Any]] = []
        dock_live = callable(self.config.get("_camera_capture"))
        fresh = latest_camera_image_file(max_age_s=CAMERA_FRESH_S)
        look_intent = classify_look(
            text, dock_live=dock_live, fresh_path=fresh
        )
        self._look: LookTurn | None = None
        if look_intent is not None:
            self._look = LookTurn(
                intent=look_intent,
                path=str(look_intent.path or ""),
            )
            if self._look.path:
                self._look.sha = frame_sha256(self._look.path)
        active = getattr(self.router, "active_model", None)
        if active and active != model:
            await self.bus.publish(
                Event(
                    EventType.MODEL_SWITCH,
                    {"from": active, "to": model, "role": role},
                )
            )
        await self.bus.publish(
            Event(EventType.STATUS, {"message": f"Role `{role}` -> model `{model}`"})
        )
        if (role or "").strip().lower() == "research":
            from arelis.llm.ollama import same_ollama_model

            needs_swap = True
            try:
                fast_tag = str(self.router.model_for("fast") or "")
                needs_swap = not same_ollama_model(fast_tag, model)
            except Exception:
                needs_swap = True
            if active and same_ollama_model(str(active), model):
                needs_swap = False
            if needs_swap:
                from arelis.llm.vram import free_gpu_neighbors

                await free_gpu_neighbors(self.config, self.bus)
                await self.bus.publish(
                    Event(
                        EventType.STATUS,
                        {
                            "message": (
                                f"Loading `{model}` — previous chat model was "
                                "unloaded so it can fit."
                            )
                        },
                    )
                )
        await self.bus.publish(
            Event(
                EventType.THINKING,
                {"text": f"round 0/{self.max_rounds}  composing with {model}"},
            )
        )

        ratio = self._token_ratios.get(model)
        self.memory.chars_per_token = ratio
        self.memory.add("user", text)
        agent_cfg = self.config.get("agent") or {}
        research_mode = is_research_mode(role, text)
        if research_mode:
            self.max_rounds = max(
                self._default_max_rounds,
                int(agent_cfg.get("research_max_rounds", 12)),
            )
        else:
            self.max_rounds = self._default_max_rounds
        available_all = set(self.tools.names())
        # A room that named its tools is capped here rather than downstream,
        # because `visible` is recomputed several times below — on escalation,
        # on expected-tool rescue — and each of those reads available_all. Cap
        # the source and every later recompute inherits it. Rooms leave `tools`
        # empty by default: leaning is the feature, caging is opt-in.
        active_room = getattr(self.config.get("_rooms"), "active", None)
        if active_room is not None and active_room.tools:
            capped = available_all & set(active_room.tools)
            if capped:
                available_all = capped
        room_skills = tuple(active_room.spec.skills) if active_room is not None else ()
        visible = filter_tool_names(
            available_all,
            role=role,
            text=text,
            enabled=bool(agent_cfg.get("research_tool_subset", True)),
            skill_subset=bool(agent_cfg.get("skill_tool_subset", True)),
            history=self.memory.messages,
            extra_skill_ids=room_skills,
        )
        available = visible
        if self._look is not None:
            look_tools = {n for n in available_all if n in LOOK_TOOL_SUBSET}
            if look_tools:
                available = look_tools
                visible = look_tools
        if self._timer is not None and len(visible) < len(available_all):
            self._timer.mark(
                "tool_subset",
                visible=len(visible),
                available=len(available_all),
            )
        # Static prefix first (persona + the whole tool policy) so the front of
        # the prompt is byte-stable across turns. Turn-specific lines trail it,
        # never precede it.
        system_messages = static_system_prefix(self.persona)
        # SMS / email / agenda drafts from this turn + recent history.
        # Image-gen / goals / file-write / calendar-create must not revive a
        # stale SMS draft for force unless this turn itself starts with an SMS
        # verb ("text Brian: …").
        other_work = looks_like_other_work(text, self.memory.messages)
        skip_sms_draft = other_work and not re.match(
            r"(?i)^\s*(?:text|sms|txt|send\s+(?:a\s+)?(?:text|sms|message))\b",
            text or "",
        )
        sms_draft = (
            None
            if skip_sms_draft
            else complete_sms_draft(text, history=self.memory.messages)
        )
        # A scheduled send, a job edit, a new room or a mailbox mutate skip the
        # email draft even when the words also look like compose — "email me the
        # weather every morning" is a job, not a letter.
        skip_email_draft = other_work and (
            looks_like_scheduled_send(text)
            or looks_like_schedule_manage(text)
            or looks_like_room_create(text)
            or looks_like_mailbox_mutate(text)
            or not looks_like_compose_email(text)
        )
        email_draft = (
            None
            if skip_email_draft
            else complete_email_draft(text, history=self.memory.messages)
        )
        agenda_draft = complete_agenda_draft(text, history=self.memory.messages)
        # Deterministic intent nudge — does not call tools or skip confirm.
        preflight_kinds: list[str] = []
        if bool(agent_cfg.get("intent_preflight", True)):
            intent_hints = detect_intents(text, history=self.memory.messages)
            preflight_kinds = [h.kind for h in intent_hints]
            for hint in intent_hints:
                self._expected_tools.update(hint.expected_tools)
            if looks_like_memory_utterance(text):
                self._expected_tools.add("memory")
            if looks_like_contacts_utterance(text) or looks_like_contacts_followup(
                text, self.memory.messages
            ):
                self._expected_tools.add("contacts")
            if looks_like_tasks_utterance(text):
                self._expected_tools.add("tasks")
            if looks_like_goals_utterance(text):
                self._expected_tools.add("goals")
            if (
                self._expected_tools & _SEE_NO_SMS_REDIRECT
                and not sms_intent_this_turn(text)
            ):
                self._expected_tools.discard("send_sms")
            if "image_edit" in self._expected_tools:
                self._expected_tools.discard("image")
            if "schedule" in self._expected_tools:
                self._expected_tools.discard("send_email")
                self._expected_tools.discard("weather")
            if "browser" in self._expected_tools:
                self._expected_tools.discard("web_search")
            nudge = preflight_system_message(text, history=self.memory.messages)
            if nudge:
                system_messages.append({"role": "system", "content": nudge})
                if self._timer is not None and preflight_kinds:
                    self._timer.mark(
                        "preflight",
                        kinds=",".join(preflight_kinds),
                        expected=",".join(sorted(self._expected_tools)) or "-",
                    )
        skill_ids = select_skill_ids(
            text, available_tools=available, extra_ids=room_skills
        )
        # Short thanks/bye must not revive weather (or a stale web_search habit).
        if looks_like_closing_chitchat(text):
            available = set(available)
            available.discard("weather")
            available.discard("web_search")
            visible = available
            self._expected_tools.discard("weather")
            self._expected_tools.discard("web_search")
        # The vision tool used to be hidden behind a keyword list, because
        # looking cost an unload, a cold VL load, and a re-warm. A multimodal
        # chat model sees at the window it is already loaded with (see
        # ModelRouter.run_vision), so the schema is the only cost left and the
        # window has room for it. The list was also a trap: any phrasing outside
        # it — "what is this?" beside a fresh attachment — left the model
        # schema-blind and it invented a caption.
        if self._expected_tools & _HIDE_WANDER_FOR:
            available = _hide_daily_wander(set(available), self._expected_tools)
            visible = available
        available = _offer_expected(available, self._expected_tools, available_all)
        visible = available
        if (
            looks_like_stale_sms_skip(text, self.memory.messages)
            and "send_sms" not in self._expected_tools
        ) or self._look is not None:
            available = set(available)
            available.discard("send_sms")
            available.discard("send_email")
            visible = available
        active_plan = select_plan(
            text, preflight_kinds=preflight_kinds, skill_ids=skill_ids
        )
        if (
            active_plan is not None
            and active_plan.steps
            and not any(s in available_all for s in active_plan.steps)
        ):
            active_plan = None
        disconnected = disconnected_integration_reply(
            expected=self._expected_tools,
            available=available_all,
            want_sms=bool(
                (sms_draft is not None and sms_draft.complete and not skip_sms_draft)
                or sms_intent_this_turn(text)
            ),
            want_mail=bool(
                (email_draft is not None and email_draft.complete)
                or looks_like_compose_email(text)
            ),
            want_calendar=bool(
                (agenda_draft is not None and agenda_draft.complete)
                or looks_like_calendar_read(text)
                or looks_like_calendar_create(text)
                or looks_like_calendar_delete(text)
            ),
        )
        if disconnected:
            await self._finish(disconnected, [])
            return
        self._active_plan = active_plan
        plan_msg = active_plan.message if active_plan else None
        if plan_msg:
            system_messages.append({"role": "system", "content": plan_msg})
            if self._timer is not None:
                self._timer.mark(
                    "plan_nudge",
                    skills=",".join(skill_ids) or "-",
                    plan=active_plan.id if active_plan else "-",
                )
        # ACE playbook items: short failure lessons matched to this turn.
        if bool(agent_cfg.get("lessons", True)):
            lesson_block = format_lessons(
                select_lessons(
                    skill_ids=skill_ids,
                    preflight_kinds=preflight_kinds,
                    user_text=text,
                )
            )
            if lesson_block:
                system_messages.append({"role": "system", "content": lesson_block})
        workspace = self.config.get("_workspace")
        if workspace is not None and _wants_project_context(
            role=role,
            skill_ids=skill_ids,
            expected_tools=self._expected_tools,
        ):
            project_line = workspace.prompt_line()
            if project_line:
                system_messages.append({"role": "system", "content": project_line})
        # A room's purpose rides every turn taken inside it. It sits after the
        # project line because it explains what the project is *for*, and before
        # the standing profile because it is the narrower context of the two.
        if active_room is not None:
            system_messages.append(
                {"role": "system", "content": active_room.prompt_block()}
            )
        location = self.config.get("_location")
        if location is not None:
            # Injected rather than left to the user_location tool. A 7B model
            # asked about the weather reliably fails to work out that it should
            # first go and find out where the user lives, and one short line
            # costs less than the round trip it prevents.
            place_line = location.prompt_line()
            if place_line:
                system_messages.append({"role": "system", "content": place_line})
        # Hand-edited standing identity/prefs from data/profile.yaml (user:).
        # Kept separate from SQLite facts so a short profile does not depend on
        # the History approve queue.
        profile_line = standing_profile_prompt_line(config=self.config)
        if profile_line:
            system_messages.append({"role": "system", "content": profile_line})
        # Same idea as location/profile: a 7B will not reliably open the
        # contacts tool before texting, so the live alias list rides every turn.
        contacts_line = contacts_prompt_line()
        if contacts_line:
            system_messages.append({"role": "system", "content": contacts_line})
        facts_line = self._active_facts_line()
        if facts_line:
            system_messages.append({"role": "system", "content": facts_line})
        store = self.memory.sink if isinstance(self.memory.sink, MemoryStore) else None
        if store is not None:
            episode_line = episodes_prompt_line(store, limit=3)
            if episode_line:
                system_messages.append({"role": "system", "content": episode_line})
        world_line = world_state_prompt_line(
            self.config,
            role=role,
            model=model,
            workspace=self.config.get("_workspace"),
            store=store,
        )
        if world_line:
            system_messages.append({"role": "system", "content": world_line})
        if speak:
            # Conversation mode plays the answer aloud. Bias toward short
            # spoken replies unless the user asked for detail — but still call
            # tools; the confirm card is how sends actually happen.
            system_messages.append(
                {
                    "role": "system",
                    "content": (
                        "You are speaking aloud in conversation mode. Prefer "
                        "1-3 short sentences unless the user asked for detail, "
                        "code, steps, or a list. When they asked you to do "
                        "something (text, email, write, search, weather, "
                        "scrape, remember), call the tool first — do not only "
                        "talk about doing it, and do not ask permission in chat. "
                        "send_sms and send_email open a confirm card; that is "
                        "how the message is approved."
                    ),
                }
            )
        # The clock goes last of the system lines because it is the only one that
        # changes on its own. It used to sit directly behind the static prefix,
        # where every minute rollover re-prefilled the focus card, the preflight
        # nudge, the facts and the world state behind it. Nothing about the
        # persona or the policy depends on the time, and putting the freshest
        # fact nearest the question does the model no harm.
        system_messages.append({"role": "system", "content": now_line()})
        # Pin system messages. Ollama drops overflow from the front, so without
        # this the persona and tool policy are the first things a long session
        # loses, and every later answer is given by a model with no identity.
        ollama_cfg = self.config.get("ollama") or {}
        num_ctx = int(ollama_cfg.get("num_ctx") or shipped_num_ctx())
        if role == "research" and ollama_cfg.get("research_num_ctx"):
            num_ctx = int(ollama_cfg["research_num_ctx"])
        # Sticky for the turn so mid-escalate does not shrink under a built prompt.
        self._turn_num_ctx = num_ctx
        tool_reserve_chars = (
            min(self.tool_output_chars, _SPEAK_TOOL_OUTPUT_CHARS)
            if speak
            else self.tool_output_chars
        )
        # Conversation small-talk: do not reserve a scrape slab when nothing
        # in this turn asked for a tool. That reserve was eating the last turn.
        if speak and not self._expected_tools and not skill_ids:
            tool_reserve_chars = 0
        exact_cfg = bool(agent_cfg.get("exactness", True))
        exact_need = detect_exactness_need(text)
        ctx = TurnContext(
            text=text,
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
            numeric_gate=exact_cfg and bool(agent_cfg.get("numeric_gate", True)),
            evidence_gate=exact_cfg and bool(agent_cfg.get("evidence_gate", True)),
            research_dual=exact_cfg and bool(agent_cfg.get("research_dual_hit", True)),
            research_min_sources=max(
                1, int(agent_cfg.get("research_min_sources", 2))
            ),
            exact_need=exact_need,
        )
        # Containers stay aliased so the rest of _run can append without a
        # ctx. prefix on every line. Scalars that get rebound must go through
        # ctx — a local `ctx.math_nudge_used = True` would not write back.
        tool_names = ctx.tool_names
        sources = ctx.sources
        ledger = ctx.ledger
        fail_counts = ctx.fail_counts
        skip_counts = ctx.skip_counts
        web_search_ok = ctx.web_search_ok
        sms_sent = ctx.sms_sent
        agenda_created = ctx.agenda_created
        weather_ok_places = ctx.weather_ok_places
        weather_days_retried = ctx.weather_days_retried
        numeric_gate = ctx.numeric_gate
        evidence_gate = ctx.evidence_gate
        research_dual = ctx.research_dual
        research_min_sources = ctx.research_min_sources
        # Research role / deep-dive always needs web warrants for contingent claims.
        if research_mode and not exact_need.needs_web_evidence:
            kinds = list(exact_need.kinds)
            if "web" not in kinds:
                kinds.append("web")
            exact_need = replace(
                exact_need, needs_web_evidence=True, kinds=tuple(kinds)
            )
            ctx.exact_need = exact_need
        # News / current-events turns should not end on search snippets alone.
        wants_fresh_page = (
            exact_need.needs_web_evidence
            or research_mode
            or ("web" in skill_ids)
            or ("research" in skill_ids)
            or wants_fresh_page_ask(text)
        )
        # "weather today" must not arm scrape-after-search.
        if (
            "weather" in self._expected_tools
            and "web_search" not in self._expected_tools
            and "scrape" not in self._expected_tools
        ):
            wants_fresh_page = False
        # A YouTube / Chrome drive is not a scrape-the-web turn.
        if "browser" in self._expected_tools:
            wants_fresh_page = False
        # Chat fast-path: skip tool schemas + hold_paint when nothing suggests
        # a tool. Cuts prefill and lets short replies stream (felt TTFT).
        # Must still arm tools for ANY exactness warrant (vision/inbox/…) —
        # calc+web alone left describe/regen turns schema-blind, so the 7B
        # invented captions or claimed it cannot generate images.
        offer_tools = should_offer_tools(
            chat_fast_path=bool(agent_cfg.get("chat_fast_path", True)),
            skill_ids=skill_ids,
            preflight_kinds=preflight_kinds,
            research_mode=research_mode,
            expected_tools=self._expected_tools,
            exact_need=exact_need,
            wants_fresh_page=wants_fresh_page,
            active_plan=active_plan,
        )
        ollama_tools = self.tools.ollama_tools(visible) if offer_tools else []
        if self._timer is not None and not offer_tools:
            self._timer.mark("chat_fast_path", tools=0)

        # The budget is built here, after the tool array exists, because the
        # schemas are prompt and have to be paid for before history is offered
        # what is left. A fast-path turn carries no schemas and gets the room.
        budget = context_budget(
            num_ctx,
            tool_output_chars=tool_reserve_chars,
            chars_per_token=ratio,
            schema_chars=len(json.dumps(ollama_tools)) if ollama_tools else 0,
        )
        ctx.wants_fresh_page = wants_fresh_page
        ctx.offer_tools = offer_tools
        ctx.ollama_tools = ollama_tools
        ctx.messages = await self._messages_for_turn(
            system_messages, budget, ratio, role, user_text=text
        )
        messages = ctx.messages

        # A complete SMS draft is a deterministic first move, so the Allow card
        # is raised before the model gets a round. Tool-bearing rounds hold the
        # answer back (hold_paint), which on a spoken "text my wife …" meant a
        # blank thread for as long as the 7B took to decide: the operator read
        # that as hung, pressed Esc to clear it, and the send died with the turn.
        # Allow is still the only thing that sends, and the model still writes
        # the reply on the round after the tool result.
        if (
            "send_sms" in self._expected_tools
            and "send_sms" not in available_all
            and sms_intent_this_turn(text)
        ):
            await self._explain_missing_send_sms(available_all)
        elif sms_draft is not None and sms_draft.complete and not skip_sms_draft:
            if "send_sms" not in tool_names:
                if sms_intent_this_turn(text):
                    await self._explain_missing_send_sms(available_all)
            elif bool(agent_cfg.get("sms_force_call", True)) and bool(
                agent_cfg.get("sms_preinject", True)
            ):
                ctx.sms_preinject = draft_send_sms_args(sms_draft)
        sms_preinject = ctx.sms_preinject

        for round_i in range(1, self.max_rounds + 1):
            await self._hold_if_paused()

            escalated = await self._maybe_escalate(
                text,
                round_i=round_i,
                agent_cfg=agent_cfg,
            )
            role = self._turn_role
            model = self.router.model_for(role)
            if escalated:
                research_mode = is_research_mode(role, text)
                if research_mode:
                    self.max_rounds = max(
                        self.max_rounds,
                        int(agent_cfg.get("research_max_rounds", 12)),
                    )
                visible = filter_tool_names(
                    available_all,
                    role=role,
                    text=text,
                    enabled=bool(agent_cfg.get("research_tool_subset", True)),
                    skill_subset=bool(agent_cfg.get("skill_tool_subset", True)),
                    history=self.memory.messages,
                )
                available = visible
                if self._look is not None:
                    look_tools = {n for n in available_all if n in LOOK_TOOL_SUBSET}
                    if look_tools:
                        available = look_tools
                        visible = look_tools
                if self._expected_tools & _HIDE_WANDER_FOR:
                    available = _hide_daily_wander(
                        set(available), self._expected_tools
                    )
                    visible = available
                available = _offer_expected(
                    available, self._expected_tools, available_all
                )
                visible = available
                if (
                    looks_like_stale_sms_skip(text, self.memory.messages)
                    and "send_sms" not in self._expected_tools
                ) or self._look is not None:
                    available = set(available)
                    available.discard("send_sms")
                    available.discard("send_email")
                    visible = available
                ollama_tools = self.tools.ollama_tools(visible)
                ctx.tool_names.clear()
                ctx.tool_names.update(visible)
                ctx.ollama_tools = ollama_tools
                ctx.available = set(available)
                ctx.visible = set(visible)
                ctx.research_mode = research_mode
                tool_names = ctx.tool_names

            if round_i > 1 and (
                ctx.email_sent_ok or ctx.agenda_create_ok or bool(sms_sent)
            ):
                offer_tools = False
                ollama_tools = []
                ctx.offer_tools = False
                ctx.ollama_tools = []
                ctx.tool_names.clear()
                tool_names = ctx.tool_names

            await self.bus.publish(
                Event(
                    EventType.THINKING,
                    {"text": f"round {round_i}/{self.max_rounds}  model step"},
                )
            )

            tools_arg = None if ctx.fallback_mode else (ollama_tools or None)
            round_ms = 0
            if sms_preinject is not None:
                injected = sms_preinject
                sms_preinject = None
                content = ""
                streamed = ""
                calls = [("send_sms", injected)]
                tool_calls = [_native_tool_call("send_sms", injected)]
                await self.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": "inject  send_sms from a complete draft (pre-model)"},
                    )
                )
                await self.bus.publish(
                    Event(EventType.STATUS, {"message": "Calling send_sms…"})
                )
                if self._timer is not None:
                    self._timer.mark(
                        "exactness", gate="sms_force", action="preinject"
                    )
            else:
                try:
                    round_t0 = time.perf_counter()
                    raw_content, tool_calls, streamed = await self._stream_round(
                        role, messages, tools_arg, round_n=round_i
                    )
                    round_ms = int((time.perf_counter() - round_t0) * 1000)
                    if self._timer is not None:
                        self._timer.rounds += 1
                        self._timer.model_ms += round_ms
                except _StoppedError:
                    raise
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # Some model/Ollama combinations reject the tools array
                    # outright. Retry once without it and let the JSON protocol
                    # carry the call. A dead or missing Ollama is not that case —
                    # don't spend a second stream on JSON fallback while the chip
                    # is already red.
                    await self._retract()
                    failure = classify_ollama_failure(
                        exc,
                        model=model,
                        base_url=str(
                            (self.config.get("ollama") or {}).get("base_url") or ""
                        ),
                        role=str(self._turn_role or ""),
                    )
                    if (
                        self.json_fallback
                        and not ctx.fallback_mode
                        and ollama_tools
                        and not failure.skip_tool_fallback
                    ):
                        ctx.fallback_mode = True
                        messages[:] = _normalize_ollama_messages(messages)
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        f"native tools failed ({exc}); "
                                        "JSON fallback"
                                    )
                                },
                            )
                        )
                        continue
                    if (
                        is_vram_failure(exc)
                        and ctx.last_ok_tool_out
                        and "research_report" in self.tools_used
                    ):
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        "research_report ready; answering "
                                        "from artifact"
                                    )
                                },
                            )
                        )
                        await self._finish(
                            _tool_followup_fallback(ctx.last_ok_tool_out, ctx.last_ok_tool_name),
                            sources,
                            streamed="",
                        )
                        return
                    if ctx.last_ok_tool_out and _is_ollama_object_400(exc):
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        "ollama 400 after tool; answering "
                                        "from result"
                                    )
                                },
                            )
                        )
                        await self._finish(
                            _tool_followup_fallback(ctx.last_ok_tool_out, ctx.last_ok_tool_name),
                            sources,
                            streamed="",
                        )
                        return
                    await self._publish_error(failure.chat, detail=failure.detail)
                    return

                content = strip_thinking_text(raw_content)
                calls = extract_native_tool_calls(tool_calls)

            if not calls and self.json_fallback:
                # strict while native tool calling is working: only a trailing
                # JSON object counts as an instruction. Scanning prose for
                # embedded JSON would let an answer that merely discusses or
                # demonstrates a tool call execute it.
                parsed = parse_fallback_payload(content, strict=not ctx.fallback_mode)
                if parsed and parsed["kind"] == "tool":
                    calls = [(parsed["name"], parsed["args"])]
                elif parsed and parsed["kind"] == "final":
                    content = parsed["text"]

            if not calls:
                # The model wrote a call as prose instead of making one, so the
                # strict parser refused it. Executing it anyway is the hole
                # strict mode exists to close, and shipping it means the user
                # gets raw JSON as their answer and no tool ever runs. Neither
                # is acceptable, so ask again and say what went wrong.
                stray = (
                    parse_fallback_payload(content, strict=False)
                    if self.json_fallback and not ctx.fallback_mode
                    else None
                )
                if stray and stray["kind"] == "tool" and ctx.nudges < _MAX_TOOL_NUDGES:
                    ctx.nudges += 1
                    await self._retract()
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": _MALFORMED_CALL_NOTICE.format(
                                tool=stray["name"],
                                args=json.dumps(stray["args"], default=str),
                            ),
                        }
                    )
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "tool call written as prose; asking for a real one"},
                        )
                    )
                    continue

                if not content and not ctx.fallback_mode:
                    # Qwen3.5 often puts the wrap-up in thinking and leaves
                    # chat content empty. Native calling still worked — a tool
                    # already ran — so do not enter the sticky-note protocol
                    # and do not ship the "empty reply / model unloaded" notice.
                    # Tools may already be stripped (agenda/SMS/email wrap-up).
                    if ctx.last_ok_tool_out:
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        "empty after tool; answering from result"
                                    )
                                },
                            )
                        )
                        await self._finish(
                            _tool_followup_fallback(ctx.last_ok_tool_out, ctx.last_ok_tool_name),
                            sources,
                            streamed="",
                        )
                        return
                    if ollama_tools and self.json_fallback:
                        # First round still blank with no tools yet? JSON fallback.
                        await self._retract()
                        ctx.fallback_mode = True
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "empty tool response; JSON fallback"},
                            )
                        )
                        continue
                # Complete SMS draft but recipients remain — nudge once, then inject.
                sms_remaining = []
                if sms_draft is not None and sms_draft.complete:
                    sent_l = {s.lower() for s in sms_sent}
                    sms_remaining = [
                        a
                        for a in sms_draft.resolved_aliases
                        if a and a.lower() not in sent_l
                    ]
                    if not sms_remaining and not sms_sent and sms_draft.tool_to:
                        sms_remaining = [sms_draft.tool_to]
                if (
                    bool(agent_cfg.get("sms_force_call", True))
                    and sms_draft is not None
                    and sms_draft.complete
                    and sms_remaining
                    and "send_sms" in tool_names
                ):
                    if ctx.sms_nudge_used < 1:
                        ctx.sms_nudge_used += 1
                        await self._retract()
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {
                                "role": "user",
                                "content": sms_force_call_notice(
                                    sms_draft, already_sent=sms_sent
                                ),
                            }
                        )
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        "SMS draft ready; asking for a real "
                                        "send_sms call"
                                    )
                                },
                            )
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "exactness", gate="sms_force", action="nudge"
                            )
                        continue
                    # Nudge ignored — inject drafted send_sms (Allow still required).
                    # Do not re-inject after a failed send (same bad card twice).
                    if not ctx.sms_failed:
                        inj = draft_send_sms_args(
                            sms_draft, already_sent=sms_sent
                        )
                        calls = [("send_sms", inj)]
                        tool_calls = [_native_tool_call("send_sms", inj)]
                        await self._retract()
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "inject  send_sms from draft"},
                            )
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "exactness", gate="sms_force", action="inject"
                            )
                # Complete email draft — nudge once, then inject.
                elif (
                    bool(agent_cfg.get("email_force_call", True))
                    and email_draft is not None
                    and email_draft.complete
                    and "send_email" in tool_names
                    and "send_email" not in self.tools_used
                ):
                    if ctx.email_nudge_used < 1:
                        ctx.email_nudge_used += 1
                        await self._retract()
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {
                                "role": "user",
                                "content": email_force_call_notice(email_draft),
                            }
                        )
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        "email draft ready; asking for a real "
                                        "send_email call"
                                    )
                                },
                            )
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "exactness", gate="email_force", action="nudge"
                            )
                        continue
                    inj = draft_send_email_args(email_draft)
                    calls = [("send_email", inj)]
                    tool_calls = [_native_tool_call("send_email", inj)]
                    await self._retract()
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  send_email from draft"},
                        )
                    )
                    if self._timer is not None:
                        self._timer.mark(
                            "exactness", gate="email_force", action="inject"
                        )
                elif (
                    looks_like_mailbox_mutate(text)
                    and "inbox" in tool_names
                    and not ctx.inbox_mutated_ok
                ):
                    inbox = self.tools.get("inbox")
                    hits = getattr(inbox, "last_hits", None) if inbox is not None else None
                    inj = draft_inbox_mutate_args(
                        text,
                        last_hits=hits if isinstance(hits, list) else None,
                    )
                    action = str(inj.get("action") or "").lower()
                    if action == "search" and "inbox" in self.tools_used:
                        inj = {}
                    if inj:
                        calls = [("inbox", inj)]
                        tool_calls = [_native_tool_call("inbox", inj)]
                        await self._retract()
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "inject  inbox from intent"},
                            )
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "exactness", gate="inbox_mutate", action="inject"
                            )
                # Complete agenda create — force on missing create success, not
                # any agenda list/today call.
                elif (
                    bool(agent_cfg.get("agenda_force_call", True))
                    and agenda_draft is not None
                    and agenda_draft.complete
                    and "agenda" in tool_names
                    and not ctx.agenda_create_ok
                ):
                    if ctx.agenda_nudge_used < 1:
                        ctx.agenda_nudge_used += 1
                        await self._retract()
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {
                                "role": "user",
                                "content": agenda_force_call_notice(agenda_draft),
                            }
                        )
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        "agenda draft ready; asking for a real "
                                        "agenda create call"
                                    )
                                },
                            )
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "exactness", gate="agenda_force", action="nudge"
                            )
                        continue
                    inj = draft_agenda_create_args(agenda_draft)
                    calls = [("agenda", inj)]
                    tool_calls = [_native_tool_call("agenda", inj)]
                    await self._retract()
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  agenda create from draft"},
                        )
                    )
                    if self._timer is not None:
                        self._timer.mark(
                            "exactness", gate="agenda_force", action="inject"
                        )
                elif (
                    bool(agent_cfg.get("agenda_force_call", True))
                    and looks_like_calendar_delete(text)
                    and "agenda" in tool_names
                    and "agenda" not in self.tools_used
                    and "agenda" in self._expected_tools
                ):
                    if ctx.agenda_nudge_used < 1:
                        ctx.agenda_nudge_used += 1
                        await self._retract()
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {
                                "role": "user",
                                "content": agenda_force_delete_notice(),
                            }
                        )
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        "agenda delete ready; asking for a real "
                                        "agenda delete call"
                                    )
                                },
                            )
                        )
                        continue
                    # Inject delete by title/time; only use an id the user pasted.
                    inj = draft_agenda_delete_args(
                        text,
                        receipts=self._receipts,
                        history=self.memory.messages,
                    )
                    calls = [("agenda", inj)]
                    tool_calls = [_native_tool_call("agenda", inj)]
                    await self._retract()
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  agenda delete"},
                        )
                    )
                elif (
                    bool(agent_cfg.get("agenda_force_call", True))
                    and looks_like_calendar_close(text)
                    and "agenda" in tool_names
                    and "agenda" not in self.tools_used
                ):
                    if ctx.agenda_nudge_used < 1:
                        ctx.agenda_nudge_used += 1
                        await self._retract()
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {
                                "role": "user",
                                "content": agenda_force_close_notice(),
                            }
                        )
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        "agenda close ready; asking for a real "
                                        "agenda close call"
                                    )
                                },
                            )
                        )
                        continue
                    inj = {"action": "close"}
                    calls = [("agenda", inj)]
                    tool_calls = [_native_tool_call("agenda", inj)]
                    await self._retract()
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  agenda close from intent"},
                        )
                    )
                elif (
                    bool(agent_cfg.get("agenda_force_call", True))
                    and looks_like_calendar_open(text)
                    and "agenda" in tool_names
                    and "agenda" not in self.tools_used
                ):
                    if ctx.agenda_nudge_used < 1:
                        ctx.agenda_nudge_used += 1
                        await self._retract()
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {
                                "role": "user",
                                "content": agenda_force_open_notice(),
                            }
                        )
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        "agenda open ready; asking for a real "
                                        "agenda open call"
                                    )
                                },
                            )
                        )
                        continue
                    inj = {"action": "open"}
                    calls = [("agenda", inj)]
                    tool_calls = [_native_tool_call("agenda", inj)]
                    await self._retract()
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  agenda open from intent"},
                        )
                    )
                elif (
                    match_tile_intent(text)
                    and "tile" in tool_names
                    and "tile" not in self.tools_used
                ):
                    from arelis.tools.tile import TileTool

                    hit = match_tile_intent(text)
                    calendar_uses_agenda = (
                        hit is not None
                        and hit[1] == "calendar"
                        and "agenda" in tool_names
                    )
                    inj = (
                        None
                        if calendar_uses_agenda
                        else tile_tool_args(text, last_name=TileTool.last_name)
                    )
                    if inj:
                        calls = [("tile", inj)]
                        tool_calls = [_native_tool_call("tile", inj)]
                        await self._retract()
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "inject  tile from intent"},
                            )
                        )
                elif (
                    bool(agent_cfg.get("agenda_force_call", True))
                    and looks_like_calendar_read(text)
                    and "agenda" in tool_names
                    and "agenda" not in self.tools_used
                    and (
                        "agenda" in self._expected_tools
                        or exact_need.needs_agenda
                    )
                ):
                    if ctx.agenda_nudge_used < 1:
                        ctx.agenda_nudge_used += 1
                        await self._retract()
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {
                                "role": "user",
                                "content": agenda_force_read_notice(
                                    agenda_read_action(text)
                                ),
                            }
                        )
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        "agenda read ready; asking for a real "
                                        "agenda list call"
                                    )
                                },
                            )
                        )
                        continue
                    inj = {"action": agenda_read_action(text)}
                    calls = [("agenda", inj)]
                    tool_calls = [_native_tool_call("agenda", inj)]
                    await self._retract()
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  agenda read from intent"},
                        )
                    )
                elif (
                    bool(agent_cfg.get("image_force_call", True))
                    and "image_edit" not in self._expected_tools
                    and "image_edit" not in preflight_kinds
                    and not wants_image_edit(
                        split_attachments_turn(text)[1] or text
                    )
                    and "image" in self._expected_tools
                    and "image" not in self.tools_used
                    and not ctx.image_attempted
                    and "image" in tool_names
                    and (
                        looks_like_image_gen(text)
                        or "image_gen" in preflight_kinds
                    )
                ):
                    if ctx.image_nudge_used < 1:
                        ctx.image_nudge_used += 1
                        await self._retract()
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {
                                "role": "user",
                                "content": image_force_call_notice(prompt_hint=text),
                            }
                        )
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        "image ask ready; asking for a real image call"
                                    )
                                },
                            )
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "exactness", gate="image_force", action="nudge"
                            )
                        continue
                    inj = {"prompt": text.strip()[:300]}
                    calls = [("image", inj)]
                    tool_calls = [_native_tool_call("image", inj)]
                    await self._retract()
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  image from intent"},
                        )
                    )
                elif (
                    bool(agent_cfg.get("image_force_call", True))
                    and "image_edit" in self._expected_tools
                    and "image_edit" not in self.tools_used
                    and "image_edit" in tool_names
                    and (
                        wants_image_edit(split_attachments_turn(text)[1] or text)
                        or "image_edit" in preflight_kinds
                    )
                ):
                    ask = split_attachments_turn(text)[1] or text
                    rows = parse_attachments_from_turn(text)
                    path = str(rows[0].get("path") or "") if rows else ""
                    if path:
                        inj_edit: dict[str, Any] = {"path": path}
                        if re.search(r"(?i)youtube|\bthumbnail\b", ask):
                            inj_edit["preset"] = "youtube_thumbnail"
                        if re.search(r"(?i)vibrant|vibrance|saturat", ask):
                            inj_edit["vibrance"] = 1.3
                        size = re.search(
                            r"(?i)(\d{2,5})\s*(?:x|\u00d7|by)\s*(\d{2,5})",
                            ask,
                        )
                        if size:
                            inj_edit["width"] = int(size.group(1))
                            inj_edit["height"] = int(size.group(2))
                            inj_edit.pop("preset", None)
                        calls = [("image_edit", inj_edit)]
                        tool_calls = [_native_tool_call("image_edit", inj_edit)]
                        await self._retract()
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "inject  image_edit from intent"},
                            )
                        )
                elif self._look is not None:
                    nxt = next_look_call(
                        self._look.intent,
                        path=self._look.path,
                        camera_done=self._look.camera_snaps > 0,
                        ocr_done=self._look.ocr_done,
                        vision_done=self._look.vision_done,
                        deferral=self._look.deferral,
                    )
                    if nxt is not None:
                        inj_name, inj = nxt
                        if inj_name in tool_names:
                            calls = [(inj_name, inj)]
                            tool_calls = [_native_tool_call(inj_name, inj)]
                            await self._retract()
                            await self.bus.publish(
                                Event(
                                    EventType.THINKING,
                                    {
                                        "text": (
                                            f"inject  look {self._look.intent.act} "
                                            f"{inj_name}"
                                        )
                                    },
                                )
                            )
                            if self._timer is not None:
                                self._timer.mark(
                                    "look",
                                    act=self._look.intent.act,
                                    tool=inj_name,
                                    action="inject",
                                )
                elif (
                    bool(agent_cfg.get("vision_force_call", True))
                    and "vision" in self._expected_tools
                    and "vision" not in self.tools_used
                    and "vision" in tool_names
                ):
                    from arelis.core.image_refs import latest_generated_image_path

                    path = (
                        latest_generated_image_path(self.memory.messages) or ""
                    )
                    if not path:
                        filled = fill_vision_args(
                            {},
                            history=self.memory.messages,
                            user_text=text,
                        )
                        path = str(filled.get("path") or "")
                    if ctx.vision_nudge_used < 1:
                        ctx.vision_nudge_used += 1
                        await self._retract()
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "Call vision now with the generated image path"
                                    + (f" path={path}" if path else "")
                                    + ". Do not web_search."
                                ),
                            }
                        )
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "vision ask ready; asking for vision call"},
                            )
                        )
                        continue
                    if path:
                        inj = {"path": path}
                        calls = [("vision", inj)]
                        tool_calls = [_native_tool_call("vision", inj)]
                        await self._retract()
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "inject  vision from intent"},
                            )
                        )
                elif (
                    bool(agent_cfg.get("weather_force_call", True))
                    and exact_need.needs_weather
                    and not looks_like_scheduled_send(text)
                    and not looks_like_schedule_manage(text)
                    and not ctx.schedule_managed_ok
                    and weather_places_missing(text, weather_ok_places)
                    and "weather" in tool_names
                ):
                    if ctx.weather_nudge_used < 1 and not weather_ok_places:
                        ctx.weather_nudge_used += 1
                        await self._retract()
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {"role": "user", "content": weather_force_notice()}
                        )
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        "weather ask; asking for a real weather call"
                                    )
                                },
                            )
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "exactness", gate="weather_force", action="nudge"
                            )
                        continue
                    inj = draft_weather_args(text)
                    missing = weather_places_missing(text, weather_ok_places)
                    if missing:
                        if missing[0]:
                            inj["place"] = missing[0]
                        else:
                            inj.pop("place", None)
                    calls = [("weather", inj)]
                    tool_calls = [_native_tool_call("weather", inj)]
                    await self._retract()
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  weather from intent"},
                        )
                    )
                    if self._timer is not None:
                        self._timer.mark(
                            "exactness", gate="weather_force", action="inject"
                        )
                elif (
                    not (content or "").strip()
                    and numeric_gate
                    and exact_need.needs_catalog
                    and not ledger.has_ok("catalog")
                    and "catalog" in tool_names
                    and "catalog" not in self.tools_used
                ):
                    if not ctx.catalog_nudge_used:
                        ctx.catalog_nudge_used = True
                        await self._retract()
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {"role": "user", "content": catalog_force_notice()}
                        )
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        "catalog ask; asking for a real catalog call"
                                    )
                                },
                            )
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "exactness", gate="catalog_force", action="nudge"
                            )
                        continue
                    inj = draft_catalog_args(text)
                    calls = [("catalog", inj)]
                    tool_calls = [_native_tool_call("catalog", inj)]
                    await self._retract()
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  catalog from intent"},
                        )
                    )
                    if self._timer is not None:
                        self._timer.mark(
                            "exactness", gate="catalog_force", action="inject"
                        )
                elif (
                    bool(agent_cfg.get("tasks_force_call", True))
                    and (
                        exact_need.needs_tasks
                        or "tasks" in self._expected_tools
                        or looks_like_tasks_utterance(text)
                    )
                    and "tasks" not in self.tools_used
                    and "tasks" in tool_names
                ):
                    inj = local_store_inject_args(
                        "tasks",
                        text,
                        receipts=self._receipts,
                        history=self.memory.messages,
                    )
                    calls = [("tasks", inj)]
                    tool_calls = [_native_tool_call("tasks", inj)]
                    await self._retract()
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  tasks from intent"},
                        )
                    )
                    if self._timer is not None:
                        self._timer.mark(
                            "exactness", gate="tasks_force", action="inject"
                        )
                elif (
                    bool(agent_cfg.get("goals_force_call", True))
                    and (
                        exact_need.needs_goals
                        or "goals" in self._expected_tools
                        or looks_like_goals_utterance(text)
                    )
                    and "goals" not in self.tools_used
                    and "goals" in tool_names
                ):
                    ids = last_store_ids_from_context(
                        self.memory.messages, self._receipts
                    )
                    if (
                        re.search(r"(?i)\b(?:both|all)\b", text or "")
                        and len(ids) > 1
                    ):
                        calls = [
                            ("goals", {"action": "remove", "id": gid})
                            for gid in ids
                        ]
                        tool_calls = [
                            _native_tool_call("goals", {"action": "remove", "id": gid})
                            for gid in ids
                        ]
                    else:
                        inj = local_store_inject_args(
                            "goals",
                            text,
                            receipts=self._receipts,
                            history=self.memory.messages,
                        )
                        calls = [("goals", inj)]
                        tool_calls = [_native_tool_call("goals", inj)]
                    await self._retract()
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  goals from intent"},
                        )
                    )
                    if self._timer is not None:
                        self._timer.mark(
                            "exactness", gate="goals_force", action="inject"
                        )
                elif (
                    (
                        "memory" in self._expected_tools
                        or looks_like_memory_utterance(text)
                    )
                    and "memory" not in self.tools_used
                    and "memory" in tool_names
                ):
                    if ctx.memory_nudge_used < 1:
                        ctx.memory_nudge_used += 1
                        await self._retract()
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "Call the memory tool now. Use action=remember "
                                    "or action=forget with the fact quoted from "
                                    "the user. Do not call recall instead, and "
                                    "do not open a browser."
                                ),
                            }
                        )
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "memory ask; asking for a real memory call"},
                            )
                        )
                        continue
                    inj = local_store_inject_args("memory", text)
                    calls = [("memory", inj)]
                    tool_calls = [_native_tool_call("memory", inj)]
                    await self._retract()
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  memory from intent"},
                        )
                    )
                elif (
                    (
                        "contacts" in self._expected_tools
                        or looks_like_contacts_utterance(text)
                        or looks_like_contacts_followup(text, self.memory.messages)
                    )
                    and "contacts" not in self.tools_used
                    and "contacts" in tool_names
                ):
                    who = contact_who_from_text(text)
                    if not who:
                        for item in reversed(self.memory.messages[-8:]):
                            role = getattr(item, "role", "")
                            content_h = getattr(item, "content", "") or ""
                            if role == "user":
                                who = contact_who_from_text(str(content_h))
                                if who:
                                    break
                    inj = {"action": "get", "who": who or "wife"}
                    calls = [("contacts", inj)]
                    tool_calls = [_native_tool_call("contacts", inj)]
                    await self._retract()
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  contacts from intent"},
                        )
                    )
                elif (
                    (
                        "browser" in self._expected_tools
                        or looks_like_browser_or_url(text)
                    )
                    and not looks_like_calendar_open(text)
                    and not looks_like_calendar_close(text)
                    and not match_tile_intent(text)
                    and "browser" not in self.tools_used
                    and "browser" in tool_names
                ):
                    inj = draft_browser_args(text)
                    calls = [("browser", inj)]
                    tool_calls = [_native_tool_call("browser", inj)]
                    await self._retract()
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  browser from intent"},
                        )
                    )
                elif (
                    looks_like_browser_click_signin(text)
                    and "browser" in self.tools_used
                    and not ctx.browser_clicked
                    and "browser" in tool_names
                ):
                    inj = draft_signin_click_args(ctx.last_browser_snapshot)
                    if inj:
                        calls = [("browser", inj)]
                        tool_calls = [_native_tool_call("browser", inj)]
                        await self._retract()
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        "inject  browser click Sign in "
                                        f"ref={inj.get('ref')}"
                                    )
                                },
                            )
                        )
                elif (
                    (
                        "rooms" in self._expected_tools
                        or looks_like_room_create(text)
                    )
                    and "rooms" not in self.tools_used
                    and "rooms" in tool_names
                ):
                    inj = draft_rooms_create_args(text)
                    calls = [("rooms", inj)]
                    tool_calls = [_native_tool_call("rooms", inj)]
                    await self._retract()
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  rooms create from intent"},
                        )
                    )

                before_sched = list(calls)
                stripped_run_now = looks_like_bare_confirm(text) and any(
                    n == "schedule"
                    and str((a or {}).get("action") or "").lower() == "run_now"
                    for n, a in before_sched
                )
                calls = rewrite_schedule_calls(
                    text,
                    calls,
                    schedule_used="schedule" in self.tools_used,
                    schedule_available="schedule" in tool_names,
                )
                if calls != before_sched:
                    tool_calls = [
                        _native_tool_call(n, a) for n, a in calls
                    ]
                    if not before_sched and calls:
                        await self._retract()
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "inject  schedule briefing from intent"},
                            )
                        )
                if stripped_run_now and not calls:
                    await self._finish(
                        "The job is already scheduled. It will run at the time "
                        "you set — no need to fire it now."
                    )
                    return

                before_browser = list(calls)
                calls = rewrite_browser_calls(calls, text=text)
                if calls != before_browser:
                    tool_calls = [
                        _native_tool_call(n, a) for n, a in calls
                    ]
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "rewrite  invented browser action → snapshot"},
                        )
                    )

                if not calls:
                    # Searched but never opened a page — one forced scrape round.
                    if (
                        bool(agent_cfg.get("scrape_after_search", True))
                        and wants_fresh_page
                        and not ctx.scrape_nudge_used
                        and "web_search" in self.tools_used
                        and "browser" not in self._expected_tools
                        and "browser" not in self.tools_used
                        and not (self.tools_used & _WEB_TOOLS)
                        and ("scrape" in tool_names or "research_report" in tool_names)
                    ):
                        ctx.scrape_nudge_used = True
                        await self._retract()
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {"role": "user", "content": _SCRAPE_AFTER_SEARCH_NOTICE}
                        )
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        "search without scrape; asking for a page read"
                                    )
                                },
                            )
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "exactness",
                                gate="scrape_after_search",
                                action="nudge",
                            )
                        continue
                    if (
                        bool(agent_cfg.get("browser_after_js_shell", True))
                        and ctx.js_shell_url
                        and not ctx.js_shell_nudge_used
                        and "browser" in available_all
                        and "browser" not in self.tools_used
                        and not (self._expected_tools & {"weather", "send_sms", "send_email"})
                    ):
                        ctx.js_shell_nudge_used = True
                        # Web-skill turns do not offer browser up front (or she
                        # skips scrape). Offer it now so the nudge can land.
                        if "browser" not in tool_names:
                            visible = set(visible) | {"browser"}
                            available = set(available) | {"browser"}
                            ctx.tool_names.clear()
                            ctx.tool_names.update(visible)
                            tool_names = ctx.tool_names
                            if offer_tools:
                                ollama_tools = self.tools.ollama_tools(visible)
                        await self._retract()
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {
                                "role": "user",
                                "content": _JS_SHELL_BROWSER_NOTICE.format(
                                    url=ctx.js_shell_url
                                ),
                            }
                        )
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        "js shell; asking to open the page in her window"
                                    )
                                },
                            )
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "exactness",
                                gate="browser_after_js_shell",
                                action="nudge",
                            )
                        continue
                    # Multi-step plan: earlier tools ran but a later step was skipped.
                    if (
                        bool(agent_cfg.get("plan_progress", True))
                        and self._active_plan is not None
                        and not ctx.plan_progress_used
                        and not answer_looks_like_refusal(content)
                    ):
                        progress = plan_progress_notice(
                            self._active_plan,
                            self.tools_used,
                            available_tools=tool_names,
                        )
                        if progress:
                            ctx.plan_progress_used = True
                            await self._retract()
                            messages.append({"role": "assistant", "content": content})
                            messages.append({"role": "user", "content": progress})
                            await self.bus.publish(
                                Event(
                                    EventType.THINKING,
                                    {
                                        "text": (
                                            f"plan_progress  {self._active_plan.id}"
                                        )
                                    },
                                )
                            )
                            if self._timer is not None:
                                self._timer.mark(
                                    "plan_progress",
                                    plan=self._active_plan.id,
                                )
                            continue
                    if await apply_force_gates(
                        self,
                        ctx,
                        content,
                        refused=answer_looks_like_refusal(content),
                    ):
                        continue
                    # Exactness: contingent fact without a matching warrant.
                    if (
                        evidence_gate
                        and exact_need.kinds
                        and not ctx.evidence_nudge_used
                        and not answer_looks_like_refusal(content)
                    ):
                        missing = ledger.missing_kinds(exact_need.kinds)
                        # Math/weather have dedicated forces above.
                        missing = [
                            k for k in missing if k not in FORCE_GATE_KINDS
                        ]
                        if missing:
                            ctx.evidence_nudge_used = True
                            await self._retract()
                            messages.append({"role": "assistant", "content": content})
                            messages.append(
                                {"role": "user", "content": evidence_force_notice()}
                            )
                            await self.bus.publish(
                                Event(
                                    EventType.THINKING,
                                    {
                                        "text": (
                                            "phase=verify missing-warrants "
                                            + ",".join(missing)
                                        )
                                    },
                                )
                            )
                            if self._timer is not None:
                                self._timer.mark(
                                    "verify",
                                    gate="evidence",
                                    missing=",".join(missing),
                                )
                            continue
                    # File read succeeded but the model only acknowledged ("Got it,
                    # I'll keep that in mind") — force one real answer from the tool
                    # output instead of shipping the empty ack.
                    if (
                        not ctx.file_answer_nudge_used
                        and (self.tools_used & _FILE_ANSWER_TOOLS)
                        and answer_looks_like_ack_only(content)
                        and not answer_looks_like_refusal(content)
                    ):
                        ctx.file_answer_nudge_used = True
                        await self._retract()
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {"role": "user", "content": file_answer_force_notice()}
                        )
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "phase=verify file-answer"},
                            )
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "verify", gate="file_answer", action="nudge"
                            )
                        continue
                    # Perception: quote-first when web evidence exists.
                    if (
                        evidence_gate
                        and ledger.has_ok("web")
                        and not ctx.quote_nudge_used
                        and exact_need.needs_web_evidence
                        and not _answer_has_quote_span(content)
                        and not answer_looks_like_refusal(content)
                    ):
                        ctx.quote_nudge_used = True
                        await self._retract()
                        messages.append({"role": "assistant", "content": content})
                        quotes = ledger.quote_lines()
                        notice = quote_first_notice()
                        if quotes:
                            notice += "\nEvidence spans:\n" + "\n".join(quotes)
                        messages.append({"role": "user", "content": notice})
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "phase=verify quote-first"},
                            )
                        )
                        if self._timer is not None:
                            self._timer.mark("verify", gate="quote", action="nudge")
                        continue
                    # Research mode: prefer ≥research_min_sources hits. Nudge once when
                    # we already have one good page; soft-fail (answer from it) if a
                    # second source never lands — hard refuse only with zero warrants
                    # (R5 / S02 refuse-after-scrape paradox).
                    web_ok_n = len(ledger.ok_web_sources()) if ledger.has_ok("web") else 0
                    if (
                        research_dual
                        and research_mode
                        and exact_need.needs_web_evidence
                        and web_ok_n < research_min_sources
                        and not answer_looks_like_refusal(content)
                    ):
                        if not ctx.dual_hit_nudge_used and web_ok_n >= 1:
                            ctx.dual_hit_nudge_used = True
                            await self._retract()
                            messages.append({"role": "assistant", "content": content})
                            messages.append({"role": "user", "content": dual_hit_notice()})
                            await self.bus.publish(
                                Event(
                                    EventType.THINKING,
                                    {"text": "phase=verify dual-hit"},
                                )
                            )
                            if self._timer is not None:
                                self._timer.mark(
                                    "verify", gate="dual_hit", action="nudge"
                                )
                            continue
                        if web_ok_n == 0:
                            await self._retract()
                            thin = unsupported_exactness_reply(["web"])
                            if self._timer is not None:
                                self._timer.mark(
                                    "exactness",
                                    gate="research_min_sources",
                                    action="refuse",
                                    have=web_ok_n,
                                    need=research_min_sources,
                                )
                            # No Sources on refuse — empty list avoids cite-then-refuse.
                            await self._finish(thin, [], streamed="")
                            return
                        if ctx.dual_hit_nudge_used and web_ok_n >= 1:
                            if self._timer is not None:
                                self._timer.mark(
                                    "exactness",
                                    gate="dual_hit",
                                    action="soft_fail",
                                    have=web_ok_n,
                                    need=research_min_sources,
                                )
                            # Fall through: answer from the one good source.
                    # Reached only when force nudges above did not continue: refuse
                    # unsupported claims instead of shipping a soft second invent.
                    refuse = _exactness_finish_refuse(
                        content,
                        exact_need=ctx.exact_need,
                        ledger=ctx.ledger,
                        numeric_gate=ctx.numeric_gate,
                        evidence_gate=ctx.evidence_gate,
                        send_path=ctx.is_send_path(self._expected_tools),
                    )
                    if refuse is None:
                        refuse = self._look_refuse(content)
                    if refuse is not None:
                        await self._retract()
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "phase=verify refuse"},
                            )
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "verify",
                                gate="refuse",
                                kinds=",".join(exact_need.kinds),
                            )
                        await self._finish(refuse, sources, streamed="")
                        return
                    if self._timer is not None:
                        self._timer.mark(
                            "round",
                            n=round_i,
                            ms=round_ms,
                            kind="final",
                            calls=0,
                        )
                        if exact_need.kinds:
                            self._timer.mark(
                                "exactness",
                                gate="pass",
                                kinds=",".join(exact_need.kinds),
                                warrants=len(ledger),
                            )
                    await self._finish(content, sources, streamed=streamed)
                    return

            # The round was a tool call, so anything already painted was a
            # preamble rather than an answer. Take it off the screen and put it
            # in the thinking dock, which is where a model narrating itself
            # belongs.
            if self._timer is not None:
                self._timer.mark(
                    "round",
                    n=round_i,
                    ms=round_ms,
                    kind="tools",
                    calls=len(calls),
                )
            if streamed.strip():
                await self._retract()
                await self.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": f"preamble  {streamed.strip()[:_MAX_THINKING_SNIPPET]}"},
                    )
                )

            # Record the model's turn before the results, so the transcript
            # reads call-then-result. In fallback mode the JSON text itself is
            # the assistant turn: sending an empty message instead makes several
            # models re-issue the same call until max_rounds runs out.
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": content}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            fanout_results: dict[int, tuple[int, Any]] | None = None
            if (
                bool(agent_cfg.get("read_fanout", True))
                and should_fanout_reads(
                    calls,
                    tool_names=tool_names,
                    expected_tools=self._expected_tools,
                    tools=self.tools,
                    confirm_writes=self.confirm_writes,
                    confirm_image=self.confirm_image,
                    confirm_send=self.confirm_send,
                    confirm_browser=self.confirm_browser,
                    confirm_vision=self.confirm_vision,
                    allow_writes_this_turn=ctx.allow_writes_this_turn,
                    tools_used=self.tools_used,
                    web_search_ok=web_search_ok,
                )
            ):
                await self.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": f"phase=fanout n={len(calls)} independent reads"},
                    )
                )

                async def _fanout_one(
                    index: int, tool_name: str, tool_args: dict[str, Any]
                ) -> tuple[int, int, Any]:
                    started = time.perf_counter()
                    tool_result = await self.tools.call(tool_name, **tool_args)
                    elapsed = int((time.perf_counter() - started) * 1000)
                    return index, elapsed, tool_result

                gathered = await asyncio.gather(
                    *[
                        _fanout_one(index, tool_name, tool_args)
                        for index, (tool_name, tool_args) in enumerate(calls)
                    ]
                )
                fanout_results = {
                    index: (elapsed, tool_result)
                    for index, elapsed, tool_result in gathered
                }
                if self._timer is not None:
                    self._timer.mark("fanout", n=len(calls))

            call_i = -1

            def _drop_wander(*names: str, _offer_tools: bool = offer_tools) -> None:
                nonlocal available, visible, tool_names, ollama_tools
                hide = set(names)
                available = set(available) - hide
                visible = set(visible) - hide
                ctx.tool_names.clear()
                ctx.tool_names.update(visible)
                tool_names = ctx.tool_names
                if _offer_tools:
                    ollama_tools = self.tools.ollama_tools(visible)

            for name, args in calls:
                call_i += 1
                await self._hold_if_paused()

                if name not in tool_names:
                    daily_miss = (
                        (
                            name in _WEATHER_WANDER
                            and "weather" in self._expected_tools
                        )
                        or (
                            name in {
                                "web_search",
                                "contacts",
                                "user_location",
                                "weather",
                                "browser",
                                "scrape",
                                "web_fetch",
                            }
                            and "send_sms" in self._expected_tools
                        )
                        or (
                            name in {"web_search", "analyze"}
                            and "send_email" in self._expected_tools
                            and "analyze" not in self._expected_tools
                        )
                        or (
                            name in {
                                "web_search",
                                "contacts",
                                "user_location",
                                "weather",
                                "schedule",
                            }
                            and "agenda" in self._expected_tools
                        )
                        or (
                            name in _BROWSER_WANDER
                            and "browser" in self._expected_tools
                        )
                    )
                    if not daily_miss:
                        err = (
                            f"Unknown tool `{name}`. "
                            f"Available: {', '.join(sorted(tool_names))}"
                        )
                        if name in {"comfyui", "search_images", "generate_image"}:
                            err += (
                                ". Image generation is the `image` tool. There is "
                                "no start-ComfyUI tool and no stock-photo search; "
                                "start ComfyUI yourself or set tools.image.auto_start."
                            )
                        await self.bus.publish(
                            Event(EventType.THINKING, {"text": f"reject  {err}"})
                        )
                        messages.append(self._tool_message(name, err))
                        continue

                # Arguments from a different tool — a cancelled SMS draft
                # arriving as calculator(to=…, body=…). Tools take **kwargs and
                # read only the keys they know, so without this the call looks
                # like a silent miss and the model retries it.
                if name == "weather":
                    args = fill_weather_args(args, text)
                tool_obj = self.tools.get(name)
                cross = cross_tool_arg_error(
                    name,
                    args,
                    declared=schema_keys(
                        getattr(tool_obj, "parameters_schema", None)
                    )
                    if tool_obj is not None
                    else None,
                    strict=bool(agent_cfg.get("strict_tool_args", True)),
                )
                if cross is not None:
                    await self.bus.publish(
                        Event(EventType.THINKING, {"text": f"reject  {cross}"})
                    )
                    messages.append(self._tool_message(name, cross))
                    if self._timer is not None:
                        self._timer.mark(
                            "exactness", gate="cross_tool_args", action="reject"
                        )
                    continue

                # Weather ask: never run web_search/scrape/fetch; inject weather.
                if (
                    name in _WEATHER_WANDER
                    and bool(agent_cfg.get("weather_force_call", True))
                    and exact_need.needs_weather
                    and not looks_like_scheduled_send(text)
                    and not looks_like_schedule_manage(text)
                    and not ctx.schedule_managed_ok
                    and weather_places_missing(text, weather_ok_places)
                    and "weather" in tool_names
                ):
                    notice = (
                        "Blocked: this turn expects the weather tool, not "
                        f"{name}. Call weather now."
                    )
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": f"redirect  {name} → weather"},
                        )
                    )
                    messages.append(self._tool_message(name, notice))
                    _drop_wander(*_WEATHER_WANDER)
                    name = "weather"
                    args = draft_weather_args(text)
                    missing = weather_places_missing(text, weather_ok_places)
                    if missing:
                        if missing[0]:
                            args["place"] = missing[0]
                        else:
                            args.pop("place", None)
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  weather from intent"},
                        )
                    )
                    if self._timer is not None:
                        self._timer.mark(
                            "exactness",
                            gate="weather_redirect",
                            action="inject",
                        )
                    # Fall through to execute injected weather.

                elif (
                    name == "browser"
                    and looks_like_calendar_open(text)
                    and "agenda" in tool_names
                ):
                    notice = (
                        "Blocked: this turn expects the Arelis calendar tile, "
                        f"not {name}. Call agenda with action=open."
                    )
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "redirect  browser → agenda"},
                        )
                    )
                    messages.append(self._tool_message(name, notice))
                    name = "agenda"
                    args = {"action": "open"}
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  agenda open from intent"},
                        )
                    )
                    if self._timer is not None:
                        self._timer.mark(
                            "exactness",
                            gate="agenda_redirect",
                            action="inject",
                        )

                elif (
                    name == "browser"
                    and match_tile_intent(text)
                    and "tile" in tool_names
                ):
                    from arelis.tools.tile import TileTool

                    inj = tile_tool_args(text, last_name=TileTool.last_name)
                    if inj:
                        notice = (
                            "Blocked: this turn expects an Arelis tile, "
                            f"not {name}. Call tile with action="
                            f"{inj['action']} and name={inj['name']}."
                        )
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "redirect  browser → tile"},
                            )
                        )
                        messages.append(self._tool_message(name, notice))
                        name = "tile"
                        args = inj
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "inject  tile from intent"},
                            )
                        )

                # Browser drive: never run web_search/scrape; inject browser.
                elif (
                    name in _BROWSER_WANDER
                    and (
                        "browser" in self._expected_tools
                        or looks_like_browser_or_url(text)
                    )
                    and not looks_like_calendar_open(text)
                    and not looks_like_calendar_close(text)
                    and not match_tile_intent(text)
                    and "browser" not in self.tools_used
                    and "browser" in tool_names
                ):
                    inj = draft_browser_args(text)
                    notice = (
                        "Blocked: this turn expects the browser tool, not "
                        f"{name}. Call browser now."
                    )
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": f"redirect  {name} → browser"},
                        )
                    )
                    messages.append(self._tool_message(name, notice))
                    _drop_wander(*_BROWSER_WANDER)
                    name = "browser"
                    args = inj
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "inject  browser from intent"},
                        )
                    )
                    if self._timer is not None:
                        self._timer.mark(
                            "exactness",
                            gate="browser_redirect",
                            action="inject",
                        )

                # Local store ask: never run weather/search instead of tasks/goals.
                elif (
                    name
                    in {
                        "weather",
                        "web_search",
                        "browser",
                        "scrape",
                        "web_fetch",
                        "user_location",
                    }
                    and self._expected_tools & _LOCAL_STORE
                    and name not in self._expected_tools
                ):
                    target = next(
                        (
                            t
                            for t in ("tasks", "goals", "contacts", "memory")
                            if t in self._expected_tools and t in tool_names
                        ),
                        "",
                    )
                    if target and target not in self.tools_used:
                        notice = (
                            f"Blocked: this turn expects {target}, not {name}."
                        )
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": f"redirect  {name} → {target}"},
                            )
                        )
                        messages.append(self._tool_message(name, notice))
                        _drop_wander(
                            "weather",
                            "web_search",
                            "browser",
                            "scrape",
                            "web_fetch",
                            "user_location",
                        )
                        name = target
                        args = local_store_inject_args(
                            target,
                            text,
                            receipts=self._receipts,
                            history=self.memory.messages,
                        )
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": f"inject  {target} from intent"},
                            )
                        )

                # SMS ask: strip wander on first miss; inject when draft is complete.
                # contacts is wander only when the draft is already resolvable —
                # missing recipients (or a failed send) must be allowed to look up
                # or add a number instead of injecting the same bad card.
                elif (
                    (
                        should_redirect_wander_to_sms(
                            name,
                            self._expected_tools,
                            tools_used=self.tools_used,
                            sms_failed=ctx.sms_failed,
                        )
                        or (
                            name == "contacts"
                            and sms_draft is not None
                            and sms_draft.complete
                            and not sms_draft.missing
                            and not ctx.sms_failed
                        )
                    )
                    and "send_sms" in self._expected_tools
                    and "send_sms" not in self.tools_used
                    and not ctx.sms_failed
                ):
                    notice = (
                        "Blocked: this turn expects send_sms (or asking once "
                        f"for the message body), not {name}. Do not invent "
                        "a body. Call send_sms when to+body are known."
                    )
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": f"redirect  {name} → sms"},
                        )
                    )
                    messages.append(self._tool_message(name, notice))
                    _drop_wander(*_SMS_WANDER)
                    if (
                        sms_draft is not None
                        and sms_draft.complete
                        and "send_sms" in tool_names
                    ):
                        inj = draft_send_sms_args(
                            sms_draft, already_sent=sms_sent
                        )
                        name = "send_sms"
                        args = inj
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "inject  send_sms from draft"},
                            )
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "exactness",
                                gate="sms_redirect",
                                action="inject",
                            )
                        # Fall through to execute injected send_sms.
                    else:
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "The user wants to send a text. If the body is "
                                    "missing, ask once what to say. If to and body "
                                    "are known, call send_sms. Do not web_search."
                                ),
                            }
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "exactness",
                                gate="sms_redirect",
                                action="block",
                            )
                        continue

                # Email compose: block web_search/analyze; inject complete draft.
                elif (
                    name in {"web_search", "analyze"}
                    and "send_email" in self._expected_tools
                    and "send_email" not in self.tools_used
                    and "analyze" not in self._expected_tools
                ):
                    notice = (
                        "Blocked: this turn expects send_email, not "
                        f"{name}. Use the literal address the user gave."
                    )
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": f"redirect  {name} → email"},
                        )
                    )
                    messages.append(self._tool_message(name, notice))
                    _drop_wander("web_search")
                    if (
                        email_draft is not None
                        and email_draft.complete
                        and "send_email" in tool_names
                    ):
                        name = "send_email"
                        args = draft_send_email_args(email_draft)
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "inject  send_email from draft"},
                            )
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "exactness",
                                gate="email_redirect",
                                action="inject",
                            )
                    else:
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "Call send_email with the address and body "
                                    "the user gave. Do not web_search."
                                ),
                            }
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "exactness",
                                gate="email_redirect",
                                action="block",
                            )
                        continue

                # Calendar: block wander; inject create or delete on first miss.
                elif (
                    name in {
                        "web_search",
                        "contacts",
                        "user_location",
                        "weather",
                        "schedule",
                    }
                    and "agenda" in self._expected_tools
                    and not ctx.agenda_create_ok
                ):
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": f"redirect  {name} → agenda"},
                        )
                    )
                    messages.append(
                        self._tool_message(
                            name,
                            "Blocked: this turn expects agenda, not "
                            f"{name}. Call agenda (open, close, list, create, or delete).",
                        )
                    )
                    _drop_wander(
                        "web_search",
                        "contacts",
                        "user_location",
                        "weather",
                        "schedule",
                    )
                    if (
                        looks_like_calendar_delete(text)
                        and "agenda" in tool_names
                    ):
                        inj = draft_agenda_delete_args(
                            text,
                            receipts=self._receipts,
                            history=self.memory.messages,
                        )
                        name = "agenda"
                        args = inj
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "inject  agenda delete"},
                            )
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "exactness",
                                gate="agenda_redirect",
                                action="inject",
                            )
                    elif (
                        agenda_draft is not None
                        and agenda_draft.complete
                        and "agenda" in tool_names
                    ):
                        name = "agenda"
                        args = draft_agenda_create_args(agenda_draft)
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "inject  agenda create from draft"},
                            )
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "exactness",
                                gate="agenda_redirect",
                                action="inject",
                            )
                    elif looks_like_calendar_close(text) and "agenda" in tool_names:
                        name = "agenda"
                        args = {"action": "close"}
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "inject  agenda close from intent"},
                            )
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "exactness",
                                gate="agenda_redirect",
                                action="inject",
                            )
                    elif looks_like_calendar_open(text) and "agenda" in tool_names:
                        name = "agenda"
                        args = {"action": "open"}
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "inject  agenda open from intent"},
                            )
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "exactness",
                                gate="agenda_redirect",
                                action="inject",
                            )
                    elif looks_like_calendar_read(text) and "agenda" in tool_names:
                        name = "agenda"
                        args = {"action": agenda_read_action(text)}
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": "inject  agenda read from intent"},
                            )
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "exactness",
                                gate="agenda_redirect",
                                action="inject",
                            )
                    else:
                        messages.append(
                            {
                                "role": "user",
                                "content": agenda_force_call_notice(agenda_draft)
                                if agenda_draft is not None and agenda_draft.complete
                                else (
                                    "Call agenda with action=open, close, today, "
                                    "tomorrow, list, create, or delete. Do not "
                                    "web_search."
                                ),
                            }
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "exactness",
                                gate="agenda_redirect",
                                action="block",
                            )
                        continue

                # After a successful SMS this turn, do not web_search contacts.
                if (
                    name == "web_search"
                    and sms_sent
                    and "send_sms" in self.tools_used
                ):
                    notice = (
                        "Blocked: SMS already sent this turn. Do not web_search "
                        "for the recipient. Answer the user and stop."
                    )
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": "redirect  web_search → stop (sms done)"},
                        )
                    )
                    messages.append(self._tool_message(name, notice))
                    continue

                # A known contact is already in contacts.yaml — never search
                # the public web for their phone/email/identity.
                if name == "web_search":
                    hit = web_search_targets_known_contact(
                        str(args.get("query") or "")
                    )
                    if hit is not None:
                        notice = (
                            f"Blocked: {hit.display_name} is already in the "
                            f"contacts book (alias `{hit.alias}`). Use the "
                            "contacts tool or send_sms. Do not search the "
                            "public web for them."
                        )
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        f"redirect  web_search → contacts "
                                        f"({hit.alias})"
                                    )
                                },
                            )
                        )
                        messages.append(self._tool_message(name, notice))
                        continue

                if name == "send_sms":
                    args = fill_send_sms_args(
                        args, sms_draft, already_sent=sms_sent
                    ) if sms_draft is not None else fill_send_sms_args(args, None)
                    to_arg = str(args.get("to") or "").strip()
                    if to_arg and to_arg.lower() in {s.lower() for s in sms_sent}:
                        notice = (
                            f"Already sent SMS to {to_arg} earlier this turn; "
                            "not sending a duplicate."
                        )
                        await self.bus.publish(
                            Event(EventType.THINKING, {"text": f"skip  {notice}"})
                        )
                        messages.append(self._tool_message(name, notice))
                        self._trace.append(f"{name} duplicate send blocked")
                        continue
                    # Block junk follow-up bodies after a locked draft send.
                    if (
                        sms_draft is not None
                        and sms_draft.complete
                        and sms_sent
                        and str(args.get("body") or "").strip()
                        and str(args.get("body") or "").strip() != sms_draft.body
                    ):
                        notice = (
                            "Already sent the drafted SMS this turn; not sending "
                            "a different follow-up body."
                        )
                        await self.bus.publish(
                            Event(EventType.THINKING, {"text": f"skip  {notice}"})
                        )
                        messages.append(self._tool_message(name, notice))
                        self._trace.append(f"{name} extra body blocked")
                        continue
                if name == "send_email" and email_draft is not None:
                    args = fill_send_email_args(args, email_draft)
                    if "send_email" in self.tools_used:
                        notice = (
                            "Already sent this email earlier this turn; "
                            "not sending a duplicate."
                        )
                        await self.bus.publish(
                            Event(EventType.THINKING, {"text": f"skip  {notice}"})
                        )
                        messages.append(self._tool_message(name, notice))
                        self._trace.append(f"{name} duplicate send blocked")
                        continue
                if name == "memory":
                    if str(args.get("action") or "").strip().lower() == "forget":
                        args = lock_memory_forget_args(args, text)

                if name == "agenda":
                    if agenda_draft is not None:
                        args = fill_agenda_args(args, agenda_draft)
                    else:
                        args = fill_agenda_args(args, None)
                    if str(args.get("action") or "").strip().lower() == "delete":
                        args = lock_agenda_delete_args(
                            args,
                            text,
                            receipts=self._receipts,
                            history=self.memory.messages,
                        )
                    if str(args.get("action") or "").strip().lower() == "create":
                        create_fp = (
                            f"{str(args.get('provider') or '').strip().lower()}|"
                            f"{str(args.get('summary') or '').strip().casefold()}|"
                            f"{str(args.get('start') or '').strip()}"
                        )
                        if create_fp in agenda_created:
                            notice = (
                                "Already created this event earlier in the turn "
                                f"({args.get('summary')} @ {args.get('start')}); "
                                "not creating a duplicate."
                            )
                            await self.bus.publish(
                                Event(EventType.THINKING, {"text": f"skip  {notice}"})
                            )
                            messages.append(self._tool_message(name, notice))
                            self._trace.append(f"{name} duplicate create blocked")
                            continue

                if name == "vision":
                    args = fill_vision_args(
                        args,
                        history=self.memory.messages,
                        user_text=text,
                    )
                    if self._look is not None:
                        args["question"] = vision_question(
                            self._look.intent, text
                        )
                        if self._look.path and not str(args.get("path") or "").strip():
                            args["path"] = self._look.path

                if name == "inbox":
                    inbox = self.tools.get("inbox")
                    hits = getattr(inbox, "last_hits", None) if inbox is not None else None
                    args = fill_inbox_args(
                        args,
                        user_text=text,
                        last_hits=hits if isinstance(hits, list) else None,
                    )

                if name == "document":
                    room_kind = ""
                    if active_room is not None:
                        room_kind = str(active_room.kind or "")
                    args = fill_document_args(
                        args,
                        user_text=text,
                        history=self.memory.messages,
                        receipts=self._receipts,
                        room_kind=room_kind,
                    )

                if name == "doc_extract":
                    args = fill_doc_extract_args(
                        args,
                        user_text=text,
                        history=self.memory.messages,
                        receipts=self._receipts,
                    )

                if self._look is not None:
                    blocked_look = look_call_blocked(name, args)
                    if blocked_look:
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": f"look grant block  {name}"},
                            )
                        )
                        messages.append(self._tool_message(name, blocked_look))
                        self._trace.append(f"{name} look_grant_blocked")
                        continue
                    if name == "camera" and self._look.camera_snaps >= 1:
                        notice = (
                            "Already captured one still this look; not "
                            "snapshotting again. Answer from the SeeRecord."
                        )
                        messages.append(self._tool_message(name, notice))
                        self._trace.append("camera look_cap")
                        continue

                # One successful weather fetch per place — otherwise the 7B
                # re-calls weather until max_rounds (83s of duplicate Open-Meteo).
                if name == "weather":
                    wx_key = weather_place_key(str(args.get("place") or ""))
                    if wx_key in weather_ok_places:
                        notice = (
                            "Already fetched weather for that place this turn; "
                            "not calling it again. Answer the user from the "
                            "prior weather result in plain prose and stop, or "
                            "call weather for a city you have not fetched yet."
                        )
                        await self.bus.publish(
                            Event(EventType.THINKING, {"text": f"skip  {notice}"})
                        )
                        messages.append(self._tool_message(name, notice))
                        self._trace.append(f"{name} duplicate fetch blocked")
                        continue

                if name == "web_search":
                    q = str(args.get("query") or "").strip().casefold()
                    if q and q in web_search_ok:
                        notice = (
                            "Already ran web_search with that query this turn; "
                            "not searching again. Answer from the prior result "
                            "or change the query."
                        )
                        await self.bus.publish(
                            Event(EventType.THINKING, {"text": f"skip  {notice}"})
                        )
                        messages.append(self._tool_message(name, notice))
                        self._trace.append(f"{name} duplicate query blocked")
                        continue

                # One successful image per turn — otherwise the 7B re-opens Allow.
                if name == "image" and "image" in self.tools_used:
                    notice = (
                        "Already generated an image this turn; not generating "
                        "another. Tell the user the saved path from the prior "
                        "image result and stop."
                    )
                    await self.bus.publish(
                        Event(EventType.THINKING, {"text": f"skip  {notice}"})
                    )
                    messages.append(self._tool_message(name, notice))
                    self._trace.append(f"{name} duplicate generate blocked")
                    continue

                blocked = confirm_args_blocked(name, args)
                if blocked:
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": f"phase=confirm blocked  {blocked}"},
                        )
                    )
                    messages.append(self._tool_message(name, f"[fail:other] {blocked}"))
                    self._trace.append(f"{name} blocked: {blocked}")
                    continue

                call_fp = _tool_fail_fingerprint(name, args)
                if fail_counts.get(call_fp, 0) >= 2:
                    notice = (
                        f"[fail:other] Already failed twice with the same "
                        f"{name} arguments this turn; not asking Allow again. "
                        "Change the args or stop."
                    )
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": f"phase=confirm skip_repeat_fail  {name}"},
                        )
                    )
                    messages.append(self._tool_message(name, notice))
                    self._trace.append(f"{name} skip_repeat_fail")
                    # Drop the tool from the remaining offer so the 7B cannot
                    # burn every round on the same dead call.
                    if name in tool_names:
                        visible = {t for t in tool_names if t != name}
                        ctx.tool_names.clear()
                        ctx.tool_names.update(visible)
                        tool_names = ctx.tool_names
                        ollama_tools = (
                            self.tools.ollama_tools(visible)
                            if offer_tools and visible
                            else []
                        )
                    stop_msg = (
                        f"Stop calling `{name}` with those same arguments — it "
                        "already failed twice this turn."
                    )
                    if (
                        "weather" in self._expected_tools
                        and "weather" in tool_names
                        and "weather" not in self.tools_used
                    ):
                        stop_msg += (
                            " Call the weather tool for the forecast instead."
                        )
                    else:
                        stop_msg += (
                            " Use a different tool or answer from what you have."
                        )
                    messages.append({"role": "user", "content": stop_msg})
                    if self._timer is not None:
                        self._timer.mark(
                            "skip_repeat_fail", tool=name, action="drop_tool"
                        )
                    continue

                needs = self.tools.needs_confirm(
                    name,
                    args,
                    # "allow writes this turn" covers images/files/browser/vision.
                    # It deliberately does not cover mail/SMS (confirm_send) or
                    # calendar mutates (agenda create/update/delete) — those
                    # stay one Allow each.
                    confirm_writes=self.confirm_writes
                    and (not ctx.allow_writes_this_turn or name == "agenda"),
                    confirm_image=self.confirm_image and not ctx.allow_writes_this_turn,
                    confirm_send=self.confirm_send,
                    confirm_browser=self.confirm_browser
                    and not ctx.allow_writes_this_turn,
                    confirm_vision=self.confirm_vision
                    and not ctx.allow_writes_this_turn,
                )
                if name == "browser" and user_asked_for_browser(text):
                    needs = False
                if (
                    self._look is not None
                    and name in {"ocr", "vision"}
                    and self._look.grant_minted
                ):
                    needs = False
                if (
                    self._look is not None
                    and name in {"ocr", "vision"}
                    and not needs
                ):
                    self._look.grant_minted = True

                summary = self.tools.summarize_call(name, args)
                if self._look is not None and name in {"ocr", "vision"}:
                    look_path = str(args.get("path") or self._look.path or "")
                    summary = (
                        f"look ({self._look.intent.act}) at {look_path} — "
                        "one still, no further actions"
                    )
                if needs:
                    confirm_id = uuid4().hex
                    confirm_t0 = time.perf_counter()
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": f"phase=confirm waiting Allow for {name}"},
                        )
                    )
                    # Heartbeat while the card is open (L10) so wall-clock wait
                    # is not mistaken for a hung model.
                    heartbeat = asyncio.create_task(
                        self._confirm_wait_heartbeat(name, confirm_t0)
                    )
                    try:
                        decision = await self.request_confirm(
                            confirm_id, name, args, summary
                        )
                    finally:
                        heartbeat.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await heartbeat
                    confirm_ms = int((time.perf_counter() - confirm_t0) * 1000)
                    if self._timer is not None:
                        self._timer.confirm_ms += confirm_ms
                        self._timer.mark(
                            "confirm",
                            tool=name,
                            ms=confirm_ms,
                            decision=decision,
                        )
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    f"phase=confirm ms={confirm_ms} "
                                    f"decision={decision}"
                                )
                            },
                        )
                    )
                    if decision == "allow_turn":
                        ctx.allow_writes_this_turn = True
                        decision = "allow"
                    if decision != "allow":
                        await self.bus.publish(
                            Event(EventType.THINKING, {"text": f"skip  {summary}"})
                        )
                        skip_counts[call_fp] = skip_counts.get(call_fp, 0) + 1
                        drop = (
                            name not in self._expected_tools
                            or skip_counts[call_fp] >= 2
                        )
                        if drop:
                            notice = (
                                f"The user declined `{name}` and it is not "
                                "available for the rest of this turn. Do not "
                                "call it again."
                            )
                            if (
                                "send_sms" in self._expected_tools
                                and name != "send_sms"
                            ):
                                notice += (
                                    " If to and body are known, call send_sms."
                                )
                            elif (
                                "send_email" in self._expected_tools
                                and name != "send_email"
                            ):
                                notice += (
                                    " Call send_email if the draft is complete."
                                )
                            messages.append(self._tool_message(name, notice))
                            _drop_wander(name)
                            self._trace.append(f"{name} skipped and dropped")
                            if self._timer is not None:
                                self._timer.mark(
                                    "skip_drop", tool=name, action="drop_tool"
                                )
                        else:
                            messages.append(
                                self._tool_message(
                                    name, _SKIP_NOTICE.format(tool=name)
                                )
                            )
                            self._trace.append(f"{name} declined by user")
                        if (
                            name in {"send_sms", "send_email"}
                            and name in self._expected_tools
                        ):
                            ctx.skip_finish_text = "Okay — I did not send that."
                            break
                        continue
                    if self._look is not None and name in {"ocr", "vision"}:
                        self._look.grant_minted = True
                        self._look.allow_count = 1

                await self.bus.publish(Event(EventType.TOOL_START, {"tool": name, "args": args}))
                if self._look is not None and name == "vision":
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {"text": LOOKING_STATUS},
                        )
                    )
                await self.bus.publish(
                    Event(
                        EventType.THINKING,
                        {"text": f"round {round_i}/{self.max_rounds}  tool  {summary}"},
                    )
                )
                if name == "image":
                    ctx.image_attempted = True
                if fanout_results is not None:
                    ms, result = fanout_results[call_i]
                else:
                    t0 = time.perf_counter()
                    result = await self.tools.call(name, **args)
                    ms = int((time.perf_counter() - t0) * 1000)
                if self._timer is not None:
                    self._timer.tool_ms += ms
                    self._timer.tools.append(name)
                    tool_fields: dict[str, Any] = {
                        "name": name,
                        "ms": ms,
                        "ok": result.ok,
                    }
                    action = str(args.get("action") or "").strip()
                    if action:
                        tool_fields["action"] = action
                    self._timer.mark("tool", **tool_fields)
                data_dict = result.data if isinstance(result.data, dict) else None
                if name in {"scrape", "web_fetch"} and not result.ok:
                    tag = ""
                    if isinstance(data_dict, dict):
                        tag = str(data_dict.get("fail_class") or "")
                    if not tag:
                        tag = classify_fetch_failure(str(result.output or ""))
                    if tag == "fail:js_shell":
                        url = ""
                        if isinstance(data_dict, dict):
                            url = str(data_dict.get("url") or "").strip()
                        if not url.startswith("http"):
                            url = str(args.get("url") or "").strip()
                        if url.startswith("http"):
                            ctx.js_shell_url = url
                            if "browser" in available_all:
                                visible = set(visible) | {"browser"}
                                available = set(available) | {"browser"}
                                ctx.tool_names.clear()
                                ctx.tool_names.update(visible)
                                tool_names = ctx.tool_names
                                if offer_tools:
                                    ollama_tools = self.tools.ollama_tools(visible)
                if result.ok:
                    self.tools_used.add(name)
                    fail_counts.pop(call_fp, None)
                    ctx.last_ok_tool_out = str(result.output or "")
                    ctx.last_ok_tool_name = name
                    if name == "inbox" and str(args.get("action") or "").lower() in {
                        "trash",
                        "archive",
                        "delete",
                    }:
                        ctx.inbox_mutated_ok = True
                    if name == "browser":
                        b_act = str(args.get("action") or "").strip().lower()
                        if b_act == "snapshot":
                            ctx.last_browser_snapshot = str(result.output or "")
                        if b_act == "click":
                            ctx.browser_clicked = True
                    if name == "web_search":
                        q = str(args.get("query") or "").strip().casefold()
                        if q:
                            web_search_ok.add(q)
                    if name == "send_sms":
                        sent_to = str(args.get("to") or "").strip()
                        if sent_to:
                            sms_sent.add(sent_to)
                    if name == "send_email":
                        ctx.email_sent_ok = True
                    if name == "agenda" and str(args.get("action") or "").lower() == "create":
                        agenda_created.add(
                            f"{str(args.get('provider') or '').strip().lower()}|"
                            f"{str(args.get('summary') or '').strip().casefold()}|"
                            f"{str(args.get('start') or '').strip()}"
                        )
                        ctx.agenda_create_ok = True
                    if self._look is not None:
                        self._note_look_tool(name, args, result, data_dict)
                else:
                    fail_counts[call_fp] = fail_counts.get(call_fp, 0) + 1
                    if name == "send_sms":
                        ctx.sms_failed = True
                    if self._look is not None and name == "camera":
                        self._look.camera_snaps += 1
                if (not result.ok) and (
                    name == "browser"
                    and data_dict
                    and str(data_dict.get("code") or "") == "PROFILE_LOCKED"
                ):
                    # Attempted browser counts for routing_gap (R9).
                    self.tools_used.add(name)
                resolved = None
                if data_dict:
                    resolved = data_dict.get("abs_path") or data_dict.get("path")
                if name == "browser" and data_dict:
                    mode = str(data_dict.get("mode") or "").strip()
                    code = str(data_dict.get("code") or "").strip()
                    bits = ["browser"]
                    if mode:
                        bits.append(mode)
                    if code:
                        bits.append(code)
                    action = str(args.get("action") or "").strip()
                    if action:
                        bits.append(action)
                    await self.bus.publish(
                        Event(EventType.THINKING, {"text": "  ".join(bits)})
                    )
                    if (
                        code
                        in {
                            "PROFILE_LOCKED",
                            "RELAUNCH_FAILED",
                            "CDP_TIMEOUT",
                            "CDP_DEAD",
                        }
                        and not ctx.browser_relaunch_nudge_used
                        and bool(agent_cfg.get("browser_relaunch_force", True))
                    ):
                        ctx.browser_relaunch_nudge_used = True
                        pending_url = str(
                            args.get("url") or args.get("target") or ""
                        ).strip()
                        url_bit = (
                            f", url={pending_url!r}" if pending_url else ""
                        )
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "Browser connect/control failed "
                                    f"({code}). If the user only asked to "
                                    "pull up a site, call browser(action=open"
                                    f"{url_bit}) — that is a plain OS open "
                                    "(no Chrome restart). For click/snapshot/"
                                    "navigate when CDP is down, call "
                                    f"browser(action=relaunch{url_bit}) after "
                                    "Allow, or ask them to close extra Chrome "
                                    "windows. Do not screenshot until connected."
                                ),
                            }
                        )
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {
                                    "text": (
                                        f"browser {code}; one-shot "
                                        "relaunch-then-open nudge"
                                    )
                                },
                            )
                        )
                        if self._timer is not None:
                            self._timer.mark(
                                "exactness", gate="browser_relaunch", action="nudge"
                            )
                self._trace.append(
                    tool_trace_entry(name, args, result.ok, resolved_path=resolved)
                )
                ledger.record_tool(
                    name,
                    ok=result.ok,
                    output=str(result.output or ""),
                    data=data_dict,
                    args=args if isinstance(args, dict) else None,
                )
                receipt = action_receipt(
                    name,
                    ok=result.ok,
                    args=args if isinstance(args, dict) else None,
                    data=data_dict,
                )
                if self._look is not None and name in {"vision", "ocr", "camera"}:
                    receipt = None
                    self._emit_look_receipt_if_ready()
                if receipt is not None:
                    self._receipts.append(receipt)
                    receipt_line = format_action_receipt(receipt)
                    self._trace.append(receipt_line)
                    if self._timer is not None:
                        self._timer.mark(
                            "receipt",
                            action=str(receipt.get("action") or name),
                            ok=True,
                        )
                    await self.bus.publish(
                        Event(EventType.THINKING, {"text": receipt_line})
                    )
                    session_id = None
                    sink = getattr(self.memory, "sink", None)
                    if sink is not None:
                        session_id = getattr(sink, "session_id", None)
                    append_action_ledger(receipt, session_id=session_id)

                if (
                    name in {"web_fetch", "scrape"}
                    or (
                        name == "browser"
                        and result.ok
                        and str(args.get("action") or "").strip().lower() == "read"
                    )
                ) and result.ok:
                    url = str(
                        (data_dict or {}).get("url") or args.get("url") or ""
                    ).strip()
                    if (
                        (url.startswith("http://") or url.startswith("https://"))
                        and all(url != known for _, known in sources)
                    ):
                        title = str((data_dict or {}).get("title") or "").strip()
                        sources.append((title, url))
                if name == "research_report" and result.ok and data_dict:
                    for item in data_dict.get("sources") or []:
                        if not isinstance(item, dict):
                            continue
                        url = str(item.get("url") or "").strip()
                        if not (
                            url.startswith("http://") or url.startswith("https://")
                        ):
                            continue
                        if any(url == known for _, known in sources):
                            continue
                        title = str(item.get("title") or "").strip()
                        sources.append((title, url))

                # Redact → optional fat-tool summary card → hard char cap.
                redacted = redact_secrets(result.output)
                if bool(agent_cfg.get("tool_summary_inject", True)):
                    prepared = prepare_tool_output(
                        name,
                        redacted,
                        data=data_dict,
                        max_inject_chars=min(self.tool_output_chars, 4000),
                        force=False,
                    )
                else:
                    prepared = PreparedToolOutput(
                        inject=redacted,
                        full_ref=None,
                        summarized=False,
                        original_chars=len(redacted),
                    )
                if prepared.summarized:
                    if self._timer is not None:
                        self._timer.mark(
                            "tool_summary",
                            tool=name,
                            orig=prepared.original_chars,
                            ref=prepared.full_ref or "-",
                        )
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    f"tool_summary  {name}  "
                                    f"{prepared.original_chars} chars → card"
                                    + (
                                        f"  ref={prepared.full_ref}"
                                        if prepared.full_ref
                                        else ""
                                    )
                                )
                            },
                        )
                    )
                    if data_dict is not None and prepared.full_ref:
                        data_dict = {**data_dict, "full_ref": prepared.full_ref}
                out, trunc = truncate_tool_output(
                    prepared.inject, self.tool_output_chars
                )
                out = frame_external_tool_output(
                    name,
                    out,
                    action=str(args.get("action") or "")
                    if isinstance(args, dict)
                    else "",
                )
                if (
                    self._look is not None
                    and name in {"ocr", "vision"}
                    and self._look.record is not None
                    and result.ok
                ):
                    out = f"{out}\n\n{format_see_record(self._look.record)}"
                if trunc.truncated:
                    if self._timer is not None:
                        self._timer.mark(
                            "truncate",
                            tool=name,
                            orig=trunc.original_chars,
                            kept=trunc.kept_chars,
                        )
                    await self.bus.publish(
                        Event(
                            EventType.THINKING,
                            {
                                "text": (
                                    f"truncated  {name}  "
                                    f"{trunc.original_chars}->{trunc.kept_chars} chars"
                                )
                            },
                        )
                    )
                await self.bus.publish(
                    Event(
                        EventType.TOOL_RESULT,
                        {
                            "tool": name,
                            "ok": result.ok,
                            "output": out,
                            "data": result.data,
                            "truncated": trunc.truncated,
                            "original_chars": trunc.original_chars,
                            "kept_chars": trunc.kept_chars,
                        },
                    )
                )
                if name == "browser" and data_dict:
                    wall_code = str(data_dict.get("code") or "")
                    if wall_code in {"YOUR_TURN", "SECRET_FIELD"}:
                        await self.bus.publish(
                            Event(
                                EventType.TURN_PAUSE,
                                {
                                    "reason": "your_turn",
                                    "kind": str(
                                        data_dict.get("wall")
                                        or ("login" if wall_code == "SECRET_FIELD" else "")
                                    ),
                                },
                            )
                        )
                        await self._await_your_turn(
                            str(data_dict.get("wall") or "")
                        )
                await self.bus.publish(
                    Event(
                        EventType.THINKING,
                        {
                            "text": (
                                f"round {round_i}/{self.max_rounds}  "
                                f"{'ok' if result.ok else 'fail'}  {name}  {ms}ms"
                            )
                        },
                    )
                )
                if (
                    name in {"image", "image_edit"}
                    and result.ok
                    and data_dict
                    and data_dict.get("path")
                ):
                    await self.bus.publish(
                        Event(EventType.IMAGE_READY, {"path": data_dict["path"]})
                    )
                    # Finish now — otherwise the 7B often re-calls image and
                    # spams Allow (same class of bug as double-SMS). image_edit
                    # joins it because the round after a finished edit is where
                    # she reached for vision to check her own work and then the
                    # calculator to verify the pixel count.
                    path = str(data_dict["path"])
                    if name == "image_edit":
                        # Its own sentence already names the sizes and the
                        # adjustments, which is the part worth reading.
                        await self._finish(str(result.output).strip(), sources, streamed="")
                        return
                    await self._finish(
                        f"Image ready — open in Workspace ({path}).",
                        sources,
                        streamed="",
                    )
                    return
                if (
                    name in {"document", "plot"}
                    and result.ok
                    and data_dict
                    and data_dict.get("abs_path")
                ):
                    await self.bus.publish(
                        Event(
                            EventType.FILE_READY,
                            {
                                "path": str(data_dict.get("path") or ""),
                                "abs_path": str(data_dict.get("abs_path") or ""),
                                "format": str(data_dict.get("format") or ""),
                                "title": str(data_dict.get("title") or ""),
                                "show_card": True,
                                "open": False,
                            },
                        )
                    )
                if (
                    name == "schedule"
                    and result.ok
                    and str(args.get("action") or "").lower()
                    in {"create", "create_briefing"}
                ):
                    # Keep [job.id] in the transcript. The 7B otherwise
                    # paraphrases the tool output and the id vanishes.
                    await self._finish(str(result.output).strip(), sources, streamed="")
                    return
                messages.append(self._tool_message(name, out))
                if (
                    name == "schedule"
                    and result.ok
                    and str(args.get("action") or "").lower() in {"list", "delete"}
                ):
                    ctx.schedule_managed_ok = True
                # Successful weather → answer from it; do not re-fetch all round.
                # days=1 is today only; if they asked tomorrow, one retry with
                # days=3. fill_weather_args usually bumps that before the call.
                # Two named cities are two readings; lock per place, not the tool.
                if name == "weather" and result.ok:
                    used_days = 3
                    try:
                        used_days = int(args.get("days") or 3)
                    except (TypeError, ValueError):
                        used_days = 3
                    wx_key = weather_place_key(str(args.get("place") or ""))
                    retry_days = (
                        used_days < 2
                        and weather_wants_beyond_today(text)
                        and wx_key not in weather_days_retried
                    )
                    if retry_days:
                        weather_days_retried.add(wx_key)
                        keep_place = str(args.get("place") or "").strip()
                        retry_msg = (
                            "That reading is today only. Call weather "
                            "again with days=3 (keep place if you used "
                            "one). Then answer the user from that."
                        )
                        if keep_place:
                            retry_msg = (
                                "That reading is today only. Call weather "
                                f"again with days=3 and place={keep_place}. "
                                "Then answer the user from that."
                            )
                        messages.append(
                            {
                                "role": "user",
                                "content": retry_msg,
                            }
                        )
                    else:
                        weather_ok_places.add(wx_key)
                        missing = weather_places_missing(text, weather_ok_places)
                        if missing:
                            nxt = missing[0]
                            if nxt:
                                more_msg = (
                                    "You already have a successful weather "
                                    f"reading this turn. Call weather now with "
                                    f"place={nxt} and days=3 for the other city. "
                                    "Then answer from every reading. Do not "
                                    "skip a named city."
                                )
                            else:
                                more_msg = (
                                    "You already have a successful weather "
                                    "reading this turn. Call weather now "
                                    "without place for the user's own location. "
                                    "Then answer from every reading."
                                )
                            messages.append(
                                {"role": "user", "content": more_msg}
                            )
                        else:
                            if "weather" in tool_names:
                                visible = {t for t in tool_names if t != "weather"}
                                ctx.tool_names.clear()
                                ctx.tool_names.update(visible)
                                tool_names = ctx.tool_names
                                ollama_tools = (
                                    self.tools.ollama_tools(visible)
                                    if offer_tools and visible
                                    else []
                                )
                            messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        "You already have a successful weather tool "
                                        "result this turn. Answer the user now in plain "
                                        "prose from that reading. Do not call weather "
                                        "again."
                                    ),
                                }
                            )
                    if self._timer is not None:
                        self._timer.mark(
                            "weather_once",
                            action=(
                                "retry_days"
                                if retry_days
                                else (
                                    "need_place"
                                    if weather_places_missing(text, weather_ok_places)
                                    else "answer_now"
                                )
                            ),
                        )
                # Successful SMS to every draft recipient → confirm and stop.
                # Otherwise the model re-opens Allow and double-texts.
                if (
                    name == "send_sms"
                    and result.ok
                    and sms_draft is not None
                    and sms_draft.complete
                ):
                    sent_l = {s.lower() for s in sms_sent}
                    still = [
                        a
                        for a in (sms_draft.resolved_aliases or sms_draft.all_tos)
                        if a and a.lower() not in sent_l
                    ]
                    if not still:
                        who = ", ".join(sms_draft.all_tos) or "them"
                        await self._finish(
                            f"Sent your text to {who}.",
                            sources,
                            streamed="",
                        )
                        return
                if (
                    name == "send_email"
                    and result.ok
                    and email_draft is not None
                    and email_draft.complete
                ):
                    who = email_draft.tool_to or email_draft.to or "them"
                    await self._finish(
                        f"Sent email to {who}.",
                        sources,
                        streamed="",
                    )
                    return
                if (
                    name == "contacts"
                    and result.ok
                    and "send_sms" not in self._expected_tools
                    and (
                        looks_like_contacts_utterance(text)
                        or looks_like_contacts_followup(
                            text, self.memory.messages
                        )
                        or "contacts" in self._expected_tools
                    )
                ):
                    data = result.data if isinstance(result.data, dict) else {}
                    if looks_like_contact_phone_ask(text):
                        field = "phone"
                    elif looks_like_contact_email_ask(text):
                        field = "email"
                    else:
                        field = "who"
                    spoken = format_contact_spoken(data, field=field)
                    await self._finish(
                        spoken or out.strip() or "No contact matched.",
                        sources,
                        streamed="",
                    )
                    return
                # A store listing is already the answer, so handing it back beats
                # letting the 7B paraphrase a list it will pad. Only once nothing
                # else is outstanding, though: "what are my deadlines? pack my
                # week" expects tasks *and* agenda, and finishing on tasks meant
                # the calendar half of the ask was silently dropped.
                if (
                    name in {"tasks", "goals"}
                    and result.ok
                    and name in self._expected_tools
                    and not (self._expected_tools - self.tools_used - {name})
                ):
                    await self._finish(
                        out.strip() or f"{name} done.",
                        sources,
                        streamed="",
                    )
                    return
                if (
                    name == "agenda"
                    and result.ok
                    and looks_like_calendar_delete(text)
                    and str(args.get("action") or "").strip().lower() == "delete"
                ):
                    await self._finish(
                        out.strip() or "Calendar delete finished.",
                        sources,
                        streamed="",
                    )
                    return
                if (
                    not result.ok
                    and not self._fail_replan_used
                ):
                    replan = tool_fail_replan_notice(
                        name, redacted, ok=False
                    )
                    if (
                        replan
                        and name == "web_search"
                        and (
                            exact_need.needs_weather
                            or "weather" in self._expected_tools
                        )
                    ):
                        replan += (
                            " If they asked about the weather/forecast, call "
                            "weather — do not web_search again."
                        )
                    if replan:
                        self._fail_replan_used = True
                        if self._timer is not None:
                            self._timer.mark("fail_replan", tool=name)
                        messages.append({"role": "system", "content": replan})
                        await self.bus.publish(
                            Event(
                                EventType.THINKING,
                                {"text": f"fail_replan  {name}"},
                            )
                        )

            if ctx.skip_finish_text:
                await self._finish(ctx.skip_finish_text, sources, streamed="")
                return

        await self._force_final_answer(ctx)

    async def _force_final_answer(self, ctx: TurnContext) -> None:
        """Last round with tools withheld, after the loop has spent its budget."""
        await self.bus.publish(
            Event(
                EventType.THINKING,
                {"text": f"max rounds ({self.max_rounds}) reached, forcing answer"},
            )
        )
        force_msgs = [
            *ctx.messages,
            {
                "role": "user",
                "content": (
                    "Stop calling tools. Provide your best final answer now "
                    "from the information gathered. If you lack a tool warrant "
                    "for a precise or contingent claim, say you do not know."
                ),
            },
        ]
        try:
            raw_final, _, streamed = await self._stream_round(
                self._turn_role,
                force_msgs,
                None,
                round_n=self.max_rounds + 1,
            )
        except (_StoppedError, asyncio.CancelledError):
            raise
        except Exception as exc:
            await self._retract()
            failure = classify_ollama_failure(
                exc,
                model=self.router.model_for(self._turn_role),
                base_url=str((self.config.get("ollama") or {}).get("base_url") or ""),
                role=str(self._turn_role or ""),
            )
            await self._publish_error(failure.chat, detail=failure.detail)
            return

        final_content = strip_thinking_text(raw_final)
        # Force-final often arrives as {"final":"..."} after JSON-fallback
        # prompting; unwrap before shipping so the user never sees the envelope.
        if self.json_fallback:
            parsed_final = parse_fallback_payload(final_content, strict=False)
            if parsed_final and parsed_final["kind"] == "final":
                final_content = parsed_final["text"]
                streamed = ""
        refuse = _exactness_finish_refuse(
            final_content,
            exact_need=ctx.exact_need,
            ledger=ctx.ledger,
            numeric_gate=ctx.numeric_gate,
            evidence_gate=ctx.evidence_gate,
            send_path=ctx.is_send_path(self._expected_tools),
        )
        if refuse is None:
            refuse = self._look_refuse(final_content)
        if refuse is not None:
            await self._retract()
            if self._timer is not None:
                self._timer.mark("exactness", gate="refuse", reason="max_rounds")
            await self._finish(refuse, ctx.sources, streamed="")
            return

        await self._finish(
            final_content,
            ctx.sources,
            streamed=streamed,
            fallback_text=_ROUND_LIMIT_NOTICE,
        )

    def _look_refuse(self, content: str) -> str | None:
        look = self._look
        if look is None:
            return None
        return look_answer_refuse(
            content, act=look.intent.act, record=look.record
        )

    def _note_look_tool(
        self,
        name: str,
        args: dict[str, Any],
        result: Any,
        data_dict: dict[str, Any] | None,
    ) -> None:
        look = self._look
        if look is None:
            return
        data_dict = data_dict or {}
        args = args or {}
        if name == "camera":
            look.camera_snaps += 1
            path = str(data_dict.get("path") or "").strip()
            if path:
                look.path = path.replace("\\", "/")
                look.sha = frame_sha256(look.path)
            return
        if name == "ocr":
            look.ocr_done = True
            empty = bool(data_dict.get("empty"))
            mean_conf = data_dict.get("mean_conf")
            conf = float(mean_conf) if isinstance(mean_conf, (int, float)) else None
            raw = str(result.output or "")
            if empty:
                body = ""
            elif "chars):\n" in raw:
                body = raw.split("chars):\n", 1)[1]
            else:
                body = raw
            inspect = inspect_ocr_text(body, mean_conf=conf)
            look.ocr_text = inspect.text
            look.deferral = ocr_deferral(inspect)
            path = str(data_dict.get("path") or args.get("path") or look.path)
            if path:
                look.path = path.replace("\\", "/")
                look.sha = look.sha or frame_sha256(look.path)
        elif name == "vision":
            look.vision_done = True
            look.vl_text = str(result.output or "").strip()
            path = str(data_dict.get("path") or args.get("path") or look.path)
            if path:
                look.path = path.replace("\\", "/")
                look.sha = look.sha or frame_sha256(look.path)
        nxt = next_look_call(
            look.intent,
            path=look.path,
            camera_done=look.camera_snaps > 0 or bool(look.path),
            ocr_done=look.ocr_done,
            vision_done=look.vision_done,
            deferral=look.deferral,
        )
        if nxt is None and (look.ocr_done or look.vision_done):
            look.record = build_see_record(look)

    def _emit_look_receipt_if_ready(self) -> None:
        look = self._look
        if look is None or look.receipt_done or look.record is None:
            return
        nxt = next_look_call(
            look.intent,
            path=look.path,
            camera_done=look.camera_snaps > 0 or bool(look.path),
            ocr_done=look.ocr_done,
            vision_done=look.vision_done,
            deferral=look.deferral,
        )
        if nxt is not None:
            return
        look.receipt_done = True
        row = look_receipt(
            look.record,
            allow_count=look.allow_count if look.grant_minted else 0,
        )
        self._receipts.append(row)
        receipt_line = format_action_receipt(row)
        self._trace.append(receipt_line)
        if self._timer is not None:
            self._timer.mark("receipt", action="look", ok=True)
        session_id = None
        sink = getattr(self.memory, "sink", None)
        if sink is not None:
            session_id = getattr(sink, "session_id", None)
        append_action_ledger(row, session_id=session_id)

    async def _maybe_escalate(
        self,
        text: str,
        *,
        round_i: int,
        agent_cfg: dict[str, Any],
    ) -> bool:
        """Once per turn: fast → research when expected tools never fire."""
        target = decide_mid_turn_escalate(
            role=self._turn_role,
            text=text,
            round_i=round_i,
            expected=self._expected_tools,
            tools_used=self.tools_used,
            already_escalated=self._escalated,
            escalate_after_rounds=int(agent_cfg.get("escalate_after_rounds", 2)),
            enabled=bool(agent_cfg.get("mid_turn_escalate", True)),
        )
        if target is None:
            return False
        prev_model = self.router.model_for(self._turn_role)
        self._escalated = True
        self._turn_role = target
        new_model = self.router.model_for(target)
        await self.router.ensure_role(target, force=True)
        self.router.mark_sticky(target)
        if self._timer is not None:
            self._timer.mark(
                "escalate",
                from_role="fast",
                to_role=target,
                round=round_i,
                expected=",".join(sorted(self._expected_tools)) or "-",
            )
        await self.bus.publish(
            Event(
                EventType.MODEL_SWITCH,
                {
                    "from": prev_model,
                    "to": new_model,
                    "role": target,
                    "reason": "mid_turn_escalate",
                },
            )
        )
        await self.bus.publish(
            Event(
                EventType.THINKING,
                {"text": f"escalate  fast → {target}  (no expected tools yet)"},
            )
        )
        await self.bus.publish(
            Event(
                EventType.STATUS,
                {"message": f"Escalating to `{target}` model for this turn"},
            )
        )
        return True

    def _active_facts_line(self) -> str:
        """Approved facts from the archive, if this session has a sink."""
        sink = self.memory.sink
        if not isinstance(sink, MemoryStore):
            return ""
        try:
            texts = sink.active_fact_texts()
        except Exception:
            log.exception("Could not load active facts")
            return ""
        return facts_prompt_line(texts)

    async def _messages_for_turn(
        self,
        system_messages: list[dict[str, Any]],
        budget: int,
        ratio: float,
        role: ModelRole,
        *,
        user_text: str = "",
    ) -> list[dict[str, Any]]:
        """Pin system content, fold overflow into a summary, return the prompt.

        Summarization uses the turn's own role so a research or code turn does
        not bounce through the fast model and pay a VRAM swap before it starts.
        On the common fast path that is the warm model already.
        """
        agent_cfg = self.config.get("agent") or {}
        pinned = list(system_messages)
        if self.memory.summary:
            pinned.append(
                {
                    "role": "system",
                    "content": f"[earlier in this conversation: {self.memory.summary}]",
                }
            )
        history = self.memory.as_ollama(
            include_notes=not bool(self.config.get("_speak_replies"))
        )
        # A backstop on message count. The token budget below is the real limit;
        # this only stops the trailer growing without bound in a session long
        # enough that the budget alone would keep saying yes.
        try:
            max_msgs = int(agent_cfg.get("history_max_messages", 120) or 0)
        except (TypeError, ValueError):
            max_msgs = 120
        try:
            min_recent = int(
                agent_cfg.get("history_min_recent", _HISTORY_MIN_RECENT)
                or _HISTORY_MIN_RECENT
            )
        except (TypeError, ValueError):
            min_recent = _HISTORY_MIN_RECENT
        min_recent = max(1, min_recent)
        capped_drop: list[dict[str, Any]] = []
        if max_msgs > 0 and len(history) > max_msgs:
            capped_drop = list(history[:-max_msgs])
            history = list(history[-max_msgs:])
        older, tail = split_recent_history(history, min_recent)
        pinned_cost = sum(message_tokens(m, chars_per_token=ratio) for m in pinned)
        tail_cost = sum(message_tokens(m, chars_per_token=ratio) for m in tail)
        remaining = budget - pinned_cost - tail_cost
        if remaining <= 0 or not older:
            dropped = list(older)
            kept = list(tail)
        else:
            kept_older, dropped = allocate_history(
                older, remaining, chars_per_token=ratio
            )
            kept = [*kept_older, *tail]
        if capped_drop:
            dropped = [*capped_drop, *dropped]
        if self._timer is not None:
            self._timer.history_kept = len(kept)
            self._timer.history_dropped = len(dropped)
            if dropped:
                self._timer.mark(
                    "history_window",
                    kept=len(kept),
                    dropped=len(dropped),
                    max_messages=max_msgs,
                )
        if not dropped:
            return [*pinned, *kept]

        # Conversation mode: a second model pass to fold two old turns costs
        # ~1-2s and shows up in turns.log every spoken reply. The archive
        # already has those messages; drop them and keep answering.
        # Slash commands also skip the model summarize (H1 / L7).
        skip_summarize = bool(self.config.get("_speak_replies")) or (
            bool(agent_cfg.get("summarize_skip_slash", True))
            and (user_text or "").lstrip().startswith("/")
        ) or (role or "").strip().lower() == "research"
        if skip_summarize:
            n_drop = len(dropped)
            self.memory.drop_prompt_prefix(n_drop)
            if self.config.get("_speak_replies"):
                mode = "speak"
            elif (role or "").strip().lower() == "research":
                mode = "research"
            else:
                mode = "slash"
            if self._timer is not None:
                self._timer.mark("drop", dropped=n_drop, mode=mode)
            await self.bus.publish(
                Event(
                    EventType.THINKING,
                    {"text": f"phase=drop dropped={n_drop} mode={mode}"},
                )
            )
            return [*pinned, *kept]

        # Re-allocate against a smaller budget, because a summary pin is about to
        # take room the first pass did not reserve. Same older/tail split: the
        # history has not changed, only what it has to fit inside.
        remaining = budget - pinned_cost - tail_cost - _SUMMARY_RESERVE_TOKENS
        if remaining <= 0 or not older:
            dropped = list(older)
            kept = list(tail)
        else:
            kept, dropped = allocate_history(
                older,
                max(0, remaining),
                chars_per_token=ratio,
            )
            kept = [*kept, *tail]
        if capped_drop:
            dropped = [*capped_drop, *dropped]
        if not dropped:
            return [*pinned, *kept]

        await self.bus.publish(
            Event(
                EventType.STATUS,
                {"message": "Compressing earlier chat so the next reply fits…"},
            )
        )
        await self.bus.publish(
            Event(EventType.THINKING, {"text": "phase=summarize starting"})
        )
        summarize_t0 = time.perf_counter()
        max_ms = int(agent_cfg.get("summarize_max_ms", 8000) or 8000)
        summary, facts = await self._summarize_dropped(
            dropped, role, timeout_s=max(1.0, max_ms / 1000.0)
        )
        summarize_ms = int((time.perf_counter() - summarize_t0) * 1000)
        if self._timer is not None:
            self._timer.summarize_ms += summarize_ms
            self._timer.mark(
                "summarize",
                ms=summarize_ms,
                dropped=len(dropped),
                alert="over_budget" if summarize_ms > 15000 else "ok",
            )
        await self.bus.publish(
            Event(
                EventType.THINKING,
                {"text": f"phase=summarize ms={summarize_ms}"},
            )
        )
        if not summary and dropped:
            # Budget/timeout: drop without model fold so the turn can proceed.
            n_drop = len(dropped)
            self.memory.drop_prompt_prefix(n_drop)
            if self._timer is not None:
                self._timer.mark("drop", dropped=n_drop, mode="summarize_timeout")
            await self.bus.publish(
                Event(
                    EventType.THINKING,
                    {
                        "text": (
                            f"phase=drop dropped={n_drop} mode=summarize_timeout"
                        )
                    },
                )
            )
            return [*pinned, *kept]
        if summary:
            self.memory.set_summary(summary)
            # Dropped prefix is now in the summary; keeping it in messages would
            # re-send it every turn and trigger another summarize immediately.
            # The archive sink has already stored those messages; only the
            # in-process working set shrinks.
            self.memory.drop_prompt_prefix(len(dropped))
        for fact in facts:
            self.memory.add_pending_fact(fact)

        pinned = list(system_messages)
        if self.memory.summary:
            pinned.append(
                {
                    "role": "system",
                    "content": f"[earlier in this conversation: {self.memory.summary}]",
                }
            )
        pinned_cost = sum(message_tokens(m, chars_per_token=ratio) for m in pinned)
        remaining_history = self.memory.as_ollama(
            include_notes=not bool(self.config.get("_speak_replies"))
        )
        older, tail = split_recent_history(remaining_history, min_recent)
        tail_cost = sum(message_tokens(m, chars_per_token=ratio) for m in tail)
        room = budget - pinned_cost - tail_cost
        if room <= 0 or not older:
            kept = list(tail)
        else:
            kept_older, _more = allocate_history(
                older, max(0, room), chars_per_token=ratio
            )
            kept = [*kept_older, *tail]
        return [*pinned, *kept]

    async def _summarize_dropped(
        self,
        dropped: list[dict[str, Any]],
        role: ModelRole,
        *,
        timeout_s: float = 8.0,
    ) -> tuple[str, list[str]]:
        """Compress dropped turns with the turn's model. No tools, nothing painted."""
        excerpt = _format_transcript(dropped)
        previous = self.memory.summary or "(none)"
        messages = [
            {"role": "system", "content": _SUMMARY_SYSTEM},
            {
                "role": "user",
                "content": _SUMMARY_USER.format(
                    previous=previous,
                    excerpt=excerpt,
                    max_chars=_MAX_SUMMARY_CHARS,
                ),
            },
        ]
        parts: list[str] = []

        async def _consume() -> None:
            async for kind, payload in self.router.stream(
                role,
                messages,
                tools=None,
                options=self._stream_options(),
            ):
                if self.is_cancelled():
                    raise _StoppedError
                if kind == "token":
                    parts.append(str(payload))

        try:
            await asyncio.wait_for(_consume(), timeout=max(1.0, float(timeout_s)))
        except TimeoutError:
            log.info(
                "Rolling summary hit %ss budget; dropping without fold",
                timeout_s,
            )
            return "", []
        except _StoppedError:
            raise
        except Exception:
            # A failed summarize must not kill the turn: fall back to dropping
            # the overflow the way Phase 2 already did.
            log.exception("Rolling summary failed; continuing without it")
            return "", []
        return _parse_summary_response("".join(parts))

    def _stream_options(self, *, tools: bool = False) -> dict[str, Any] | None:
        """Turn-sticky num_ctx; lower temperature on tool-bearing rounds."""
        opts: dict[str, Any] = {}
        ctx = getattr(self, "_turn_num_ctx", None)
        if ctx is not None:
            opts["num_ctx"] = int(ctx)
        if tools:
            agent_cfg = self.config.get("agent") or {}
            try:
                temp = float(agent_cfg.get("tool_round_temperature", 0.1))
            except (TypeError, ValueError):
                temp = 0.1
            opts["temperature"] = temp
        return opts or None

    async def _stream_round(
        self,
        role: ModelRole,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        *,
        round_n: int = 0,
    ) -> tuple[str, list[dict[str, Any]], str]:
        """Run one model step, painting candidate answer text as it arrives.

        Returns the raw content, the native tool calls, and the text that was
        actually published, which the caller needs in order to retract it or to
        avoid sending it twice.
        """
        live = _LiveAnswer()
        content_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        model = self.router.model_for(role)
        # Hold paint while tools are offered so exactness nudges do not retract
        # a half-streamed answer every round (H5 / R13).
        agent_cfg = self.config.get("agent") or {}
        hold_paint = bool(tools) and bool(
            agent_cfg.get("stream_answer_after_tools", True)
        )
        stream_messages = _normalize_ollama_messages(list(messages))
        if tools:
            # Trailing hint only — must not sit in the static cached prefix.
            stream_messages.append({"role": "system", "content": _TOOL_ROUND_HINT})
        prompt_chars = prompt_char_count(stream_messages, tools=tools)
        await self.bus.publish(
            Event(
                EventType.THINKING,
                {
                    "text": (
                        f"phase=model role={role} hold_paint={int(hold_paint)}"
                    )
                },
            )
        )

        async for kind, payload in self.router.stream(
            role,
            stream_messages,
            tools=tools,
            options=self._stream_options(tools=bool(tools)),
        ):
            if self.is_cancelled():
                raise _StoppedError
            if self.is_paused():
                await self._hold_if_paused()
            if kind == "thinking":
                chunk = str(payload)
                if chunk:
                    await self.bus.publish(
                        Event(EventType.THINKING, {"text": chunk, "stream": True})
                    )
            elif kind == "token":
                chunk = str(payload)
                content_parts.append(chunk)
                if hold_paint:
                    continue
                visible, retract = live.feed(chunk)
                if retract:
                    await self._retract()
                if visible:
                    await self._publish_delta(visible)
            elif kind == "tool_calls":
                tool_calls = list(payload or [])
                if hold_paint and tool_calls:
                    await self._publish_tool_intent(tool_calls)
            elif kind == "metrics":
                if self._timer is not None and isinstance(payload, dict):
                    self._timer.note_ollama_metrics(payload, round_n=round_n)
                count = payload.get("prompt_eval_count") if isinstance(payload, dict) else None
                if isinstance(count, int):
                    updated = self._token_ratios.observe(model, prompt_chars, count)
                    if updated is not None:
                        self.memory.chars_per_token = updated

        raw = "".join(content_parts).strip()
        if hold_paint:
            # Never paint here: raw may still be a JSON-fallback tool call that
            # the caller parses after return. Final answers are painted in
            # _finish (or a later round with tools=None).
            return raw, tool_calls, ""
        tail = live.flush()
        if tail:
            await self._publish_delta(tail)
        return raw, tool_calls, live.published

    async def _explain_missing_send_sms(self, available_all: set[str]) -> None:
        """Say why a ready SMS cannot be sent, instead of answering in prose.

        There are only two reasons and they need different fixes, so guessing
        wastes an evening: either the tool was never registered because the
        Android Notify credentials are absent, or it is registered and this turn
        hid it because the utterance did not read as a send.
        """
        if "send_sms" in available_all:
            reason = (
                "send_sms is registered but hidden for this turn by the tool "
                "subset — the utterance did not read as an outbound send."
            )
        else:
            reason = (
                "send_sms is not registered: the Android Notify SMS account is "
                "missing (data/secrets.yaml → sms.base_url, sms.username, and "
                "the password or ARELIS_SMS_PASSWORD)."
            )
        await self.bus.publish(Event(EventType.THINKING, {"text": f"sms  {reason}"}))
        await self.bus.publish(Event(EventType.STATUS, {"message": reason}))

    async def _publish_tool_intent(self, tool_calls: list[dict[str, Any]]) -> None:
        """Surface a short status as soon as a tool call is parsed (felt latency)."""
        label = _tool_intent_label(tool_calls)
        if not label:
            return
        await self.bus.publish(Event(EventType.THINKING, {"text": label}))
        await self.bus.publish(Event(EventType.STATUS, {"message": label}))

    async def _publish_delta(self, text: str) -> None:
        from arelis.voice.speech_text import scrub_cjk_runs

        text = scrub_cjk_runs(text, strip=False) if text else text
        if not text:
            return
        self._painted += text
        if self._timer is not None and text:
            self._timer.note_first_delta()
        await self.bus.publish(Event(EventType.ASSISTANT_DELTA, {"text": text}))

    async def _retract(self) -> None:
        """Withdraw everything painted since the last terminal event."""
        if not self._painted:
            return
        self._painted = ""
        await self.bus.publish(Event(EventType.ASSISTANT_RETRACT, {}))

    async def _confirm_wait_heartbeat(self, tool: str, started: float) -> None:
        """Periodic thinking while Allow is open (L10)."""
        try:
            while True:
                await asyncio.sleep(5.0)
                elapsed = int(time.perf_counter() - started)
                await self.bus.publish(
                    Event(
                        EventType.THINKING,
                        {
                            "text": (
                                f"phase=confirm waiting for Allow "
                                f"({elapsed}s) tool={tool}"
                            )
                        },
                    )
                )
        except asyncio.CancelledError:
            return

    def _tool_message(self, name: str, content: str) -> dict[str, Any]:
        """Tool result in the shape Ollama expects.

        tool_name is included so a round with several calls stays unambiguous.
        Without it the model receives an ordered list of anonymous results and
        has to guess which one answers which call.
        """
        return {"role": "tool", "tool_name": name, "content": content}

    async def _finish(
        self,
        text: str,
        sources: list[tuple[str, str]],
        *,
        streamed: str = "",
        fallback_text: str = "",
    ) -> None:
        """Publish the single terminal event for this turn.

        Everything that must happen exactly once per turn lives here: citation
        append, memory write, whatever delta is still owed, ASSISTANT_DONE, and
        the optional voice hand-off.
        """
        final = strip_thinking_text(text).strip()
        if not final:
            # An empty model reply used to end the turn with an empty bubble:
            # no answer, no error, no explanation. Say something actionable.
            final = fallback_text or _EMPTY_REPLY_NOTICE
        # Last-chance unwrap: any path that still holds a {"final":"..."}
        # envelope must not paint it into chat.
        if self.json_fallback and final.startswith("{") and '"final"' in final:
            parsed_final = parse_fallback_payload(final, strict=False)
            if parsed_final and parsed_final["kind"] == "final":
                final = (parsed_final["text"] or "").strip() or final
                streamed = ""
        final = _append_sources(final, sources)

        # Preflight expected a tool but none of those succeeded this turn.
        if self._expected_tools and not (self.tools_used & self._expected_tools):
            if self._timer is not None:
                self._timer.mark(
                    "routing_gap",
                    expected=",".join(sorted(self._expected_tools)),
                    used=",".join(sorted(self.tools_used)) or "-",
                )
            await self.bus.publish(
                Event(
                    EventType.THINKING,
                    {
                        "text": (
                            "routing_gap  expected "
                            + ",".join(sorted(self._expected_tools))
                            + "  used "
                            + (",".join(sorted(self.tools_used)) or "-")
                        )
                    },
                )
            )

        self.memory.add("assistant", final, note=tool_trace_note(self._trace))

        # Usually the answer was already streamed and only the appended Sources
        # list is still owed. When the text changed under us, for example
        # because a {"final": ...} payload replaced it, retract and resend.
        already = streamed.strip()
        if already and final.startswith(already):
            remainder = final[len(already) :]
            if remainder.strip():
                await self._publish_delta(remainder)
        else:
            await self._retract()
            await self._publish_delta(final)

        self.terminal_sent = True
        self._painted = ""
        if self._timer is not None:
            blurb = self._timer.finish("ok")
            await self.bus.publish(Event(EventType.THINKING, {"text": blurb}))
        voice = self.config.get("voice", {})
        will_speak = bool(voice.get("enabled")) and bool(voice.get("tts", {}).get("enabled", True))
        # speak tells the UI that a spoken reply follows. Streaming TTS may
        # already have armed on the first clip; this covers the gap when the
        # first sentence was held until VOICE_SPEAK. Other producers of
        # ASSISTANT_DONE (slash commands, the cancel notice) omit it.
        await self.bus.publish(
            Event(EventType.ASSISTANT_DONE, {"text": final, "speak": will_speak})
        )
        # The answer goes out as written. Reducing it to something speakable is
        # the voice service's job, not the loop's: the bus carries the real
        # text, and only the branch that ends in a speaker changes it.
        if will_speak:
            await self.bus.publish(Event(EventType.VOICE_SPEAK, {"text": final}))

    async def _hold_if_paused(self) -> None:
        """Freeze between steps while the Drive strip is on Pause."""
        while self.is_paused() and not self.is_cancelled():  # noqa: ASYNC110
            await asyncio.sleep(0.12)
        if self.is_cancelled():
            raise _StoppedError

    async def _await_your_turn(self, kind: str) -> None:
        """Hold until the wall is gone (captcha/login) or they hit Go."""
        from arelis.browser.hold import is_paused, set_paused

        tool = self.tools.get("browser")
        session = getattr(tool, "session", None)
        auto = kind in {"captcha", "login"}
        while not self.is_cancelled():
            if not is_paused() and not self.is_paused():
                return
            if auto and session is not None:
                probe = getattr(session, "probe_wall", None)
                wall = None
                if callable(probe):
                    try:
                        wall = await probe()
                    except Exception:
                        wall = None
                if wall is None:
                    set_paused(False)
                    await self.bus.publish(
                        Event(
                            EventType.TURN_RESUME,
                            {"reason": "wall_cleared", "kind": kind},
                        )
                    )
                    return
            await asyncio.sleep(0.8)
        raise _StoppedError

    async def _cancel_notice(self) -> None:
        """End a stopped turn, keeping whatever was already written.

        Discarding a half-finished answer is the wrong default: the user pressed
        stop because they had seen enough, not because they wanted it erased.
        The partial text is deliberately not added to memory, since a truncated
        answer is a poor thing for the next turn to build on.
        """
        if self.terminal_sent:
            return
        self.terminal_sent = True
        partial = self._painted.strip()
        self._painted = ""
        text = f"{partial}\n\n_Stopped._" if partial else "Stopped."
        # publish_nowait, not publish: this also runs while a CancelledError is
        # propagating, and anything that suspends there can be interrupted
        # again, which would lose the terminal event and hang the composer.
        self.bus.publish_nowait(Event(EventType.THINKING, {"text": "cancelled"}))
        self.bus.publish_nowait(Event(EventType.ASSISTANT_DONE, {"text": text}))
        self.memory.mark_last_user_cancelled()

    async def _publish_error(self, message: str, *, detail: str = "") -> None:
        self.terminal_sent = True
        self._painted = ""
        if detail:
            await self.bus.publish(Event(EventType.THINKING, {"text": detail}))
        if self._timer is not None:
            blurb = self._timer.finish("error")
            await self.bus.publish(Event(EventType.THINKING, {"text": blurb}))
        payload: dict[str, Any] = {"message": message}
        if detail:
            payload["detail"] = detail
        await self.bus.publish(Event(EventType.ERROR, payload))


_EVIDENCE_KINDS = frozenset(
    {
        "web",
        "weather",
        "recall",
        "inbox",
        "inbound_sms",
        "doc",
        "agenda",
        "git",
        "tasks",
        "analyze",
    }
)


_PROJECT_CONTEXT_SKILLS = frozenset({"workspace", "analyze", "docs", "document", "science"})
_PROJECT_CONTEXT_TOOLS = frozenset(
    {"workspace", "analyze", "git_info", "doc_extract", "plot", "document"}
)


def _wants_project_context(
    *,
    role: str,
    skill_ids: list[str] | tuple[str, ...] | set[str],
    expected_tools: set[str],
) -> bool:
    """True when the active-project system line is relevant this turn.

    Always injecting it on conversation follow-ups is how a missing last
    turn gets replaced by a guess about the interferometer root.
    """
    if (role or "").strip().lower() == "research":
        return True
    if _PROJECT_CONTEXT_SKILLS & set(skill_ids):
        return True
    return bool(expected_tools & _PROJECT_CONTEXT_TOOLS)


def disconnected_integration_reply(
    *,
    expected: set[str],
    available: set[str],
    want_sms: bool = False,
    want_mail: bool = False,
    want_calendar: bool = False,
) -> str | None:
    """Chat line when they asked for mail/SMS/calendar that is not connected.

    Returns None when those tools are registered, or when the turn also needs
    some other registered tool. Mixed work stays with the model.
    """
    integration = {"send_sms", "inbound_sms", "send_email", "inbox", "agenda"}
    if set(expected) - integration:
        return None
    if want_sms or expected & {"send_sms", "inbound_sms"}:
        needed = set()
        if want_sms or "send_sms" in expected:
            needed.add("send_sms")
        if "inbound_sms" in expected:
            needed.add("inbound_sms")
        if needed and not (needed & available):
            return (
                "I can't text until the phone is paired. "
                "Open Settings → Notify and scan the QR."
            )
    if want_mail or expected & {"send_email", "inbox"}:
        needed = set()
        if want_mail or "send_email" in expected:
            needed.add("send_email")
        if "inbox" in expected:
            needed.add("inbox")
        if needed and not (needed & available):
            return (
                "I can't send or read mail until an account is in Settings → Mail."
            )
    if want_calendar or "agenda" in expected:
        if "agenda" not in available:
            return (
                "I can't use the calendar until Google is connected. "
                "That's in Settings."
            )
    return None


def should_offer_tools(
    *,
    chat_fast_path: bool,
    skill_ids: list[str] | tuple[str, ...] | set[str],
    preflight_kinds: list[str] | tuple[str, ...] | set[str],
    research_mode: bool,
    expected_tools: set[str],
    exact_need: Any,
    wants_fresh_page: bool,
    active_plan: Any | None,
) -> bool:
    """Whether this turn should send Ollama tool schemas.

    When ``chat_fast_path`` is on, pure social chat skips schemas for TTFT.
    Any skill, preflight, plan, research mode, expected tool, or exactness
    warrant (including vision) must re-arm tools — otherwise the 7B invents
    captions or denies capabilities it just used.
    """
    if not chat_fast_path:
        return True
    kinds = getattr(exact_need, "kinds", ()) or ()
    return bool(
        skill_ids
        or preflight_kinds
        or research_mode
        or expected_tools
        or kinds
        or wants_fresh_page
        or active_plan is not None
    )


_NEWS_FRESH_MARKERS = (
    "news",
    "latest",
    "headline",
    "article",
    "wsj",
    "what happened",
    "current events",
    "breaking",
)
_TODAY_NEWS = re.compile(
    r"(?i)\b(?:"
    r"(?:news|headlines?|happened|breaking|article).{0,24}today"
    r"|today.{0,24}(?:news|headlines?|happened|breaking)"
    r"|today'?s\s+(?:news|headlines?)"
    r")\b"
)


def wants_fresh_page_ask(text: str) -> bool:
    """True for a current-events ask — not every sentence that says 'today'."""
    raw = text or ""
    low = raw.lower()
    if any(marker in low for marker in _NEWS_FRESH_MARKERS):
        return True
    return bool(_TODAY_NEWS.search(raw))


def decide_mid_turn_escalate(
    *,
    role: str,
    text: str,
    round_i: int,
    expected: set[str],
    tools_used: set[str],
    already_escalated: bool,
    escalate_after_rounds: int = 2,
    enabled: bool = True,
) -> ModelRole | None:
    """Pure escalate decision (Wave 2). Returns target role or None."""
    if already_escalated or not enabled:
        return None
    if role != "fast":
        return None
    if _OUTBOUND_LOCK.search(text or ""):
        return None
    after = max(1, int(escalate_after_rounds))
    if round_i <= after:
        return None
    # IMPORTANT: never call is_research_mode("research", …) here — that forces
    # True because the role arg is hardcoded, so every turn after round 2 used
    # to escalate to 14B and pin ~10GB VRAM (agenda/calendar sessions).
    multi = bool(expected) or is_deep_dive_ask(text)
    if not multi:
        return None
    if expected & {
        "analyze",
        "weather",
        "send_sms",
        "send_email",
        "agenda",
        "image",
        "vision",
    } and "research_report" not in expected:
        return None
    if expected and (tools_used & expected):
        return None
    if not expected and tools_used:
        return None
    # Research-shaped asks win over bare "write" in FILE_ESCALATE (e.g. "write
    # a report" must escalate to research, not stay on a file-shaped miss).
    if "research_report" in expected or is_deep_dive_ask(text):
        return "research"
    if expected & {"web_search", "scrape", "web_fetch", "research_report"}:
        return "research"
    return None


def _exactness_finish_refuse(
    content: str,
    *,
    exact_need: Any,
    ledger: EvidenceLedger,
    numeric_gate: bool,
    evidence_gate: bool,
    send_path: bool = False,
) -> str | None:
    """Return a refusal when finishing would ship an unsupported exact claim."""
    # Side-effect honesty runs before refusal escape so hedge-then-claim
    # ("I don't know, but I sent…") cannot ship a fake send.
    if evidence_gate:
        send_missing = send_claim_missing_kinds(
            content,
            has_send_sms=ledger.has_ok("send_sms"),
            has_send_email=ledger.has_ok("send_email"),
        )
        if send_missing:
            return unsupported_send_claim_reply()
    if answer_looks_like_refusal(content):
        return None
    # Compose/send turns must not die on "no retrieved page warrant" (R4 / S10).
    if send_path:
        return None
    kinds = tuple(exact_need.kinds or ())
    if not kinds:
        return None
    missing = ledger.missing_kinds(kinds)
    if not numeric_gate:
        missing = [
            k
            for k in missing
            if k not in {"math", "symbolic", "units", "plot", "catalog", "document"}
        ]
    if not evidence_gate:
        missing = [k for k in missing if k not in _EVIDENCE_KINDS]
    if not missing:
        return None
    if "math" in missing:
        calc_fail = next(
            (w for w in ledger.items if w.kind == "calc" and not w.ok),
            None,
        )
        if calc_fail is not None:
            return unsupported_exactness_reply(
                missing, calc_failed=True, calc_detail=calc_fail.span
            )
    if "symbolic" in missing:
        cas_fail = next(
            (w for w in ledger.items if w.kind == "cas" and not w.ok),
            None,
        )
        if cas_fail is not None:
            return unsupported_exactness_reply(
                missing, cas_failed=True, cas_detail=cas_fail.span
            )
    if "units" in missing:
        units_fail = next(
            (w for w in ledger.items if w.kind == "units" and not w.ok),
            None,
        )
        if units_fail is not None:
            return unsupported_exactness_reply(
                missing, units_failed=True, units_detail=units_fail.span
            )
    if "plot" in missing:
        plot_fail = next(
            (w for w in ledger.items if w.kind == "plot" and not w.ok),
            None,
        )
        if plot_fail is not None:
            return unsupported_exactness_reply(
                missing, plot_failed=True, plot_detail=plot_fail.span
            )
    if "catalog" in missing:
        catalog_fail = next(
            (w for w in ledger.items if w.kind == "catalog" and not w.ok),
            None,
        )
        if catalog_fail is not None:
            return unsupported_exactness_reply(
                missing, catalog_failed=True, catalog_detail=catalog_fail.span
            )
    if "document" in missing:
        document_fail = next(
            (w for w in ledger.items if w.kind == "document" and not w.ok),
            None,
        )
        if document_fail is not None:
            return unsupported_exactness_reply(
                missing, document_failed=True, document_detail=document_fail.span
            )
    return unsupported_exactness_reply(missing)


def _answer_has_quote_span(text: str) -> bool:
    """True when the answer includes a non-empty quoted span (ASCII or curly)."""
    return bool(re.search(r'"[^"\n]{3,}"|“[^”\n]{3,}”', text or ""))


_EMPTY_REPLY_NOTICE = (
    "The model returned an empty reply. That usually means the context was "
    "exhausted or the model was unloaded mid-turn. Try a narrower ask, or check "
    "that Ollama is still running."
)

_ROUND_LIMIT_NOTICE = "I hit the tool-step limit before finishing. Try a narrower ask."

# Sent when a model announces a call in prose rather than making one. Observed
# from qwen2.5:7b: "Let's start by reading the file:" then a fenced JSON object,
# then "Once I've read it I'll summarize". Nothing runs, and the JSON is what
# the user ends up reading.
#
# The wording is load-bearing and was arrived at by measurement. An earlier
# version offered "or answer directly from what you already know", and the model
# took that option and invented a summary of a file it had never opened, which
# is a worse failure than the one being corrected. Another phrasing left it
# asking which repository the README belonged to. So the notice now quotes the
# exact call back, gives no alternative, and names invention as the thing not to
# do.
_MALFORMED_CALL_NOTICE = (
    "You printed a tool call as text, so nothing ran and you have no result to "
    "work from. The call you meant was `{tool}` with arguments {args}. Make that "
    "exact call through the tool interface now. Do not print JSON, do not restate "
    "the plan, and do not answer from memory: you have not seen that content yet, "
    "so any summary of it would be invented."
)

# What the model is told when the user declines a call. The wording matters more
# than it looks. A bare "user skipped tool X" reads as "you lack permission", and
# models respond by apologizing, refusing to use tools for the rest of the
# session, and suggesting the user run a shell command instead. This says what
# actually happened and what is still allowed.
_SKIP_NOTICE = (
    "The user declined this specific `{tool}` call. This is not a permissions "
    "error and the tool is still available. Either propose a different call, or "
    "ask what they would prefer. Do not tell the user to run commands themselves, "
    "and do not claim the change was made."
)


def _format_transcript(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages:
        role = str(message.get("role") or "?")
        content = message.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _parse_summary_response(text: str) -> tuple[str, list[str]]:
    """Pull SUMMARY and FACTS out of the model reply.

    Tolerates missing labels and a bare paragraph: a failed parse must still
    yield something injectable rather than discarding the whole compression.
    Proposed facts are filtered hard: 7B compress passes otherwise dump the
    whole transcript into the History review queue.
    """
    cleaned = text.strip()
    if not cleaned:
        return "", []

    summary = ""
    facts: list[str] = []
    section: str | None = None
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("SUMMARY:"):
            section = "summary"
            summary = line.split(":", 1)[1].strip()
            continue
        if upper.startswith("FACTS:"):
            section = "facts"
            remainder = line.split(":", 1)[1].strip()
            if remainder:
                _append_fact(facts, remainder)
            continue
        if section == "summary":
            summary = f"{summary} {line}".strip() if summary else line
        elif section == "facts":
            _append_fact(facts, line.lstrip("- ").strip())
        elif section is None:
            # Model ignored the form and wrote a paragraph. Use it as the summary.
            summary = f"{summary} {line}".strip() if summary else line

    if len(summary) > _MAX_SUMMARY_CHARS:
        summary = summary[: _MAX_SUMMARY_CHARS - 1].rstrip() + "…"
    return summary, facts[:_MAX_PROPOSED_FACTS]


def _append_fact(facts: list[str], raw: str) -> None:
    text = raw.strip().lstrip("- ").strip()
    if not text or text.upper() == "NONE":
        return
    if not _looks_like_durable_fact(text):
        return
    if text not in facts:
        facts.append(text)


_TRANSIENT_FACT_MARKERS = (
    "asked",
    "discussed",
    "talked about",
    "mentioned that",
    "wants me to",
    "wants you to",
    "this turn",
    "this chat",
    "this conversation",
    "just said",
    "is working on",
    "is trying to",
    "looking at",
    "opened ",
    "wrote ",
    "read ",
    "searched ",
    "tool ",
    "confirm",
    # Draft / send / exactness refuse crumbs (U8).
    "email draft",
    "draft email",
    "draft reply",
    "subject:",
    "send_email",
    "send_sms",
    "text my ",
    "sms to",
    "don't know",
    "do not know",
    "no retrieved",
    "without a warrant",
    "exactness",
    "i don't have",
    "refuse",
)


def _tool_fail_fingerprint(name: str, args: dict[str, Any] | None) -> str:
    """Stable key for identical tool+args failures within a turn (K2)."""
    try:
        payload = json.dumps(args or {}, sort_keys=True, default=str)
    except TypeError:
        payload = repr(args)
    return f"{name}|{payload}"


def _looks_like_durable_fact(text: str) -> bool:
    """Reject transcript crumbs that 7B models label as FACTS."""
    cleaned = " ".join(text.split())
    if len(cleaned) < 8 or len(cleaned) > 200:
        return False
    lower = cleaned.lower()
    if lower in {"none", "n/a", "na", "nothing", "no facts"}:
        return False
    if cleaned.endswith("?"):
        return False
    if lower.startswith(("user:", "assistant:", "system:", "tool:")):
        return False
    if any(marker in lower for marker in _TRANSIENT_FACT_MARKERS):
        return False
    # Prefer statements about the person / standing projects, not chat meta.
    durable_hints = (
        "user ",
        "prefers",
        "prefer ",
        "works ",
        "is a ",
        "lives ",
        "studies",
        "climbs",
        "builds ",
        "owns ",
        "uses ",
        "always ",
        "never ",
        "allergic",
        "timezone",
        "located",
    )
    # Require a durable cue. Chatty compress models otherwise invent a fact
    # for every turn; History is a review queue, not a transcript dump.
    return any(hint in lower for hint in durable_hints)


def _append_sources(answer: str, sources: list[tuple[str, str]]) -> str:
    """Guarantee a Sources list whenever the web was actually used.

    The persona and tool policy both promise citations, but a prompt cannot
    enforce one. These entries come from tool results, so the list can only ever
    contain pages that really loaded at their post-redirect URL. If the model
    already wrote its own Sources section, leave it alone. Only http(s) URLs
    are kept so STATUS / notify copy can never appear as a citation (R6).
    """
    if not sources:
        return answer
    if "sources:" in answer.lower():
        return answer
    if answer_looks_like_refusal(answer):
        return answer
    clean: list[tuple[str, str]] = []
    for title, url in sources:
        u = (url or "").strip()
        t = (title or "").strip()
        if t.lower().startswith("inbound notify") or u.lower().startswith("inbound notify"):
            continue
        if not (u.startswith("http://") or u.startswith("https://")):
            continue
        clean.append((t, u))
    if not clean:
        return answer
    lines = ["", "**Sources:**"]
    for i, (title, url) in enumerate(clean, start=1):
        lines.append(f"{i}. {title} ({url})" if title else f"{i}. {url}")
    return answer + "\n" + "\n".join(lines)
