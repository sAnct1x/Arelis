"""Multi-turn conversation soak — production tool routing under shared memory.

Unlike single-utterance foundation scenarios, this keeps one AgentLoop session
across many user turns so sticky context (SMS drafts, calendar ids, generated
image paths) matches real conversation mode.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from arelis.config import shipped_num_ctx
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.eval.harness import (
    _BrowserStub,
    _FatScrapeStub,
    _ResearchReportStub,
    _ScriptedRouter,
    _StubTool,
    _VisionStub,
)
from arelis.paths import display_path, outputs_dir, user_data_dir
from arelis.tools.base import ToolRegistry, ToolResult


def tool_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """OpenAI-style tool_call for scripted router rounds."""
    return {
        "type": "function",
        "function": {"name": name, "arguments": args},
    }


@dataclass(frozen=True)
class ConversationTurn:
    """One user turn inside a multi-turn soak."""

    id: str
    user: str
    expect_tools: tuple[str, ...] = ()
    expect_tools_any: bool = False
    require_args: tuple[str, ...] = ()
    expect_args: dict[str, str] = field(default_factory=dict)
    expect_answer_contains: tuple[str, ...] = ()
    forbid_claim_if_no_tool: tuple[str, ...] = ()
    allow_no_tools: bool = False
    # Scripted model rounds for offline mode (ignored when live).
    script: list[list[tuple[str, Any]]] = field(default_factory=list)
    notes: str = ""


@dataclass
class ToolCallRecord:
    name: str
    args: dict[str, Any]
    ok: bool | None = None
    ms: int = 0
    output_head: str = ""


@dataclass
class TurnReport:
    turn_id: str
    user: str
    ok: bool
    reasons: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    expect_tools: list[str] = field(default_factory=list)
    final_text: str = ""
    thinking_tail: list[str] = field(default_factory=list)
    total_ms: int = 0
    model_ms: int = 0
    confirm_ms: int = 0
    first_paint_ms: int | None = None
    rounds: int = 0
    notes: str = ""


@dataclass
class SoakReport:
    id: str
    mode: str
    ok: bool
    started_at: str
    finished_at: str = ""
    total_ms: int = 0
    turns: list[TurnReport] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Stateful stubs — calendar ids, generated images, richer weather/SMS/email
# ---------------------------------------------------------------------------


class _WeatherSoakStub(_StubTool):
    async def run(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        out = (
            "Place: Springfield, Illinois\n"
            "Coordinates: 39.7817, -89.6501\n"
            "Now: 68.7°F (feels 70.8°F), overcast, precip 0.\n"
            "Daily:\n"
            "- 2026-08-11: high 75.4°F / low 64.5°F, heavy rain, precip chance 91%.\n"
            "- 2026-08-12: high 79.2°F / low 63.2°F, light drizzle, precip chance 17%."
        )
        return ToolResult(
            ok=True,
            output=out,
            data={"latitude": 39.7817, "longitude": -89.6501},
        )


class _AgendaSoakStub(_StubTool):
    """Tracks create/delete so later turns can delete a real stub id."""

    def __init__(self) -> None:
        super().__init__("agenda", risk="read")
        self.events: dict[str, dict[str, Any]] = {}

    async def run(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        action = str(kwargs.get("action") or "").strip().lower()
        if action == "create":
            eid = f"soak-{uuid4().hex[:10]}"
            summary = str(kwargs.get("summary") or "Event")
            start = str(kwargs.get("start") or "")
            self.events[eid] = {
                "id": eid,
                "summary": summary,
                "start": start,
                "provider": str(kwargs.get("provider") or "google"),
            }
            return ToolResult(
                ok=True,
                output=(
                    f"Created Google Calendar event '{summary}' at {start}."
                ),
                data={"event_id": eid, **self.events[eid]},
            )
        if action == "delete":
            eid = str(kwargs.get("event_id") or kwargs.get("id") or "").strip()
            if not eid:
                # Delete the most recent created event when the model omits id.
                if self.events:
                    eid = next(reversed(self.events))
                else:
                    return ToolResult(
                        ok=False,
                        output="[fail:agenda] delete requires event_id",
                    )
            gone = self.events.pop(eid, None)
            if gone is None:
                return ToolResult(
                    ok=False,
                    output=f"[fail:agenda] unknown event_id={eid}",
                )
            return ToolResult(
                ok=True,
                output=f"Deleted calendar event '{gone.get('summary')}' (id={eid}).",
                data={"event_id": eid, "deleted": True},
            )
        if action in {"today", "tomorrow", "list", "range"}:
            rows = list(self.events.values())
            if not rows:
                return ToolResult(ok=True, output="No events.", data={"events": []})
            lines = [f"- {e['summary']} @ {e['start']}" for e in rows]
            return ToolResult(
                ok=True,
                output=(
                    "Events:\n"
                    + "\n".join(lines)
                    + "\nSummarize time and title. Do not quote event ids."
                ),
                data={"events": rows},
            )
        return ToolResult(
            ok=True,
            output=f"agenda {action or 'ok'}",
            data=dict(kwargs),
        )


class _ImageSoakStub(_StubTool):
    """Writes a tiny real PNG so vision/upload turns have a file on disk."""

    def __init__(self, out_dir: Path) -> None:
        super().__init__("image", risk="side_effect")
        self.out_dir = out_dir
        self.last_path = ""

    async def run(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"soak_{uuid4().hex[:8]}.png"
        # Minimal valid 1x1 PNG
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
            b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
            b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        rel = display_path(path)
        self.last_path = rel
        prompt = str(kwargs.get("prompt") or kwargs.get("text") or "")[:120]
        return ToolResult(
            ok=True,
            output=(
                f"Generated image.\nSaved: {rel}\n"
                "Call vision with this path to describe it."
            ),
            data={"path": rel, "prompt": prompt},
        )


class _SendSmsSoakStub(_StubTool):
    async def run(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        to = str(kwargs.get("to") or "").strip()
        body = str(kwargs.get("body") or kwargs.get("message") or "").strip()
        if not to:
            return ToolResult(ok=False, output="[fail:send_sms] Missing recipient.")
        if not body:
            return ToolResult(ok=False, output="[fail:send_sms] Missing body.")
        mid = f"msg-{uuid4().hex[:12]}"
        return ToolResult(
            ok=True,
            output=f"Sent SMS to {to} from your phone.",
            data={"to": to, "body": body, "message_id": mid},
        )


class _SendEmailSoakStub(_StubTool):
    async def run(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        to = str(kwargs.get("to") or "").strip()
        subject = str(kwargs.get("subject") or "").strip() or "A message from Arelis"
        body = str(kwargs.get("body") or "").strip()
        attach = str(kwargs.get("attach") or kwargs.get("path") or "").strip()
        if not body and not attach:
            return ToolResult(ok=False, output="[fail:send_email] Missing body.")
        if attach and not Path(attach).is_file() and not (user_data_dir() / attach).is_file():
            # Still OK for soak if path was just generated under outputs/
            pass
        mid = f"mail-{uuid4().hex[:12]}"
        note = f" Attachment: {Path(attach).name}." if attach else ""
        return ToolResult(
            ok=True,
            output=f"Sent email to {to or '(user)'}.{note}",
            data={
                "to": to,
                "subject": subject,
                "body": body,
                "attach": attach,
                "message_id": mid,
            },
        )


def soak_registry(*, image_dir: Path | None = None) -> ToolRegistry:
    """Stateful agenda/image/SMS/email/weather stubs for multi-turn soak."""
    out = ToolRegistry()
    for name, risk in (
        ("web_search", "read"),
        ("web_fetch", "read"),
        ("calculator", "read"),
        ("python", "read"),
        ("workspace", "read"),
        ("git_info", "read"),
        ("recall", "read"),
        ("memory", "side_effect"),
        ("inbox", "read"),
        ("inbound_sms", "read"),
        ("analyze", "read"),
        ("doc_extract", "read"),
        ("tasks", "write"),
        ("goals", "write"),
        ("user_location", "read"),
        ("contacts", "read"),
        ("clipboard", "side_effect"),
        ("ocr", "side_effect"),
        ("camera", "side_effect"),
        ("schedule", "write"),
    ):
        out.register(_StubTool(name, risk=risk))
    out.register(_WeatherSoakStub("weather", risk="read"))
    out.register(_SendSmsSoakStub("send_sms", risk="side_effect"))
    out.register(_SendEmailSoakStub("send_email", risk="side_effect"))
    out.register(_AgendaSoakStub())
    out.register(_FatScrapeStub("scrape", risk="read"))
    out.register(_ResearchReportStub("research_report", risk="read"))
    out.register(_BrowserStub("browser", risk="side_effect"))
    out.register(_VisionStub("vision", risk="side_effect"))
    img_dir = image_dir or (outputs_dir() / "images" / "soak")
    out.register(_ImageSoakStub(img_dir))
    return out


# Every attended tool build_tool_registry can offer. Soak stubs must cover this
# set so a new limb cannot ship without an offline bounce.
SOAK_TOOL_NAMES = frozenset(
    {
        "web_search",
        "web_fetch",
        "scrape",
        "research_report",
        "calculator",
        "python",
        "workspace",
        "git_info",
        "analyze",
        "doc_extract",
        "recall",
        "memory",
        "tasks",
        "goals",
        "contacts",
        "inbox",
        "inbound_sms",
        "send_sms",
        "send_email",
        "agenda",
        "schedule",
        "weather",
        "user_location",
        "clipboard",
        "ocr",
        "camera",
        "image",
        "vision",
        "browser",
    }
)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _score_turn(
    turn: ConversationTurn,
    *,
    tools_called: list[str],
    tool_records: list[ToolCallRecord],
    final_text: str,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if turn.expect_tools:
        if turn.expect_tools_any:
            if not any(t in tools_called for t in turn.expect_tools):
                reasons.append(
                    f"expected one of {turn.expect_tools}, got {tools_called or '-'}"
                )
        else:
            missing = [t for t in turn.expect_tools if t not in tools_called]
            if missing:
                reasons.append(
                    f"missing tools {missing}; got {tools_called or '-'}"
                )
    elif not turn.allow_no_tools and not tools_called:
        # No expectation listed — still OK if allow_no_tools; otherwise soft.
        pass

    if turn.expect_tools and not tools_called and turn.forbid_claim_if_no_tool:
        low = final_text.lower()
        for phrase in turn.forbid_claim_if_no_tool:
            if phrase.lower() in low:
                reasons.append(f"claimed {phrase!r} without tool")

    # Arg checks on first matching expected tool.
    target = None
    for name in turn.expect_tools:
        for rec in tool_records:
            if rec.name == name:
                target = rec
                break
        if target is not None:
            break
    if target is not None:
        for key in turn.require_args:
            if key not in target.args or target.args.get(key) in (None, ""):
                reasons.append(f"missing arg {key!r} on {target.name}")
        for key, needle in turn.expect_args.items():
            raw = str(target.args.get(key) or "")
            if needle.lower() not in raw.lower():
                reasons.append(
                    f"arg {key}={raw!r} missing {needle!r} on {target.name}"
                )
        same = [r for r in tool_records if r.name == target.name]
        if target.ok is False and not any(r.ok for r in same):
            reasons.append(f"{target.name} returned ok=False")

    low = final_text.lower()
    for phrase in turn.expect_answer_contains:
        if phrase.lower() not in low:
            reasons.append(f"answer missing {phrase!r}")

    return (not reasons), reasons


class ConversationSession:
    """Shared AgentLoop + memory across soak turns."""

    def __init__(
        self,
        *,
        router: Any,
        tools: ToolRegistry,
        persona: str = "You are Arelis under production tool soak.",
        agent_cfg: dict[str, Any] | None = None,
        auto_allow: bool = True,
    ) -> None:
        self.bus = EventBus()
        self.tools = tools
        self.memory = SessionMemory()
        self.router = router
        cfg = {
            "max_rounds": 8,
            "tool_output_chars": 8000,
            "tool_summary_inject": True,
            "confirm_writes": True,
            "confirm_image": True,
            "confirm_send": True,
            "confirm_browser": True,
            "confirm_vision": True,
            "confirm_run": True,
            "json_fallback": True,
            "skill_cards": True,
            "intent_preflight": True,
            "lessons": True,
            "sms_force_call": True,
            "email_force_call": True,
            "agenda_force_call": True,
            "image_force_call": True,
            "weather_force_call": True,
            "exactness": True,
            "numeric_gate": True,
            "evidence_gate": False,
            "research_dual_hit": False,
            "chat_fast_path": True,
            "turn_telemetry": True,
            "mid_turn_escalate": False,
            "skill_tool_subset": True,
            "read_fanout": True,
        }
        if agent_cfg:
            cfg.update(agent_cfg)

        async def _confirm(*_a: Any, **_k: Any) -> str:
            return "allow" if auto_allow else "skip"

        self._cap: dict[str, Any] = {
            "t0": 0.0,
            "first_paint_ms": None,
            "tools": [],
            "tool_records": [],
            "thinking": [],
            "final": "",
            "pending_args": {},
        }

        async def on_delta(event: Event) -> None:
            if self._cap["first_paint_ms"] is None:
                self._cap["first_paint_ms"] = int(
                    (time.perf_counter() - float(self._cap["t0"])) * 1000
                )

        async def on_tool_start(event: Event) -> None:
            name = str((event.payload or {}).get("tool") or "")
            args = dict((event.payload or {}).get("args") or {})
            if name:
                self._cap["tools"].append(name)
                self._cap["pending_args"][name] = args
                self._cap["tool_records"].append(
                    ToolCallRecord(name=name, args=args)
                )

        async def on_tool_result(event: Event) -> None:
            name = str((event.payload or {}).get("tool") or "")
            ok = (event.payload or {}).get("ok")
            ms = int((event.payload or {}).get("ms") or 0)
            out = str((event.payload or {}).get("output") or "")[:200]
            for rec in reversed(self._cap["tool_records"]):
                if rec.name == name and rec.ok is None:
                    rec.ok = bool(ok) if ok is not None else None
                    rec.ms = ms
                    rec.output_head = out
                    break

        async def on_thinking(event: Event) -> None:
            text = str((event.payload or {}).get("text") or "")
            if text:
                self._cap["thinking"].append(text)

        async def on_done(event: Event) -> None:
            self._cap["final"] = str((event.payload or {}).get("text") or "")

        async def on_retract(_event: Event) -> None:
            return None

        self.bus.subscribe(EventType.ASSISTANT_DELTA, on_delta)
        self.bus.subscribe(EventType.TOOL_START, on_tool_start)
        self.bus.subscribe(EventType.TOOL_RESULT, on_tool_result)
        self.bus.subscribe(EventType.THINKING, on_thinking)
        self.bus.subscribe(EventType.ASSISTANT_DONE, on_done)
        self.bus.subscribe(EventType.ASSISTANT_RETRACT, on_retract)

        self.loop = AgentLoop(
            self.bus,
            router,
            tools,
            self.memory,
            persona=persona,
            # The shipped window, not a number of its own — see harness.py.
            config={"agent": cfg, "ollama": {"num_ctx": shipped_num_ctx()}},
            request_confirm=_confirm,
            is_cancelled=lambda: False,
        )
        self._bus_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> ConversationSession:
        self._bus_task = asyncio.create_task(self.bus.run())
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.bus.stop()
        if self._bus_task is not None:
            self._bus_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._bus_task

    async def run_turn(self, turn: ConversationTurn) -> TurnReport:
        self._cap["t0"] = time.perf_counter()
        self._cap["first_paint_ms"] = None
        self._cap["tools"] = []
        self._cap["tool_records"] = []
        self._cap["thinking"] = []
        self._cap["final"] = ""
        self._cap["pending_args"] = {}

        await self.loop.run(turn.user, "fast", source="soak")
        await self.bus.drain()

        total_ms = int((time.perf_counter() - float(self._cap["t0"])) * 1000)
        timer = getattr(self.loop, "_timer", None)
        tools_called = list(self._cap["tools"])
        records = list(self._cap["tool_records"])
        final = str(self._cap["final"] or "")
        ok, reasons = _score_turn(
            turn,
            tools_called=tools_called,
            tool_records=records,
            final_text=final,
        )
        return TurnReport(
            turn_id=turn.id,
            user=turn.user,
            ok=ok,
            reasons=reasons,
            tools_called=tools_called,
            tool_calls=records,
            expect_tools=list(turn.expect_tools),
            final_text=final[:500],
            thinking_tail=list(self._cap["thinking"])[-24:],
            total_ms=total_ms,
            model_ms=int(getattr(timer, "model_ms", 0) or 0),
            confirm_ms=int(getattr(timer, "confirm_ms", 0) or 0),
            first_paint_ms=self._cap["first_paint_ms"],
            rounds=int(getattr(timer, "rounds", 0) or 0),
            notes=turn.notes,
        )


class _QueueRouter(_ScriptedRouter):
    """Scripted router whose script queue can grow between turns."""

    def push(self, turn_script: list[list[tuple[str, Any]]]) -> None:
        self.script.extend(turn_script)


def _rewrite_placeholders(
    script: list[list[tuple[str, Any]]],
    *,
    image_path: str = "",
    event_id: str = "",
) -> list[list[tuple[str, Any]]]:
    """Replace {{IMAGE_PATH}} / {{EVENT_ID}} in tool args."""

    def fix_args(args: Any) -> Any:
        if isinstance(args, dict):
            return {k: fix_args(v) for k, v in args.items()}
        if isinstance(args, str):
            out = args
            if image_path:
                out = out.replace("{{IMAGE_PATH}}", image_path)
            if event_id:
                out = out.replace("{{EVENT_ID}}", event_id)
            return out
        return args

    fixed: list[list[tuple[str, Any]]] = []
    for round_steps in script:
        new_round: list[tuple[str, Any]] = []
        for kind, payload in round_steps:
            if kind == "tool_calls" and isinstance(payload, list):
                calls = []
                for call in payload:
                    call = dict(call)
                    fn = dict(call.get("function") or {})
                    fn["arguments"] = fix_args(fn.get("arguments") or {})
                    call["function"] = fn
                    calls.append(call)
                new_round.append((kind, calls))
            else:
                new_round.append((kind, payload))
        fixed.append(new_round)
    return fixed


async def run_conversation_soak(
    turns: list[ConversationTurn],
    *,
    soak_id: str = "tool_bounce",
    mode: str = "mock",
    fail_fast: bool = False,
    live_router: Any | None = None,
    agent_cfg: dict[str, Any] | None = None,
    image_dir: Path | None = None,
) -> SoakReport:
    """Run a multi-turn soak. mode=mock uses queued scripts; live uses Ollama."""
    started = datetime.now(UTC).isoformat()
    t0 = time.perf_counter()
    tools = soak_registry(image_dir=image_dir)
    reports: list[TurnReport] = []

    if mode == "live":
        if live_router is None:
            raise ValueError("live mode requires live_router")
        router: Any = live_router
    else:
        missing = [t.id for t in turns if not t.script]
        if missing:
            raise ValueError(f"mock mode needs scripts for turns: {missing}")
        router = _QueueRouter([])

    async with ConversationSession(
        router=router, tools=tools, agent_cfg=agent_cfg
    ) as session:
        image = session.tools.get("image")
        agenda = session.tools.get("agenda")
        last_image = ""
        last_event_id = ""

        for turn in turns:
            if mode == "mock":
                script = _rewrite_placeholders(
                    list(turn.script),
                    image_path=last_image,
                    event_id=last_event_id,
                )
                # Isolate each turn's script so a short/long prior turn cannot
                # desync the queue for the rest of the soak.
                router.script = script
                router.i = 0

            report = await session.run_turn(turn)
            reports.append(report)

            if image is not None:
                last_image = str(getattr(image, "last_path", "") or last_image)
            if agenda is not None and hasattr(agenda, "events"):
                events = agenda.events or {}
                if events:
                    last_event_id = next(reversed(events))
                # After a successful delete, pick remaining or clear.
                for rec in report.tool_calls:
                    if rec.name == "agenda" and rec.ok:
                        action = str(rec.args.get("action") or "").lower()
                        if action == "create" and isinstance(rec.ok, bool):
                            # Prefer stub state.
                            if events:
                                last_event_id = next(reversed(events))
                        if action == "delete":
                            last_event_id = (
                                next(reversed(events)) if events else ""
                            )

            if not report.ok and fail_fast:
                break

    finished = datetime.now(UTC).isoformat()
    total_ms = int((time.perf_counter() - t0) * 1000)
    ok = all(r.ok for r in reports) and len(reports) == len(turns)
    passed = sum(1 for r in reports if r.ok)
    summary = (
        f"{'PASS' if ok else 'FAIL'}  {passed}/{len(turns)} turns  "
        f"total={total_ms}ms  mode={mode}"
    )
    return SoakReport(
        id=soak_id,
        mode=mode,
        ok=ok,
        started_at=started,
        finished_at=finished,
        total_ms=total_ms,
        turns=reports,
        summary=summary,
    )
