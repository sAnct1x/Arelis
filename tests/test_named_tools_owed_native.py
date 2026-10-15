"""Native tool-calling must still honor named_tools_owed on multi-tool chains.

Matrix C01/C02/P09/P10 failed with native_tool_calling on: first tool ran,
tools were stripped, later named tools rejected as Unknown tool.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from arelis.config import shipped_num_ctx
from arelis.core.agent_loop import _MAX_TOOL_NUDGES, AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
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


def test_native_units_calc_memory_chain_keeps_named_tools() -> None:
    """C01/P10 native: all three named tools must run (not strip after units)."""
    script = [
        _call("units", {"action": "convert", "quantity": "5 miles", "to": "kilometers"}),
        _call("calculator", {"expression": "8.05 * 3"}),
        _call(
            "memory",
            {"action": "remember", "fact": "weekly run distance is 24.1 kilometers"},
        ),
        [("token", "Got it - your weekly run distance of 24.1 km is stored.")],
    ]
    final_text, tool_results, _ = asyncio.run(
        _run_agent_with_script(
            "Convert 5 miles to kilometers with the units tool, then multiply those "
            "kilometers by 3 with the calculator, then remember that result as my "
            "weekly run distance.",
            script,
            ["units", "calculator", "memory"],
            _NATIVE,
        )
    )
    assert [n for n, _ in tool_results] == ["units", "calculator", "memory"], tool_results
    assert all(ok for _, ok in tool_results), tool_results
    assert "24" in final_text


class _ResolvedWeather(_StubTool):
    """Forecast stub whose data.place is the city the code resolved."""

    async def run(self, **kwargs: object) -> ToolResult:
        self.calls.append(dict(kwargs))
        return ToolResult(
            ok=True,
            output="Springfield, Illinois: 61F and overcast, high 66, low 48.",
            data={"place": "Springfield, Illinois"},
        )


def test_untitled_weather_brief_uses_the_resolved_place() -> None:
    """An untitled brief takes the resolved place. The model writes the reply."""
    weather = _ResolvedWeather("weather")
    document = _StubTool("document", risk="write")
    reg = ToolRegistry()
    reg.register(weather)
    reg.register(document)
    script = [
        _call("weather", {"place": "Springfield"}),
        _call("document", {"format": "md", "body": "Sunny."}),
        [("token", "Saved the Springfield brief.")],
    ]
    final_text, tool_results, _ = asyncio.run(
        _run_agent_with_script(
            "Get today's weather forecast for Springfield, Illinois, then save a "
            "one-paragraph summary of it as a markdown document.",
            script,
            ["weather", "document"],
            _FLAG_OFF,
            registry=reg,
        )
    )
    assert [name for name, _ok in tool_results] == ["weather", "document"], tool_results
    assert document.calls[0]["title"] == "Springfield, Illinois Weather Brief"
    assert final_text.strip() == "Saved the Springfield brief."


def test_step_after_weather_doc_still_runs() -> None:
    """A note after the weather file still runs. The turn does not end on the file."""
    weather = _ResolvedWeather("weather")
    document = _StubTool("document", risk="write")
    memory = _StubTool("memory", risk="write")
    reg = ToolRegistry()
    reg.register(weather)
    reg.register(document)
    reg.register(memory)
    script = [
        _call("weather", {"place": "Springfield, Illinois"}),
        _call(
            "document",
            {
                "format": "md",
                "title": "Springfield, Illinois Weather Brief",
                "body": "61F and overcast.",
            },
        ),
        _call("memory", {"action": "remember", "fact": "done"}),
        [("token", "Saved the brief and added a note saying done.")],
    ]
    final_text, tool_results, _ = asyncio.run(
        _run_agent_with_script(
            "Get the weather for Springfield, Illinois, save it as a doc, "
            "then add a note saying done.",
            script,
            ["weather", "document", "memory"],
            _FLAG_OFF,
            registry=reg,
        )
    )
    assert [name for name, _ok in tool_results] == [
        "weather",
        "document",
        "memory",
    ], tool_results
    assert memory.calls == [{"action": "remember", "fact": "done"}]
    assert final_text.strip() == "Saved the brief and added a note saying done."


def test_user_given_doc_title_survives_weather() -> None:
    """A title the user already gave stays, even after a forecast resolved."""
    weather = _ResolvedWeather("weather")
    document = _StubTool("document", risk="write")
    reg = ToolRegistry()
    reg.register(weather)
    reg.register(document)
    script = [
        _call("weather", {"place": "Springfield, Illinois"}),
        _call(
            "document",
            {"format": "md", "title": "Grocery List", "body": "Milk."},
        ),
        [("token", "Saved Grocery List.")],
    ]
    final_text, tool_results, _ = asyncio.run(
        _run_agent_with_script(
            "Get the weather for Springfield, Illinois, then write a doc titled Grocery List.",
            script,
            ["weather", "document"],
            _FLAG_OFF,
            registry=reg,
        )
    )
    assert [name for name, _ok in tool_results] == ["weather", "document"], tool_results
    assert document.calls[0]["title"] == "Grocery List"
    assert final_text.strip() == "Saved Grocery List."


def test_native_early_finish_still_calls_owed_tool() -> None:
    """Native: model tries to answer after weather; document is still owed -> runs."""
    script = [
        _call("weather", {"place": "Springfield, Illinois"}),
        [("token", "Sunny today in Springfield.")],
        _call(
            "document",
            {
                "format": "md",
                "title": "Springfield Weather Brief",
                "body": "Springfield forecast: sunny.",
            },
        ),
        [("token", "Saved Springfield Weather Brief.md")],
    ]
    final_text, tool_results, thinking = asyncio.run(
        _run_agent_with_script(
            "Call the weather tool for Springfield, Illinois. Then call the document "
            "tool with format=md and title Springfield Weather Brief and a body "
            "summarizing the forecast.",
            script,
            ["weather", "document"],
            _NATIVE,
            capture_thinking=True,
        )
    )
    assert [n for n, _ in tool_results] == ["weather", "document"], tool_results
    assert tool_results[1][1] is True
    assert "springfield" in final_text.lower()
    assert any(_OWED_NUDGE in t for t in thinking), thinking


def test_native_owed_tool_twice_failed_still_terminates() -> None:
    """Native: owed tool fails twice -> finish hold drops; turn ends cleanly."""
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
    ]
    final_text, tool_results, _ = asyncio.run(
        _run_agent_with_script(
            "Call the weather tool for Springfield, Illinois. Then call the document "
            "tool with format=md and title Springfield Weather Brief and a body "
            "summarizing the forecast.",
            script,
            ["weather", "document"],
            {**_NATIVE, "max_rounds": 5},
            registry=reg,
        )
    )
    assert tool_results[0] == ("weather", True), tool_results
    doc_fails = [ok for n, ok in tool_results if n == "document"]
    assert doc_fails == [False, False], tool_results
    assert final_text.strip(), "turn must finish with an answer"
    assert len(tool_results) == 3, tool_results


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


def test_native_owed_nudge_respects_max_tool_nudges() -> None:
    """Native finish nudge fires up to _MAX_TOOL_NUDGES and no further."""
    script = [
        [("token", "ANSWER_1: sunny without tools.")],
        [("token", "ANSWER_2: still skipping document.")],
        [("token", "ANSWER_3: third try.")],
        [("token", "ANSWER_4: fourth try.")],
        [("token", "ANSWER_5: fifth try.")],
        [("token", "ANSWER_6: sixth try.")],
    ]
    final_text, tool_results, thinking = asyncio.run(
        _run_agent_with_script(
            "Call the weather tool for Springfield, Illinois. Then call the document "
            "tool with format=md and title Springfield Weather Brief and a body "
            "summarizing the forecast.",
            script,
            ["weather", "document"],
            {**_NATIVE, "max_rounds": 8},
            capture_thinking=True,
        )
    )
    del tool_results
    owed_nudges = [t for t in thinking if _OWED_NUDGE in t]
    assert len(owed_nudges) <= _MAX_TOOL_NUDGES, thinking
    assert len(owed_nudges) == _MAX_TOOL_NUDGES, thinking
    assert final_text.strip(), "turn must terminate with an answer"


def test_flag_off_plain_question_still_runs_owed_document() -> None:
    """Flag off: weather, then a plain question, must not end the turn.

    C02/P09. Round 1 calls weather. Round 2 is a question, not a call.
    Document is still owed, so the finish path holds and round 3 runs it.
    """
    script = [
        _call("weather", {"place": "Springfield, Illinois"}),
        [("token", "Should I save the Springfield forecast now?")],
        _call(
            "document",
            {
                "format": "md",
                "title": "Springfield Weather Brief",
                "body": "Springfield forecast: sunny.",
            },
        ),
        [("token", "Saved Springfield Weather Brief.md")],
    ]
    final_text, tool_results, thinking = asyncio.run(
        _run_agent_with_script(
            "Call the weather tool for Springfield, Illinois. Then call the document "
            "tool with format=md and title Springfield Weather Brief and a body "
            "summarizing the forecast.",
            script,
            ["weather", "document"],
            _FLAG_OFF,
            capture_thinking=True,
        )
    )
    assert [n for n, _ in tool_results] == ["weather", "document"], tool_results
    assert tool_results[1][1] is True
    assert any(_OWED_NUDGE in t for t in thinking), thinking
    assert "springfield" in final_text.lower()


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


def test_flag_off_repeated_weather_block_ends_before_step_limit() -> None:
    """A second weather call runs. The turn does not invent a forecast ending."""
    script = [
        _call("weather", {"place": "Springfield"}),
        _call("weather", {"place": "Springfield"}),
        [("token", "Mild in Springfield.")],
    ]
    extras: dict = {}
    final_text, tool_results, thinking = asyncio.run(
        _run_agent_with_script(
            "What is the weather in Springfield?",
            script,
            ["weather", "document"],
            {**_FLAG_OFF, "max_rounds": 8},
            registry=_ambiguous_weather_registry(),
            capture_thinking=True,
            extras=extras,
        )
    )
    assert [name for name, _ok in tool_results] == ["weather", "weather"], tool_results
    assert all(ok for _name, ok in tool_results)
    assert _not_run_tool_messages(extras["messages"]) == []
    assert final_text.strip() == "Mild in Springfield."
    assert "I have the forecast" not in final_text
    assert not any("max rounds" in line for line in thinking), thinking
    assert "tool-step limit" not in final_text.lower()


def _brief_path(title: str) -> Path:
    stem = title.replace(" ", "-")
    matches = sorted((outputs_dir() / "documents").glob(f"{stem}*.md"))
    assert matches, f"no file for {title}"
    return matches[-1]


@pytest.mark.parametrize("mode", ["blocked", "no_call"])
def test_flag_off_need_place_still_writes_owed_document(mode: str) -> None:
    """Document still has to run after weather, and the markdown file has to land.

    Blocked mode calls weather again before document. Those calls run.
    No-call mode pastes the forecast. The owed-document hold still nudges,
    and the file still lands.
    """
    title = f"Springfield Weather Brief {mode}"
    body = f"Sunny at Springfield Station ({mode})."
    document = _call(
        "document",
        {"format": "md", "title": title, "body": body},
    )
    done = [("token", f"Saved {title}.md")]
    weather = _call("weather", {"place": "Springfield"})
    if mode == "blocked":
        script = [weather, weather, weather, document, done]
    else:
        script = [
            weather,
            [("token", _WEATHER_RESULT_TEXT)],
            [("token", _WEATHER_RESULT_TEXT)],
            document,
            done,
        ]
    extras: dict = {}
    final_text, tool_results, thinking = asyncio.run(
        _run_agent_with_script(
            _C02_WEATHER_DOCUMENT,
            script,
            ["weather", "document"],
            {**_FLAG_OFF, "max_rounds": 8},
            registry=_ambiguous_weather_writing_registry(),
            capture_thinking=True,
            extras=extras,
        )
    )
    assert not any("max rounds" in line for line in thinking), thinking
    assert "tool-step limit" not in final_text.lower()
    written = _brief_path(title)
    text = written.read_text(encoding="utf-8")
    assert body in text, text
    assert written.is_file()
    names = [name for name, ok in tool_results]
    assert all(ok for _name, ok in tool_results)
    if mode == "blocked":
        assert names == ["weather", "weather", "weather", "document"], tool_results
        assert _not_run_tool_messages(extras["messages"]) == []
    else:
        assert names == ["weather", "document"], tool_results
        assert any(_OWED_NUDGE in line for line in thinking), thinking


def test_flag_off_repeated_weather_block_still_runs_owed_document() -> None:
    """Weather calls do not end the turn while document is still owed.

    The model calls weather four times, then document. Every weather call
    runs. Document runs. The canned forecast ending does not replace it.
    """
    weather = _call("weather", {"place": "Springfield"})
    document = _call(
        "document",
        {
            "format": "md",
            "title": "Springfield Weather Brief",
            "body": "Sunny at Springfield Station.",
        },
    )
    script = [weather, weather, weather, weather, document, [("token", "Saved the brief.")]]
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
    assert "I have the forecast" not in final_text
    assert "I couldn't save the brief" not in final_text
    assert "Saved the brief." in final_text
    assert [name for name, ok in tool_results] == [
        "weather",
        "weather",
        "weather",
        "weather",
        "document",
    ], tool_results
    assert all(ok for _name, ok in tool_results)
    assert _not_run_tool_messages(extras["messages"]) == []
    assert not any("max rounds" in line for line in thinking), thinking


def test_flag_off_repeated_weather_block_stops_after_nudge_cap() -> None:
    """A weather retry does not substitute the old brief-ending sentence.

    Document is owed and the model does call it. The turn must not stop
    early with the canned "I couldn't save the brief." line. The nudge
    cap itself is test_flag_off_owed_nudge_respects_max_tool_nudges.
    """
    weather = _call("weather", {"place": "Springfield"})
    document = _call(
        "document",
        {
            "format": "md",
            "title": "Springfield Weather Brief",
            "body": "Sunny at Springfield Station.",
        },
    )
    script = [weather, weather, document, [("token", "Saved the brief.")]]
    final_text, tool_results, thinking = asyncio.run(
        _run_agent_with_script(
            _C02_WEATHER_DOCUMENT,
            script,
            ["weather", "document"],
            {**_FLAG_OFF, "max_rounds": 8},
            registry=_ambiguous_weather_registry(),
            capture_thinking=True,
        )
    )
    assert "I couldn't save the brief" not in final_text
    assert "I have the forecast" not in final_text
    assert "Saved the brief." in final_text
    assert [name for name, _ok in tool_results] == [
        "weather",
        "weather",
        "document",
    ], tool_results
    assert "tool-step limit" not in final_text.lower()
    assert not any("max rounds" in line for line in thinking), thinking


def test_flag_off_repeated_weather_block_without_document_ends() -> None:
    """No document owed: both weather calls run, and the model answers."""
    script = [
        _call("weather", {"place": "Springfield"}),
        _call("weather", {"place": "Springfield"}),
        [("token", "Mild in Springfield.")],
    ]
    final_text, tool_results, thinking = asyncio.run(
        _run_agent_with_script(
            "What is the weather in Springfield?",
            script,
            ["weather", "document"],
            {**_FLAG_OFF, "max_rounds": 8},
            registry=_ambiguous_weather_registry(),
            capture_thinking=True,
        )
    )
    assert [name for name, _ok in tool_results] == ["weather", "weather"], tool_results
    assert not any(_OWED_NUDGE in line for line in thinking), thinking
    assert not any("max rounds" in line for line in thinking), thinking
    assert "tool-step limit" not in final_text.lower()
    assert final_text.strip() == "Mild in Springfield."
    assert "I have the forecast" not in final_text


def test_flag_off_repeated_camera_block_does_not_end_turn() -> None:
    """A repeated camera cap on a look turn does not take the weather end path.

    The first snapshot runs. The next two hit the camera cap and do not run.
    That second block used to finish the turn. The calculator call after it
    still has to run.
    """
    script = [
        _call("camera", {"action": "snapshot"}),
        _call("camera", {"action": "snapshot"}),
        _call("camera", {"action": "snapshot"}),
        _call("calculator", {"expression": "1+1"}),
        [("token", "kept going")],
    ]
    final_text, tool_results, thinking = asyncio.run(
        _run_agent_with_script(
            "look at the camera and tell me what you see",
            script,
            ["camera", "calculator"],
            {**_FLAG_OFF, "max_rounds": 8},
            capture_thinking=True,
        )
    )
    assert tool_results == [("camera", True), ("calculator", True)], tool_results
    assert any(line.startswith("round 4/") for line in thinking), thinking
    assert "camera_eval.jpg" not in final_text
    assert "did not run" not in final_text.lower()
    assert not any("max rounds" in line for line in thinking), thinking


def test_flag_off_repeated_send_block_does_not_end_turn() -> None:
    """Two duplicate send_sms blocks do not take the weather end path.

    The stub send runs once. The next two calls hit the once-guard and do
    not send again. Before the repeated-block end existed, that round
    stayed open and the closing line landed. The weather plain reply must
    not replace it.
    """
    sms = _call("send_sms", {"to": "Ada", "body": "I am on my way"})
    script = [sms, sms, sms, [("token", "kept going")]]
    final_text, tool_results, thinking = asyncio.run(
        _run_agent_with_script(
            "How many miles is 5 kilometers? Use send_sms to text Ada that I am on my way.",
            script,
            ["send_sms", "units"],
            {**_FLAG_OFF, "max_rounds": 8},
            capture_thinking=True,
        )
    )
    assert tool_results == [("send_sms", True)], tool_results
    assert "kept going" in final_text
    assert "I have the forecast" not in final_text
    assert "I already have that forecast" not in final_text
    skips = [line for line in thinking if line.startswith("skip  Already sent SMS")]
    assert len(skips) == 2, thinking
    assert any(line.startswith("round 4/") for line in thinking), thinking
    assert not any("max rounds" in line for line in thinking), thinking


def test_flag_off_repeated_weather_block_ends_in_plain_words() -> None:
    """The model's words stay. A weather retry does not paste the tool dump."""
    script = [
        _call("weather", {"place": "Springfield"}),
        [("token", "Mild and clear.")],
    ]
    final_text, tool_results, thinking = asyncio.run(
        _run_agent_with_script(
            "What is the weather in Springfield?",
            script,
            ["weather", "document"],
            {**_FLAG_OFF, "max_rounds": 8},
            registry=_ambiguous_weather_registry(),
            capture_thinking=True,
        )
    )
    assert [name for name, _ok in tool_results] == ["weather"], tool_results
    assert final_text.strip() == "Mild and clear."
    lowered = final_text.lower()
    assert "place:" not in lowered
    assert "now:" not in lowered
    assert "72f" not in lowered
    assert "did not run" not in lowered
    assert not any("max rounds" in line for line in thinking), thinking


def test_flag_off_ambiguous_resolved_place_is_not_home() -> None:
    """An ambiguous reading is the forecast. It is not a second home call.

    The ask names no city. Weather ran with a place and came back
    ambiguous. The turn must not steer another weather call for home,
    and it must not paste an answer-now nudge. The model speaks the
    forecast it already has.
    """
    script = [
        _call("weather", {"place": "Springfield"}),
        [("token", "Here is the forecast.")],
    ]
    extras: dict = {}
    final_text, tool_results, _thinking = asyncio.run(
        _run_agent_with_script(
            "What's the weather like?",
            script,
            ["weather"],
            _FLAG_OFF,
            registry=_ambiguous_weather_registry(),
            extras=extras,
        )
    )
    user_lines = [
        str(message.get("content") or "")
        for message in extras["messages"]
        if message.get("role") == "user"
    ]
    assert not any("Answer the user now" in line for line in user_lines), user_lines
    assert not any("That reading is today only" in line for line in user_lines), user_lines
    assert not any(
        "without place for the user's own location" in line for line in user_lines
    ), user_lines
    assert tool_results[0] == ("weather", True), tool_results
    assert "forecast" in final_text.lower()


def test_weather_failure_line_names_no_tool() -> None:
    """A missing forecast is plain words. No tool name and no dash."""
    from arelis.core.claims import unsupported_exactness_reply

    line = unsupported_exactness_reply(["weather"])
    assert "tool" not in line.casefold()
    assert "\u2014" not in line
    assert "\u2013" not in line
    assert line == "I don't know. I don't have a forecast for that, so I won't guess."


def test_flag_off_weather_miss_says_so_and_stops() -> None:
    """A failed forecast does not end the turn with a canned line.

    The retry runs. The model then answers. The old "I couldn't get a
    forecast." finish is not substituted.
    """
    reg = ToolRegistry()
    reg.register(_FailingStub("weather", risk="read"))
    script = [
        _call("weather", {"place": "Springfield"}),
        _call("weather", {"place": "Springfield"}),
        [("token", "trying again")],
    ]
    final_text, tool_results, thinking = asyncio.run(
        _run_agent_with_script(
            "What is the weather in Springfield?",
            script,
            ["weather"],
            {**_FLAG_OFF, "max_rounds": 8},
            registry=reg,
            capture_thinking=True,
        )
    )
    assert tool_results == [("weather", False), ("weather", False)], tool_results
    assert final_text.strip() == (
        "I don't know. I don't have a forecast for that, so I won't guess."
    )
    assert "I couldn't get a forecast." not in final_text
    assert "tool-step limit" not in final_text.lower()
    assert not any("max rounds" in line for line in thinking), thinking


def test_flag_off_weather_miss_still_reaches_document() -> None:
    """A failed forecast must not end the turn while document is still owed."""
    reg = ToolRegistry()
    reg.register(_FailingStub("weather", risk="read"))
    reg.register(_StubTool("document", risk="write"))
    script = [
        _call("weather", {"place": "Springfield"}),
        _call(
            "document",
            {
                "format": "md",
                "title": "Springfield Weather Brief",
                "body": "No forecast.",
            },
        ),
        [("token", "Saved the brief.")],
    ]
    final_text, tool_results, thinking = asyncio.run(
        _run_agent_with_script(
            _C02_WEATHER_DOCUMENT,
            script,
            ["weather", "document"],
            {**_FLAG_OFF, "max_rounds": 8},
            registry=reg,
            capture_thinking=True,
        )
    )
    assert [name for name, _ok in tool_results] == ["weather", "document"], tool_results
    assert tool_results[0][1] is False
    assert tool_results[1][1] is True
    assert "couldn't get a forecast" not in final_text.lower()
    assert "tool-step limit" not in final_text.lower()
    assert not any("max rounds" in line for line in thinking), thinking


def test_flag_off_owed_nudge_respects_max_tool_nudges() -> None:
    """Flag off: the owed-tool hold still stops at _MAX_TOOL_NUDGES."""
    script = [
        [("token", "Should I call the tools?")],
        [("token", "Still asking instead of calling?")],
        [("token", "Third question without a call?")],
        [("token", "Fourth question?")],
        [("token", "Fifth question?")],
        [("token", "Sixth question?")],
    ]
    final_text, tool_results, thinking = asyncio.run(
        _run_agent_with_script(
            "Call the weather tool for Springfield, Illinois. Then call the document "
            "tool with format=md and title Springfield Weather Brief and a body "
            "summarizing the forecast.",
            script,
            ["weather", "document"],
            {**_FLAG_OFF, "max_rounds": 8},
            capture_thinking=True,
        )
    )
    del tool_results
    owed_nudges = [t for t in thinking if _OWED_NUDGE in t]
    assert len(owed_nudges) <= _MAX_TOOL_NUDGES, thinking
    assert len(owed_nudges) == _MAX_TOOL_NUDGES, thinking
    assert final_text.strip(), "turn must terminate with an answer"


def test_flag_off_units_calc_memory_unchanged() -> None:
    """Flag-off regression: C01 chain still runs all three tools."""
    script = [
        _call("units", {"action": "convert", "quantity": "5 miles", "to": "kilometers"}),
        _call("calculator", {"expression": "8.05 * 3"}),
        _call(
            "memory",
            {"action": "remember", "fact": "weekly run distance is 24.1 kilometers"},
        ),
        [("token", "Got it - your weekly run distance of 24.1 km is stored.")],
    ]
    final_text, tool_results, _ = asyncio.run(
        _run_agent_with_script(
            "Convert 5 miles to kilometers with the units tool, then multiply those "
            "kilometers by 3 with the calculator, then remember that result as my "
            "weekly run distance.",
            script,
            ["units", "calculator", "memory"],
            _FLAG_OFF,
        )
    )
    assert [n for n, _ in tool_results] == ["units", "calculator", "memory"], tool_results
    assert "24" in final_text


def test_native_image_edit_then_ocr_does_not_finish_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard only; passes on base too. image_edit then OCR must still chain."""
    from arelis.eval.harness import _StubTool

    reg = foundation_registry()
    reg.register(_StubTool("image_edit", risk="write"))

    def _reg(names: list[str]) -> ToolRegistry:
        out = ToolRegistry()
        for name in names:
            tool = reg.get(name)
            assert tool is not None, name
            out.register(tool)
        return out

    monkeypatch.setattr(sys.modules[__name__], "_tools_registry", _reg)

    script = [
        _call("image_edit", {"path": "work/invoice.png", "op": "grayscale"}),
        _call("ocr", {"path": "outputs/images/invoice-gray.png", "action": "text"}),
        [("token", "Amount due 1250")],
    ]
    text, results, _ = asyncio.run(
        _run_agent_with_script(
            "Convert work/invoice.png to grayscale with image_edit, then OCR the new "
            "grayscale image and tell me the amount due.",
            script,
            ["image_edit", "ocr"],
            _NATIVE,
        )
    )
    assert [n for n, _ in results] == ["image_edit", "ocr"], results
    assert "1250" in text


@pytest.mark.parametrize(
    "negation",
    [
        "Do not use the document tool, just tell me.",
        "Don't use the document tool, just tell me.",
        "without the document tool, just tell me.",
        "never use the document tool, just tell me.",
    ],
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


def test_native_positive_owed_document_still_nudges() -> None:
    """Positive owed mention still nudges in native mode (negation filter must not blanket-skip)."""
    script = [
        [("token", "ANSWER_1: converting in my head.")],
        _call("units", {"action": "convert", "quantity": "5 km", "to": "miles"}),
        _call(
            "document",
            {
                "format": "md",
                "title": "Distance Note",
                "body": "5 km is about 3.1 miles.",
            },
        ),
        [("token", "Saved Distance Note.md")],
    ]
    final_text, tool_results, thinking = asyncio.run(
        _run_agent_with_script(
            "Convert 5 km to miles with the units tool, then save it with the document tool.",
            script,
            ["units", "document"],
            _NATIVE,
            capture_thinking=True,
        )
    )
    assert any(_OWED_NUDGE in t for t in thinking), thinking
    assert [n for n, _ in tool_results] == ["units", "document"], tool_results
    assert final_text.strip()
