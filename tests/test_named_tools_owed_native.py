"""Native tool-calling must still honor named_tools_owed on multi-tool chains.

Matrix C01/C02/P09/P10 failed with native_tool_calling on: first tool ran,
tools were stripped, later named tools rejected as Unknown tool.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from arelis.config import shipped_num_ctx
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.eval.harness import _FailingStub, _ScriptedRouter, _StubTool, foundation_registry
from arelis.paths import outputs_dir
from arelis.tools.base import ToolRegistry, ToolResult
from arelis.tools.document import DocumentTool
from tests.test_no_call_path import _ctx, _FakeLoop, _scratch

_C17_RESEARCH_PDF = (
    "Write a sourced research report on how solid-state batteries differ "
    "from lithium-ion batteries, then convert that report to a PDF with "
    "the document tool."
)

pytestmark = pytest.mark.no_ui

_NATIVE = {
    "max_rounds": 6,
    "exactness": True,
    "numeric_gate": True,
    "evidence_gate": True,
    "native_tool_calling": True,
}

_FLAG_OFF = {
    "max_rounds": 6,
    "exactness": True,
    "numeric_gate": True,
    "evidence_gate": True,
    "native_tool_calling": False,
}

_OWED_NUDGE = "named tools owed; asking to continue"


def _tools_registry(tools_list: list[str]) -> ToolRegistry:
    full = foundation_registry()
    reg = ToolRegistry()
    for name in tools_list:
        tool = full.get(name)
        assert tool is not None, name
        reg.register(tool)
    return reg


async def _allow(*_args, **_kwargs) -> str:
    return "allow"


async def _run_agent_with_script(
    text: str,
    script: list[list[tuple[str, object]]],
    tools_list: list[str],
    agent_cfg: dict,
    *,
    registry: ToolRegistry | None = None,
    capture_thinking: bool = False,
    extras: dict | None = None,
) -> tuple[str, list[tuple[str, bool]], list[str]]:
    router = _ScriptedRouter(script)
    tools = registry if registry is not None else _tools_registry(tools_list)
    bus = EventBus()
    memory = SessionMemory()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    watch = [EventType.TOOL_START, EventType.TOOL_RESULT, EventType.ASSISTANT_DONE]
    if capture_thinking:
        watch.append(EventType.THINKING)
    for et in watch:
        bus.subscribe(et, capture)

    loop = AgentLoop(
        bus,
        router,
        tools,
        memory,
        persona="You are Arelis under eval.",
        config={
            "agent": agent_cfg,
            "ollama": {"num_ctx": shipped_num_ctx()},
        },
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )

    bus_task = asyncio.create_task(bus.run())
    try:
        await loop.run(text, "fast", source="eval")
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
        try:
            await bus_task
        except asyncio.CancelledError:
            pass

    tool_results = [
        (e.payload.get("tool", "?"), e.payload.get("ok", False))
        for e in events
        if e.type == EventType.TOOL_RESULT
    ]
    thinking = [str(e.payload.get("text") or "") for e in events if e.type == EventType.THINKING]
    done = next((e for e in events if e.type == EventType.ASSISTANT_DONE), None)
    final_text = str((done.payload.get("text") if done else "") or "")
    if extras is not None:
        extras["messages"] = list(getattr(loop, "_last_sent_messages", None) or [])
        extras["max_rounds"] = loop.max_rounds
    return final_text, tool_results, thinking


def _call(name: str, args: dict) -> list[tuple[str, object]]:
    return [
        (
            "tool_calls",
            [{"type": "function", "function": {"name": name, "arguments": args}}],
        )
    ]


class _ResolvedWeather(_StubTool):
    """Forecast stub whose data.place is the city the code resolved."""

    async def run(self, **kwargs: object) -> ToolResult:
        self.calls.append(dict(kwargs))
        return ToolResult(
            ok=True,
            output="Springfield, Illinois: 61\u00b0F and overcast, high 66\u00b0F, low 48\u00b0F.",
            data={"place": "Springfield, Illinois"},
        )


def test_native_twice_failed_exemption_skips_owed_nudge() -> None:
    """After two identical document failures, native owed-nudge must not fire again."""
    reg = ToolRegistry()
    full = foundation_registry()
    weather = full.get("weather")
    assert weather is not None
    reg.register(weather)
    reg.register(_FailingStub("document", risk="write"))

    args = {
        "format": "md",
        "title": "Springfield Weather Brief",
        "body": "Sunny.",
    }
    script = [
        _call("weather", {"place": "Springfield, Illinois"}),
        _call("document", args),
        _call("document", args),
        [("token", "Could not save the brief; weather was sunny.")],
        [("token", "Still done after second failure.")],
        [("token", "Extra answer should not be needed.")],
    ]
    final_text, tool_results, thinking = asyncio.run(
        _run_agent_with_script(
            "Call the weather tool for Springfield, Illinois. Then call the document "
            "tool with format=md and title Springfield Weather Brief and a body "
            "summarizing the forecast.",
            script,
            ["weather", "document"],
            {**_NATIVE, "max_rounds": 6},
            registry=reg,
            capture_thinking=True,
        )
    )
    assert tool_results[0] == ("weather", True), tool_results
    doc_fails = [ok for n, ok in tool_results if n == "document"]
    assert doc_fails == [False, False], tool_results
    assert final_text.strip(), "turn must finish with an answer"

    # Index of second document failure among captured events is implicit in
    # tool_results order; any owed-nudge after that point means the exemption
    # in named_tools_owed_runnable was skipped.
    # With the script always calling tools until the text answer, the first
    # finish-path hit is after both failures — so zero owed-nudges is required.
    owed_nudges = [t for t in thinking if _OWED_NUDGE in t]
    assert owed_nudges == [], thinking
    assert "Could not save" in final_text or "sunny" in final_text.lower()


_C02_WEATHER_DOCUMENT = (
    "Get today's weather forecast for Springfield, Illinois, then save a "
    "one-paragraph summary of it as a markdown document titled Springfield Weather Brief."
)


class _AmbiguousWeather(_StubTool):
    """A bare Springfield resolves to one gazetteer label, not the typed string."""

    async def run(self, **kwargs: object) -> ToolResult:
        self.calls.append(dict(kwargs))
        place = "Springfield Station"
        output = (
            f"Place: {place}\n"
            "That name also matched: Springfield, Illinois. "
            f"Say which one if {place} is not the one you meant.\n"
            "Now: 72F"
        )
        return ToolResult(
            ok=True,
            output=output,
            data={
                "place": place,
                "ambiguous": True,
                "alternatives": ["Springfield, Illinois"],
            },
        )


def _ambiguous_weather_registry() -> ToolRegistry:
    full = foundation_registry()
    reg = ToolRegistry()
    reg.register(_AmbiguousWeather("weather", risk="read"))
    document = full.get("document")
    assert document is not None
    reg.register(document)
    return reg


def _ambiguous_weather_writing_registry() -> ToolRegistry:
    """Real document tool so a held turn can write the brief to disk."""
    reg = ToolRegistry()
    reg.register(_AmbiguousWeather("weather", risk="read"))
    reg.register(DocumentTool())
    return reg


_WEATHER_RESULT_TEXT = (
    "Place: Springfield Station\n"
    "That name also matched: Springfield, Illinois. "
    "Say which one if Springfield Station is not the one you meant.\n"
    "Now: 72F"
)


def _not_run_tool_messages(messages: list[dict]) -> list[str]:
    return [
        str(message.get("content") or "")
        for message in messages
        if message.get("role") == "tool" and "did not run" in str(message.get("content") or "").lower()
    ]


def test_flag_off_need_place_blocked_weather_still_runs_document() -> None:
    """C02: a second weather call runs, and document still runs after it.

    There is no once-guard. Both weather calls execute. Document runs on
    the next step. The turn stays under the step limit.
    """
    script = [
        _call("weather", {"place": "Springfield"}),
        _call("weather", {"place": "Springfield"}),
        _call(
            "document",
            {
                "format": "md",
                "title": "Springfield Weather Brief",
                "body": "Sunny at Springfield Station.",
            },
        ),
        [("token", "Saved Springfield Weather Brief.md")],
    ]
    extras: dict = {}
    final_text, tool_results, thinking = asyncio.run(
        _run_agent_with_script(
            _C02_WEATHER_DOCUMENT,
            script,
            ["weather", "document"],
            {**_FLAG_OFF, "max_rounds": 8},
            registry=_ambiguous_weather_registry(),
            capture_thinking=True,
            extras=extras,
        )
    )
    assert [name for name, _ok in tool_results] == [
        "weather",
        "weather",
        "document",
    ], tool_results
    assert all(ok for _name, ok in tool_results)
    assert _not_run_tool_messages(extras["messages"]) == []
    assert not any("max rounds" in line for line in thinking), thinking
    assert "tool-step limit" not in final_text.lower()
    assert "springfield" in final_text.lower()


def _brief_path(title: str) -> Path:
    stem = title.replace(" ", "-")
    matches = sorted((outputs_dir() / "documents").glob(f"{stem}*.md"))
    assert matches, f"no file for {title}"
    return matches[-1]


def test_failed_lookup_then_invented_forecast_is_refused() -> None:
    """A failed lookup does not let an invented temperature through."""
    sentence = "I couldn't get the forecast for Paris."
    invented = "It is 72F and sunny in Paris, high 75."

    class _MissWeather(_StubTool):
        async def run(self, **kwargs: object) -> ToolResult:
            self.calls.append(dict(kwargs))
            return ToolResult(ok=False, output=sentence)

    weather = _MissWeather("weather", risk="read")
    reg = ToolRegistry()
    reg.register(weather)
    script = [
        _call("weather", {"place": "Paris"}),
        _call("weather", {"place": "Paris"}),
        [("token", invented)],
    ]
    final_text, tool_results, thinking = asyncio.run(
        _run_agent_with_script(
            "What is the weather in Paris?",
            script,
            ["weather"],
            {**_FLAG_OFF, "max_rounds": 8},
            registry=reg,
            capture_thinking=True,
        )
    )
    assert tool_results == [("weather", False), ("weather", False)], tool_results
    assert invented not in final_text
    assert final_text.strip() == (
        "I don't know. I don't have a forecast for that, so I won't guess."
    )
    assert not any("max rounds" in line for line in thinking), thinking


def test_failure_sentence_plus_a_forecast_is_refused() -> None:
    """The failed tool sentence plus extra text is still refused.

    The skip lets a reply through only when it equals that sentence. A
    startswith or contains check would accept this one.
    """
    from arelis.core.claims import ExactnessNeed
    from arelis.core.evidence import EvidenceLedger
    from arelis.core.loop_helpers import _exactness_finish_refuse

    sentence = "I couldn't get the forecast for Paris."
    reply = sentence + " It's 72°F."
    ledger = EvidenceLedger()
    ledger.record_tool(
        "weather",
        ok=False,
        output=sentence,
        data={},
        args={"place": "Paris"},
    )
    need = ExactnessNeed(
        needs_calculator=False,
        needs_web_evidence=False,
        needs_weather=True,
        needs_recall=False,
        kinds=("weather",),
    )
    refuse = _exactness_finish_refuse(
        reply,
        exact_need=need,
        ledger=ledger,
        numeric_gate=True,
        evidence_gate=True,
    )
    assert refuse == "I don't know. I don't have a forecast for that, so I won't guess."


class _WikiResearchReport(_StubTool):
    """C17-shaped report: only Wikipedia, so require_paper would refuse."""

    async def run(self, **kwargs: object) -> ToolResult:
        self.calls.append(dict(kwargs))
        url = "https://en.wikipedia.org/wiki/Solid-state_battery"
        return ToolResult(
            ok=True,
            output=(
                "Research report written to outputs/research/ssb.md "
                "(1 source scraped).\n\n# Solid-state vs Li-ion\n"
            ),
            data={
                "query": str(kwargs.get("query") or ""),
                "ok_count": 1,
                "path": "outputs/research/ssb.md",
                "sources": [{"title": "Solid-state battery", "url": url}],
            },
        )


def test_c17_research_report_hands_off_named_document_not_browser() -> None:
    """After research_report, a named document step must drop Chrome.

    Fail-before: 'convert that report to a PDF with the document tool' is
    not a document exactness kind, so _hand_off_to_document no-oped and
    the 35B kept browsing Wikipedia / a DOE 404 for the rest of the turn.

    Second case: a named document step without research_report must not
    widen owes-file. Drop the research_report gate in `_owes_document`
    and a repeat browser open that merely names the document tool would
    hold for a file even though needs_document is false. Main paints.
    """
    from arelis.core.claims import ExactnessNeed, detect_document_ask
    from arelis.core.same_call import record_same_call, same_call_key
    from arelis.core.turn_dispatch import _owes_document, dispatch_calls

    assert not detect_document_ask(_C17_RESEARCH_PDF)

    reg = ToolRegistry()
    full = foundation_registry()
    reg.register(_WikiResearchReport("research_report", risk="read"))
    for name in ("web_search", "scrape", "browser", "document"):
        tool = full.get(name)
        assert tool is not None, name
        reg.register(tool)

    extras: dict = {}
    _final, tool_results, thinking = asyncio.run(
        _run_agent_with_script(
            _C17_RESEARCH_PDF,
            [
                _call(
                    "research_report",
                    {"query": "solid-state batteries vs lithium-ion"},
                ),
                _call(
                    "browser",
                    {
                        "action": "navigate",
                        "url": "https://en.wikipedia.org/wiki/Solid-state_battery",
                    },
                ),
                _call(
                    "document",
                    {
                        "format": "pdf",
                        "title": "Solid-state vs Li-ion",
                        "from_path": "outputs/research/ssb.md",
                    },
                ),
                [("token", "PDF written to outputs/documents/ssb.pdf")],
            ],
            ["research_report", "web_search", "scrape", "browser", "document"],
            {**_NATIVE, "max_rounds": 8},
            registry=reg,
            capture_thinking=True,
            extras=extras,
        )
    )
    assert [name for name, _ok in tool_results] == [
        "research_report",
        "document",
    ], tool_results
    assert all(ok for _name, ok in tool_results)
    blob = " ".join(
        str(message.get("content") or "") for message in extras.get("messages", [])
    )
    assert "from_path" in blob
    assert "Do not search or browse" in blob
    assert any("Unknown tool" in t for t in thinking) or "Unknown tool" in blob

    ask = (
        "Open the Wikipedia page on solid-state batteries, then convert "
        "that page to a PDF with the document tool."
    )
    assert not detect_document_ask(ask)

    loop = _FakeLoop()
    loop.tools.ollama_tools = lambda names, *, param_hints=False: [{"name": n} for n in sorted(names)]
    args = {"action": "open", "url": "https://en.wikipedia.org/wiki/Solid-state_battery"}
    names = {"browser", "scrape", "document"}
    r = _scratch(
        text=ask,
        calls=[("browser", args)],
        content="",
        streamed="",
        tool_names=set(names),
        available=set(names),
        visible=set(names),
        offer_tools=True,
        messages=[],
    )
    ctx = _ctx(text=ask)
    ctx.available_all = set(names)
    ctx.tool_names = r.tool_names
    ctx.exact_need = ExactnessNeed(False, False, False, False)
    ctx.last_ok_tool_out = "Opened Solid-state battery - Wikipedia"
    ctx.last_ok_tool_name = "browser"
    record_same_call(ctx.same_ok, "browser", args)
    key = same_call_key("browser", args)
    assert key
    ctx.same_skip_keys.add(key)

    assert "research_report" not in loop.tools_used
    assert not _owes_document(loop, ctx)
    assert asyncio.run(dispatch_calls(loop, ctx, r, 20)) is True
    assert loop.finished is not None
    assert "browser" in r.tool_names
    assert "repeat held for the file" not in loop._trace
    assert "Call document" not in " ".join(str(m.get("content") or "") for m in r.messages)


@pytest.mark.parametrize(
    "negation",
    ['Do not use the document tool, just tell me.', "Don't use the document tool, just tell me."],
)
def test_native_negated_document_mention_does_not_nudge(negation: str) -> None:
    """Native: a negated document mention must not become an owed-tool nudge."""
    script = [
        _call("weather", {"place": "Springfield, Illinois"}),
        [("token", "ANSWER_1: Mild and clear in Springfield.")],
        [("token", "ANSWER_2: still mild.")],
        [("token", "ANSWER_3: third.")],
        [("token", "ANSWER_4: fourth.")],
        [("token", "ANSWER_5: fifth.")],
    ]
    prompt = f"What is the weather in Springfield, Illinois? {negation}"
    final_text, tool_results, thinking = asyncio.run(
        _run_agent_with_script(
            prompt,
            script,
            ["weather", "document"],
            {**_NATIVE, "max_rounds": 6},
            capture_thinking=True,
        )
    )
    # The model called weather. Document was only named under negation, so
    # the owed-tool nudge must not fire and the answer must ship.
    assert final_text.startswith("ANSWER_1"), (final_text, thinking, tool_results)
    assert not any(_OWED_NUDGE in t for t in thinking), thinking


