from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from uuid import uuid4

from arelis.core.bus import EventBus
from arelis.core.context import (
    TokenRatios,
    allocate_history,
    message_tokens,
    prompt_char_count,
    split_recent_history,
)
from arelis.core.events import Event, EventType
from arelis.core.facts import facts_prompt_line
from arelis.core.json_tools import (
    ThinkingStripper,
    parse_fallback_payload,
    strip_thinking_text,
)
from arelis.core.look import (
    LookTurn,
    build_see_record,
    frame_sha256,
    inspect_ocr_text,
    look_answer_refuse,
    look_receipt,
    next_look_call,
    ocr_deferral,
)
from arelis.core.memory import SessionMemory, tool_trace_note
from arelis.core.receipts import (
    append_action_ledger,
    format_action_receipt,
)
from arelis.core.skills import (
    full_tool_policy,
)
from arelis.core.turn_context import TurnContext
from arelis.core.turn_telemetry import TurnTimer
from arelis.llm.errors import classify_ollama_failure
from arelis.llm.router import ModelRole, ModelRouter
from arelis.memory.store import MemoryStore
from arelis.tools.base import ToolRegistry

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
        self._turn_source = "chat"

    async def run(
        self,
        text: str,
        role: ModelRole,
        *,
        source: str = "chat",
        route_reason: str = "default",
        stopped_ask: str = "",
    ) -> None:
        try:
            await self._run(
                text,
                role,
                source=source,
                route_reason=route_reason,
                stopped_ask=stopped_ask,
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
        stopped_ask: str = "",
    ) -> None:
        ctx = await self._prepare_turn(
            text,
            role,
            source=source,
            route_reason=route_reason,
            stopped_ask=stopped_ask,
        )
        if ctx is None:
            return
        for round_i in range(1, self.max_rounds + 1):
            if await self._run_round(ctx, round_i):
                return
        await self._force_final_answer(ctx)

    async def _prepare_turn(
        self,
        text: str,
        role: ModelRole,
        *,
        source: str = "chat",
        route_reason: str = "default",
        stopped_ask: str = "",
    ) -> TurnContext | None:
        from arelis.core.turn_prepare import prepare_turn
        return await prepare_turn(
            self, text, role, source=source, route_reason=route_reason, stopped_ask=stopped_ask,
        )

    async def _run_round(self, ctx: TurnContext, round_i: int) -> bool:
        from arelis.core.turn_round import run_round
        return await run_round(self, ctx, round_i)

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
                expect_tools=False,
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
        expect_tools: bool | None = None,
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
        # Hold paint on a real tool round so exactness nudges do not retract
        # a half-streamed answer (H5 / R13). Schemas can still ride a chitchat
        # turn for the prefix cache — that is not a tool round.
        agent_cfg = self.config.get("agent") or {}
        tool_round = bool(tools) and (
            bool(expect_tools) if expect_tools is not None else True
        )
        hold_paint = tool_round and bool(
            agent_cfg.get("stream_answer_after_tools", True)
        )
        stream_messages = _normalize_ollama_messages(list(messages))
        if tool_round:
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
        # Eval/scripted fakes are not ModelRouter. Asking them for the
        # gate used to AttributeError, which the loop treated as a dead
        # Ollama — no tool calls, no ASSISTANT_DONE.
        if getattr(self.router, "warmup_pending", lambda: False)():
            await self.bus.publish(
                Event(
                    EventType.THINKING,
                    {
                        "text": (
                            "waiting for the conversation model to finish "
                            "loading — first reply after that is quick"
                        )
                    },
                )
            )
            if self._timer is not None:
                self._timer.mark("warmup_wait")

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
        will_speak = (
            bool(voice.get("enabled"))
            and bool(voice.get("tts", {}).get("enabled", True))
            and getattr(self, "_turn_source", "chat") != "mobile"
        )
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


from arelis.core.loop_helpers import (  # noqa: E402, F401
    _EMPTY_REPLY_NOTICE,
    _EVIDENCE_KINDS,
    _MALFORMED_CALL_NOTICE,
    _NEWS_FRESH_MARKERS,
    _PROJECT_CONTEXT_SKILLS,
    _PROJECT_CONTEXT_TOOLS,
    _ROUND_LIMIT_NOTICE,
    _SKIP_NOTICE,
    _TODAY_NEWS,
    _TRANSIENT_FACT_MARKERS,
    _answer_has_quote_span,
    _append_fact,
    _append_sources,
    _exactness_finish_refuse,
    _format_transcript,
    _looks_like_durable_fact,
    _parse_summary_response,
    _tool_fail_fingerprint,
    _wants_project_context,
    decide_mid_turn_escalate,
    disconnected_integration_reply,
    should_offer_tools,
    turn_expects_tool_round,
    wants_fresh_page_ask,
)
