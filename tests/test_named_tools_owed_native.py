"""Native tool-calling must still honor named_tools_owed on multi-tool chains.

Matrix C01/C02/P09/P10 failed with native_tool_calling on: first tool ran,
tools were stripped, later named tools rejected as Unknown tool.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from arelis.config import shipped_num_ctx
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.no_call_finish import owed_tool_names
from arelis.core.orchestrator import Orchestrator
from arelis.core.turn_scratch import named_tools_owed
from arelis.eval.harness import _FailingStub, _ScriptedRouter, _StubTool, foundation_registry
from arelis.paths import outputs_dir
from arelis.tools.base import ToolRegistry, ToolResult
from arelis.tools.document import DocumentTool

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
            "llamacpp": {"default_cap": shipped_num_ctx()},
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


_INJECTED_MENU = ("analyze", "doc_extract", "image", "pdf", "plot", "vision")


def _picture(name: str = "plot.png") -> list[dict[str, object]]:
    return [
        {
            "id": "pic",
            "name": name,
            "path": f"data/drops/20261021/{name}",
            "kind": "image",
            "bytes": 8,
        }
    ]


async def _prepare_owed(
    text: str,
    typed_text: str | None,
    staged_files: object = None,
):
    """One turn through the real prepare path, with the tools the rules name."""
    registry = ToolRegistry()
    for name in _INJECTED_MENU:
        registry.register(_StubTool(name))
    loop = AgentLoop(
        EventBus(),
        _ScriptedRouter([]),
        registry,
        SessionMemory(),
        persona="You are Arelis under eval.",
        config={
            "agent": {"max_rounds": 4, "native_tool_calling": True},
            "llamacpp": {"default_cap": shipped_num_ctx()},
        },
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )
    ctx = await loop._prepare_turn(
        text, "fast", typed_text=typed_text, staged_files=staged_files
    )
    assert ctx is not None
    return loop, ctx


def _held(loop: AgentLoop, ctx: object) -> list[str]:
    return owed_tool_names(loop, ctx, SimpleNamespace(fail_counts={}))


async def test_attached_picture_does_not_owe_injected_tool_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Owed tools come from the words they typed, not from the attachment lines.

    The rules, the continuation instructions, and a filename stem such as
    plot are Arelis's own text. They must not force analyze, image, pdf,
    vision, or plot. A tool they actually named still is owed, and a
    negation they typed still wins over a filename that repeats it.
    """
    recorded: dict[str, object] = {}
    real_prepare = AgentLoop._prepare_turn

    async def _stop_at_prepare(
        self: AgentLoop, text: str, role: object, **kwargs: object
    ) -> None:
        del self, role
        recorded["text"] = text
        recorded["typed_text"] = kwargs.get("typed_text")
        recorded["staged_files"] = kwargs.get("staged_files")
        return None

    # Real run() has to forward typed_text. Stopping inside prepare records
    # that argument without playing the rest of the turn.
    monkeypatch.setattr(AgentLoop, "_prepare_turn", _stop_at_prepare)
    persona = Path(__file__).resolve().parents[1] / "arelis" / "persona" / "arelis.md"
    orch = Orchestrator(
        EventBus(),
        _ScriptedRouter([]),  # type: ignore[arg-type]
        ToolRegistry(),
        {
            "agent": {"confirm_timeout_s": 30},
            "workspace": {"roots": ["."]},
            "_persona_path": str(persona),
        },
        SessionMemory(),
    )

    async def _send(text: str, attachments: list[dict[str, object]] | None) -> tuple[str, object]:
        await orch.on_user_message(
            Event(
                EventType.USER_MESSAGE,
                {"text": text, "attachments": attachments or []},
            )
        )
        return str(recorded["text"]), recorded["typed_text"], recorded.get("staged_files")

    plain, plain_typed, plain_staged = await _send("what is this?", _picture())
    named, named_typed, named_staged = await _send("analyze the table", _picture())
    negated, negated_typed, negated_staged = await _send("do not call plot", _picture())
    picture_ask, picture_typed, picture_staged = await _send(
        "what's in this image", _picture()
    )
    orch.memory.add("user", plain)
    orch.memory.add("assistant", "I can describe that.")
    follow, follow_typed, _follow_staged = await _send("ok", None)
    monkeypatch.setattr(AgentLoop, "_prepare_turn", real_prepare)

    assert plain_typed == "what is this?"
    assert "plot.png" in plain
    assert "Attachments for this turn" in plain
    assert "analyze" in plain.lower()
    assert plain_staged == _picture()
    loop, ctx = await _prepare_owed(
        plain, plain_typed if isinstance(plain_typed, str) else None, plain_staged
    )
    assert ctx.typed_text == "what is this?"
    assert named_tools_owed(loop, ctx) == []
    assert _held(loop, ctx) == []

    assert named_typed == "analyze the table"
    loop, ctx = await _prepare_owed(
        named, named_typed if isinstance(named_typed, str) else None, named_staged
    )
    assert named_tools_owed(loop, ctx) == ["analyze"]
    assert _held(loop, ctx) == ["analyze"]

    assert negated_typed == "do not call plot"
    loop, ctx = await _prepare_owed(
        negated, negated_typed if isinstance(negated_typed, str) else None, negated_staged
    )
    assert "plot" in named_tools_owed(loop, ctx)
    assert _held(loop, ctx) == []

    assert follow_typed == "ok"
    assert "Continue the prior request" in follow
    loop, ctx = await _prepare_owed(
        follow, follow_typed if isinstance(follow_typed, str) else None
    )
    assert ctx.typed_text == "ok"
    assert named_tools_owed(loop, ctx) == []
    assert _held(loop, ctx) == []

    assert picture_typed == "what's in this image"
    assert picture_staged == _picture()
    loop, ctx = await _prepare_owed(
        picture_ask,
        picture_typed if isinstance(picture_typed, str) else None,
        picture_staged,
    )
    assert ctx.staged_files == (("image", "plot.png"),)
    assert named_tools_owed(loop, ctx) == ["vision"]
    assert _held(loop, ctx) == ["vision"]

    loop, ctx = await _prepare_owed("what's in this image", "what's in this image", None)
    assert named_tools_owed(loop, ctx) == ["image"]
    assert _held(loop, ctx) == ["image"]

    loop, ctx = await _prepare_owed(
        "do not call image",
        "do not call image",
        _picture(),
    )
    assert "vision" not in named_tools_owed(loop, ctx)
    assert _held(loop, ctx) == []


