"""Native tool-calling must still honor named_tools_owed on multi-tool chains.

Matrix C01/C02/P09/P10 failed with native_tool_calling on: first tool ran,
tools were stripped, later named tools rejected as Unknown tool.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from arelis.config import shipped_num_ctx
from arelis.core.agent_loop import _MAX_TOOL_NUDGES, AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.eval.harness import _FailingStub, _ScriptedRouter, foundation_registry
from arelis.tools.base import ToolRegistry

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


def test_native_early_finish_still_calls_owed_tool() -> None:
    """Native: model tries to answer after weather; document is still owed -> runs."""
    script = [
        _call("weather", {"place": "Springfield, Illinois", "days": 3}),
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
        _call("weather", {"place": "Springfield, Illinois", "days": 3}),
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
        _call("weather", {"place": "Springfield, Illinois", "days": 3}),
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
    """Native: purely negated document mention must not trigger owed-tool nudges."""
    script = [
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
    # Weather force may preinject a weather call; that is fine. The owed-nudge
    # must not discard ANSWER_1 — that is the negation-filter contract.
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
