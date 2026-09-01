"""Run foundation scenarios against a scripted (or live) model."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from arelis.config import shipped_num_ctx
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.preflight import detect_intents
from arelis.core.skills import select_skill_ids
from arelis.eval.scenarios import SCENARIOS, Scenario
from arelis.tools.base import ToolRegistry, ToolResult


@dataclass
class EvalResult:
    scenario_id: str
    ok: bool
    reasons: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    first_args: dict[str, Any] = field(default_factory=dict)
    final_text: str = ""
    skill_ids: list[str] = field(default_factory=list)
    preflight_kinds: list[str] = field(default_factory=list)
    model_switches: list[dict[str, Any]] = field(default_factory=list)


# Declared parameters of the real tools, mirrored so a stub presents the surface
# the model actually sees. These were open schemas ({} with additionalProperties),
# which read to cross_tool_arg_error as "this tool accepts nothing" and rejected
# every argument of every scripted call — 15 tests dark, and a gate the eval could
# not see. tests/test_eval_stub_schemas.py fails when this drifts from the
# registry, because a stub that lies is worse than no stub.
_STUB_SCHEMAS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "agenda": (
        ("action",),
        (
            "action", "all_day", "calendar_id", "description", "end", "event_id",
            "keep", "location", "provider", "start", "summary",
        ),
    ),
    "analyze": (("path",), ("action", "path", "rows")),
    "browser": (
        ("action",),
        (
            "action", "amount", "browser", "date", "destination", "direction",
            "focus", "full_page", "into", "key", "mode", "name", "notes", "nth",
            "origin", "party", "phone", "place", "private", "query", "ref",
            "seconds", "select", "site", "tab", "target", "text", "time", "url",
        ),
    ),
    "calculator": (("expression",), ("expression",)),
    "python": (("code",), ("code", "source", "script")),
    "cas": (
        ("expr",),
        ("action", "expr", "hi", "lo", "n", "symbol", "wrt"),
    ),
    "diagnostics": ((), ("suite",)),
    "units": (("action",), ("action", "name", "quantity", "to")),
    "plot": (
        (),
        ("action", "out", "path", "title", "x", "xlabel", "xs", "y", "ylabel", "ys"),
    ),
    "document": (
        ("format",),
        ("body", "filename", "format", "from_path", "replace", "rows", "title"),
    ),
    "catalog": (
        ("action",),
        ("action", "date", "query", "table", "target"),
    ),
    "solar": (
        ("action",),
        (
            "action", "date", "dvx", "dvy", "dvz", "epoch_gyr", "flag", "name",
            "r1_au", "r2_au", "rate", "refresh", "tracers",
        ),
    ),
    "earth": (
        ("action",),
        ("action", "id", "layer", "on", "query"),
    ),
    "camera": (("action",), ("action",)),
    "doc_extract": (("path",), ("max_chars", "page_end", "page_start", "path")),
    "git_info": ((), ("action", "max_chars", "n", "path")),
    "goals": (
        ("action",),
        ("action", "horizon", "id", "kind", "limit", "notes", "status", "title"),
    ),
    "inbound_sms": ((), ("limit",)),
    "inbox": (
        ("action",),
        (
            "action", "id", "limit", "sender", "since", "subject", "text",
            "unread_only",
        ),
    ),
    "memory": (
        ("action",),
        ("action", "fact", "key", "project", "summary", "text", "type", "value"),
    ),
    "ocr": (("action",), ("action", "lang", "path")),
    "recall": (
        ("action",),
        ("action", "limit", "offset", "page", "query", "session_id", "source"),
    ),
    "research_report": (("query",), ("max_sources", "query", "recency")),
    "scrape": (("url",), ("max_chars", "url")),
    "send_email": (
        ("body", "subject"),
        ("attach", "body", "path", "subject", "to"),
    ),
    "send_sms": (("body", "to"), ("body", "to")),
    "tasks": (
        ("action",),
        ("action", "due", "goal_id", "id", "limit", "status", "title"),
    ),
    "user_location": ((), ("refresh",)),
    "vision": (("path",), ("path", "question")),
    "weather": ((), ("days", "place")),
    "web_fetch": (("url",), ("max_chars", "url")),
    "web_search": (("query",), ("max_results", "query", "recency")),
    "workspace": (
        ("action",),
        ("action", "content", "max_chars", "new", "old", "path", "text", "title"),
    ),
}


def stub_schema(name: str) -> dict[str, Any]:
    """Schema for a stub: the real tool's declared parameters where known.

    Falls back to an open schema for a name with no real counterpart, which is
    what the growth-track stubs were before any of them shipped.
    """
    entry = _STUB_SCHEMAS.get(name)
    if entry is None:
        return {"type": "object", "properties": {}, "additionalProperties": True}
    required, props = entry
    return {
        "type": "object",
        "properties": {key: {"type": "string"} for key in props},
        "required": list(required),
    }


def parse_agent_overrides(raw: str) -> dict[str, Any]:
    """Read ``--agent-json`` as JSON, or as ``key=value`` pairs.

    The second form exists because this repo is driven from PowerShell, which
    strips the inner double quotes out of ``'{"gate": false}'`` before the
    interpreter ever sees it. That failure is silent-looking — the flag appears
    to be accepted and the board comes back unchanged — so the shorthand is
    worth the few lines. ``gate=false,other=2`` needs no quoting anywhere.

    Raises ValueError with the offending text; a mistyped override that ran as
    a baseline would quietly answer the wrong question.
    """
    text = (raw or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("agent overrides must be a JSON object")
        return parsed

    out: dict[str, Any] = {}
    for chunk in text.split(","):
        pair = chunk.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ValueError(f"expected key=value, got {pair!r}")
        key, _, value = pair.partition("=")
        token = value.strip()
        low = token.lower()
        if low in {"true", "false"}:
            out[key.strip()] = low == "true"
        elif low in {"none", "null"}:
            out[key.strip()] = None
        else:
            try:
                out[key.strip()] = int(token)
            except ValueError:
                try:
                    out[key.strip()] = float(token)
                except ValueError:
                    out[key.strip()] = token
    return out


class _StubTool:
    def __init__(self, name: str, *, risk: str = "read") -> None:
        self.name = name
        self.description = name
        self.risk = risk
        self.parameters_schema: dict[str, Any] = stub_schema(name)
        self.calls: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        return ToolResult(ok=True, output=f"{self.name} ok", data=dict(kwargs))


class _FatScrapeStub(_StubTool):
    """Returns a long page body so tool_summary / truncation paths exercise offline."""

    async def run(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        url = str(kwargs.get("url") or "https://example.com/long").strip()
        lines: list[str] = [
            "# Long example article",
            "",
            "Lead paragraph with enough prose for summary extraction offline.",
            "",
        ]
        for i in range(60):
            lines.append(
                f"- Bullet {i}: concrete finding about topic {i} with supporting detail."
            )
            lines.append(
                f"Paragraph {i} expands the point with context, numbers, and caveats "
                f"so the body stays well above the fat-tool threshold."
            )
            lines.append("")
        body = "\n".join(lines)
        while len(body) < 3000:
            body += "\nExtra padding line for offline fat scrape evaluation.\n"
        return ToolResult(
            ok=True,
            output=body,
            data={"title": "Long Example Page", "url": url},
        )


class _ResearchReportStub(_StubTool):
    """Returns multi-source web warrants so research finish gates can pass."""

    async def run(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        query = str(kwargs.get("query") or "")
        sources = [
            {"title": "Source A", "url": "https://example.com/a"},
            {"title": "Source B", "url": "https://example.com/b"},
        ]
        body = (
            f"# Research report\n\n## Question\n{query}\n\n"
            "## Findings\n- Stub finding from Source A.\n"
            "- Stub finding from Source B.\n\n"
            "## Uncertainties\n- Offline stub.\n\n"
            "## Sources\n1. Source A — https://example.com/a\n"
            "2. Source B — https://example.com/b\n"
        )
        path = "outputs/research/eval-stub.md"
        body = body + f"\n\nSaved: {path}\n"
        return ToolResult(
            ok=True,
            output=body,
            data={
                "query": query,
                "ok_count": 2,
                "sources": sources,
                "path": path,
            },
        )


class _BrowserStub(_StubTool):
    """Offline browser tool: open/navigate succeed without a real Chrome."""

    async def run(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        action = str(kwargs.get("action") or "open").strip().lower()
        target = str(kwargs.get("url") or kwargs.get("target") or "").strip()
        if action == "relaunch":
            return ToolResult(
                ok=True,
                output="Connected to chrome (relaunch).",
                data={"mode": "relaunch", "browser": "chrome"},
            )
        if action in {"open", "navigate"}:
            url = target or "https://www.youtube.com"
            if not url.startswith("http"):
                url = "https://www.youtube.com"
            return ToolResult(
                ok=True,
                output=(
                    f"Opened {url}\n\ntitle: Stub Page\nurl: {url}\nelements:\n"
                    f"[e1] a role=link 'Home'"
                ),
                data={"url": url, "mode": "attach", "title": "Stub Page"},
            )
        if action == "snapshot":
            return ToolResult(
                ok=True,
                output="title: Stub\nurl: https://example.com\nelements:\n[e1] a 'Home'",
                data={"refs": ["e1"], "mode": "attach"},
            )
        if action == "screenshot":
            path = "outputs/images/browser_stub.png"
            return ToolResult(
                ok=True,
                output=(
                    "Screenshot saved (viewport).\n"
                    f"Saved: {path}\n"
                    "Call vision with this path to describe what is on screen."
                ),
                data={
                    "path": path,
                    "url": "https://example.com",
                    "title": "Stub",
                    "full_page": bool(kwargs.get("full_page")),
                    "mode": "attach",
                },
            )
        if action == "read":
            return ToolResult(
                ok=True,
                output=(
                    "title: Stub Page\n"
                    "url: https://example.com\n"
                    "heading: Welcome\n"
                    "body: Compact visible text of the tab she is on."
                ),
                data={"url": "https://example.com", "title": "Stub Page", "mode": "attach"},
            )
        if action == "maps":
            dest = str(kwargs.get("destination") or kwargs.get("query") or "there")
            return ToolResult(
                ok=True,
                output=(
                    f"Opened Maps directions to {dest}.\n"
                    "Phone link: https://maps.google.com/?daddr=there"
                ),
                data={"destination": dest, "mode": "attach"},
            )
        if action == "search":
            query = str(kwargs.get("query") or "").strip()
            site = str(kwargs.get("site") or "google")
            return ToolResult(
                ok=True,
                output=f"Opened {site} search for {query}.",
                data={"query": query, "site": site, "mode": "attach"},
            )
        if action == "reserve":
            place = str(
                kwargs.get("place") or kwargs.get("query") or "the place"
            ).strip()
            return ToolResult(
                ok=True,
                output=(
                    f"Opened reservation search for {place}.\n"
                    "You click Book / Reserve. I stop on that screen."
                ),
                data={"place": place, "mode": "attach", **kwargs},
            )
        return ToolResult(
            ok=True,
            output=f"browser {action} ok",
            data={"mode": "attach", **kwargs},
        )


class _VisionStub(_StubTool):
    """Offline vision: fixed caption without loading a VL model."""

    async def run(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        path = str(kwargs.get("path") or "outputs/images/demo.png").strip()
        caption = "Stub vision: a simple demo diagram with three labeled boxes."
        return ToolResult(
            ok=True,
            output=caption,
            data={
                "path": path,
                "model": "eval-vision",
                "answer_len": len(caption),
                "answer_hash": "evalstub0001",
            },
        )


class _OcrStub(_StubTool):
    """Offline OCR: clean print so Read accepts without VL."""

    async def run(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        path = str(kwargs.get("path") or "outputs/images/camera_eval.jpg").strip()
        needle = path.replace("\\", "/").lower()
        name = needle.rsplit("/", 1)[-1]
        if any(tag in needle for tag in ("blur", "empty", "hand")):
            return ToolResult(
                ok=True,
                output=(
                    f"OCR found no readable text in {name}. "
                    "Try vision for a description, or a sharper screenshot."
                ),
                data={
                    "path": path,
                    "chars": 0,
                    "empty": True,
                    "mean_conf": None,
                    "word_count": 0,
                    "action": str(kwargs.get("action") or "text"),
                },
            )
        body = "INGREDIENTS: water, sugar, salt"
        return ToolResult(
            ok=True,
            output=f"OCR text from {name} ({len(body)} chars):\n{body}",
            data={
                "path": path,
                "chars": len(body),
                "empty": False,
                "mean_conf": 88.0,
                "word_count": 4,
                "action": str(kwargs.get("action") or "text"),
            },
        )


class _CameraStub(_StubTool):
    """Offline camera: one still path, no hardware."""

    async def run(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        path = "outputs/images/camera_eval.jpg"
        return ToolResult(
            ok=True,
            output=f"Saved camera frame to {path}. Call vision with path={path}.",
            data={"path": path},
        )


class _ScriptedRouter:
    """Offline router with distinct role→model names so MODEL_SWITCH looks real."""

    def __init__(
        self,
        script: list[list[tuple[str, Any]]],
        model: str = "eval-fast",
    ) -> None:
        self.script = script
        self.i = 0
        self.models = {
            "fast": "eval-fast",
            "research": "eval-research",
            "code": "eval-code",
        }
        self.default_role = "fast"
        self.active_role = "fast"
        self.active_model = model if model in self.models.values() else self.models["fast"]

    def model_for(self, role=None) -> str:
        wanted = role or self.default_role
        return self.models.get(str(wanted), self.active_model or self.models["fast"])

    async def ensure_role(self, role, *, force: bool = False) -> str:
        del force
        model = self.model_for(role)
        self.active_role = role
        self.active_model = model
        return model

    def mark_sticky(self, role) -> None:
        return None

    def clear_sticky(self) -> None:
        return None

    def apply_sticky(self, wanted, reason: str):
        return wanted, reason

    async def stream(
        self, role, messages, *, options=None, tools=None, force: bool = False
    ) -> AsyncIterator[tuple[str, Any]]:
        del force
        if self.i >= len(self.script):
            yield ("token", "done")
            return
        steps = self.script[self.i]
        self.i += 1
        for item in steps:
            yield item


def foundation_registry() -> ToolRegistry:
    reg = ToolRegistry()
    for name, risk in (
        ("weather", "read"),
        ("web_search", "read"),
        ("web_fetch", "read"),
        ("send_sms", "side_effect"),
        ("calculator", "read"),
        ("python", "read"),
        ("diagnostics", "read"),
        ("cas", "read"),
        ("units", "read"),
        ("plot", "write"),
        ("document", "write"),
        ("catalog", "read"),
        ("workspace", "read"),
        ("git_info", "read"),
        ("recall", "read"),
        ("memory", "side_effect"),
        ("inbox", "read"),
        ("inbound_sms", "read"),
        ("send_email", "side_effect"),
        # Growth-track stubs (T2-T5): scenarios can call these before real tools land.
        ("analyze", "read"),
        ("agenda", "read"),
        ("doc_extract", "read"),
        ("tasks", "write"),
        ("goals", "write"),
        ("user_location", "read"),
    ):
        reg.register(_StubTool(name, risk=risk))
    reg.register(_FatScrapeStub("scrape", risk="read"))
    reg.register(_ResearchReportStub("research_report", risk="read"))
    reg.register(_BrowserStub("browser", risk="side_effect"))
    reg.register(_VisionStub("vision", risk="side_effect"))
    reg.register(_OcrStub("ocr", risk="side_effect"))
    reg.register(_CameraStub("camera", risk="side_effect"))
    return reg


def _result_tool_name(scenario: Scenario) -> str:
    if scenario.expect_tool_result_tool:
        return scenario.expect_tool_result_tool
    if scenario.expect_tools:
        return scenario.expect_tools[0]
    return "scrape"


async def run_scripted_scenario(
    scenario: Scenario,
    *,
    confirm: str = "allow",
    agent_overrides: dict[str, Any] | None = None,
) -> EvalResult:
    """Offline: scripted model + stub tools. Scores tool choice and claims.

    ``agent_overrides`` wins over ``scenario.agent_config`` so a gate can be
    turned off across the whole board from one command line. Answering "does the
    7B still need this mechanism" needs the board with the gate off, and until
    now only a scenario could ask for that, one scenario at a time.
    """
    if not scenario.script:
        return EvalResult(
            scenario_id=scenario.id,
            ok=False,
            reasons=["scenario has no offline script"],
        )

    bus = EventBus()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    for et in (
        EventType.TOOL_START,
        EventType.TOOL_RESULT,
        EventType.ASSISTANT_DONE,
        EventType.ERROR,
        EventType.MODEL_SWITCH,
    ):
        bus.subscribe(et, capture)

    tools = foundation_registry()
    router = _ScriptedRouter(scenario.script)
    memory = SessionMemory()
    confirms: list[str] = []

    async def _confirm(_cid: Any, tool: str, *_a: Any, **_k: Any) -> str:
        confirms.append(str(tool or ""))
        return confirm

    agent_cfg: dict[str, Any] = {
        "max_rounds": 6,
        "tool_output_chars": 4000,
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
        "scrape_after_search": True,
        "sms_force_call": True,
        "email_force_call": True,
        "exactness": True,
        "numeric_gate": True,
        "evidence_gate": True,
        "research_dual_hit": True,
        "research_max_rounds": 12,
        "research_min_sources": 2,
        "research_tool_subset": True,
        "skill_tool_subset": True,
        "read_fanout": True,
        "turn_telemetry": False,
    }
    agent_cfg.update(scenario.agent_config)
    if agent_overrides:
        agent_cfg.update(agent_overrides)

    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        memory,
        persona="You are Arelis under eval.",
        config={
            "agent": agent_cfg,
            # The shipped window, not a number of its own. An eval pinned to a
            # window nobody runs is not measuring the product.
            "ollama": {"num_ctx": shipped_num_ctx()},
        },
        request_confirm=_confirm,
        is_cancelled=lambda: False,
    )

    skill_ids = select_skill_ids(scenario.user, available_tools=set(tools.names()))
    preflight_kinds = [h.kind for h in detect_intents(scenario.user)]

    # EventBus only dispatches while run() is pumping the queue.
    bus_task = asyncio.create_task(bus.run())
    try:
        await loop.run(scenario.user, "fast", source="eval")
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
        try:
            await bus_task
        except asyncio.CancelledError:
            pass

    starts = [e for e in events if e.type == EventType.TOOL_START]
    tools_called = [str(e.payload.get("tool") or "") for e in starts]
    first_args: dict[str, Any] = {}
    if starts:
        raw_args = starts[0].payload.get("args") or {}
        if isinstance(raw_args, dict):
            first_args = dict(raw_args)

    done = next((e for e in events if e.type == EventType.ASSISTANT_DONE), None)
    final = str((done.payload.get("text") if done else "") or "")
    reasons: list[str] = []

    if not tools_called:
        if not scenario.allow_no_tools:
            reasons.append("no tool calls")
    else:
        expected = set(scenario.expect_tools)
        if expected and tools_called[0] not in expected:
            reasons.append(
                f"first tool {tools_called[0]!r} not in {sorted(expected)}"
            )
        # Multi-expect: every listed tool must appear (order still checked via first),
        # unless expect_tools_any (OR set — e.g. agenda or briefing).
        if len(scenario.expect_tools) > 1 and not scenario.expect_tools_any:
            missing = [t for t in scenario.expect_tools if t not in tools_called]
            if missing:
                reasons.append(f"missing tools: {missing}")

    for want in scenario.expect_confirm_tools:
        if want not in confirms:
            reasons.append(f"expected Allow for {want!r} (got {confirms})")

    lowered_final = final.lower()
    for phrase in scenario.expect_answer_contains:
        if phrase.lower() not in lowered_final:
            reasons.append(f"missing answer phrase {phrase!r}")

    match_args = first_args
    for e in starts:
        if e.payload.get("tool") in scenario.expect_tools:
            cand = e.payload.get("args") or {}
            if isinstance(cand, dict):
                match_args = cand
                break

    for key in scenario.require_args:
        if key not in match_args or match_args.get(key) in (None, ""):
            reasons.append(f"missing arg {key!r}")

    for key, want in scenario.expect_args.items():
        got = str(match_args.get(key) or "")
        if want.lower() not in got.lower():
            reasons.append(f"arg {key!r} missing {want!r} (got {got!r})")

    ok_results = {
        str(e.payload.get("tool"))
        for e in events
        if e.type == EventType.TOOL_RESULT and e.payload.get("ok")
    }
    if not ok_results:
        lowered = final.lower()
        for phrase in scenario.forbid_claim_if_no_tool:
            if phrase.lower() in lowered:
                reasons.append(f"claimed {phrase!r} without successful tool")

    # Scrape URL hygiene when scrape ran.
    for e in starts:
        if e.payload.get("tool") != "scrape":
            continue
        args = e.payload.get("args") or {}
        url = str(args.get("url") or "")
        if url and not url.startswith(("http://", "https://")):
            reasons.append(f"scrape url is not http(s): {url!r}")

    result_tool = _result_tool_name(scenario)
    tool_results = [
        e
        for e in events
        if e.type == EventType.TOOL_RESULT and e.payload.get("tool") == result_tool
    ]
    if scenario.expect_tool_result_contains:
        blob = "\n".join(str(e.payload.get("output") or "") for e in tool_results)
        if not tool_results:
            reasons.append(f"no TOOL_RESULT for {result_tool!r}")
        else:
            for phrase in scenario.expect_tool_result_contains:
                if phrase not in blob:
                    reasons.append(
                        f"TOOL_RESULT for {result_tool!r} missing {phrase!r}"
                    )

    if scenario.expect_truncated is not None:
        if not tool_results:
            reasons.append(f"no TOOL_RESULT for {result_tool!r} (truncation check)")
        else:
            flagged = any(bool(e.payload.get("truncated")) for e in tool_results)
            # prepare_tool_output may shrink the card before the hard cap; treat
            # the summary-card marker as truncation evidence too.
            marked = any(
                "truncated" in str(e.payload.get("output") or "").lower()
                for e in tool_results
            )
            saw = flagged or marked
            if scenario.expect_truncated and not saw:
                reasons.append(
                    f"expected truncated TOOL_RESULT for {result_tool!r}"
                )
            if scenario.expect_truncated is False and flagged:
                reasons.append(
                    f"unexpected truncated TOOL_RESULT for {result_tool!r}"
                )

    model_switches = [
        dict(e.payload)
        for e in events
        if e.type == EventType.MODEL_SWITCH
    ]
    if scenario.expect_model_switch_reason:
        want_reason = scenario.expect_model_switch_reason
        matched = [
            sw
            for sw in model_switches
            if str(sw.get("reason") or "") == want_reason
        ]
        if not matched:
            reasons.append(
                f"missing MODEL_SWITCH reason={want_reason!r} "
                f"(saw {[sw.get('reason') for sw in model_switches]})"
            )
        elif scenario.expect_escalate_to_role:
            want_role = scenario.expect_escalate_to_role
            if not any(str(sw.get("role") or "") == want_role for sw in matched):
                reasons.append(
                    f"MODEL_SWITCH reason={want_reason!r} missing role="
                    f"{want_role!r} (saw {[sw.get('role') for sw in matched]})"
                )
            # Distinct from/to makes the switch look like a real role pin.
            if not any(
                str(sw.get("from") or "")
                and str(sw.get("to") or "")
                and str(sw.get("from")) != str(sw.get("to"))
                for sw in matched
                if str(sw.get("role") or "") == want_role
            ):
                reasons.append(
                    f"MODEL_SWITCH to {want_role!r} did not change model "
                    f"(from==to)"
                )

    return EvalResult(
        scenario_id=scenario.id,
        ok=not reasons,
        reasons=reasons,
        tools_called=tools_called,
        first_args=first_args,
        final_text=final,
        skill_ids=skill_ids,
        preflight_kinds=preflight_kinds,
        model_switches=model_switches,
    )


async def run_all_scripted(
    *, agent_overrides: dict[str, Any] | None = None
) -> list[EvalResult]:
    return [
        await run_scripted_scenario(s, agent_overrides=agent_overrides)
        for s in SCENARIOS
        if s.script
    ]
