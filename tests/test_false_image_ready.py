"""A model must not claim Image ready unless a picture tool produced a file."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from arelis.core.events import EventType
from arelis.core.evidence import EvidenceLedger
from arelis.core.turn_context import TurnContext
from arelis.core.turn_execute import execute_call
from arelis.tools.base import ToolResult
from tests.hardening_helpers import _collect, _loop_with_tools, _ScriptedRouter


@pytest.mark.asyncio
async def test_finish_drops_image_ready_claim_when_the_tool_did_not_run() -> None:
    loop = _loop_with_tools(_ScriptedRouter(["ignored"]))
    claim = "Image ready: 73330443158a4839951222993415501d.png"
    events = await _collect(loop.bus, loop._finish(claim, []))
    dones = [
        str(event.payload.get("text") or "")
        for event in events
        if event.type == EventType.ASSISTANT_DONE
    ]
    assert dones
    assert all("Image ready" not in text for text in dones)
    assert "have not made a picture" in dones[0].lower()

    loop = _loop_with_tools(_ScriptedRouter(["ignored"]))
    loop._image_ready_ok = True
    events = await _collect(loop.bus, loop._finish(claim, []))
    dones = [
        str(event.payload.get("text") or "")
        for event in events
        if event.type == EventType.ASSISTANT_DONE
    ]
    assert dones == [claim]


@pytest.mark.asyncio
async def test_successful_image_call_keeps_ready_line_and_marks_passthrough() -> None:
    loop = _loop_with_tools(_ScriptedRouter(["ignored"]))
    ctx = TurnContext(text="draw a red fox", role="fast")
    scratch = SimpleNamespace(
        text=ctx.text,
        agent_cfg={"tool_summary_inject": False},
        available_all=set(),
        available=set(),
        visible=set(),
        tool_names=set(),
        sources=[],
        ledger=EvidenceLedger(),
        fail_counts={},
        web_search_ok=set(),
        page_ok=set(),
        sms_sent=set(),
        agenda_created=set(),
        weather_ok_places=set(),
        weather_days_retried=set(),
        exact_need=ctx.exact_need,
        offer_tools=False,
        chat_tools=[],
        messages=[],
        sms_draft=None,
        email_draft=None,
    )
    path = "outputs/images/fox.png"
    result = ToolResult(
        ok=True,
        output=f"Image saved to {path}.",
        data={"path": path},
    )
    ended = False

    async def _drive() -> None:
        nonlocal ended
        ended = await execute_call(
            loop,
            ctx,
            scratch,
            "image",
            {"prompt": "a red fox"},
            summary="image",
            call_fp="image-1",
            round_i=1,
            call_i=0,
            fanout_results={0: (12, result)},
        )

    await _collect(loop.bus, _drive())
    assert ended is True
    assert loop._image_ready_ok is True
    last = loop.memory.messages[-1]
    assert last.role == "assistant"
    assert f"Image ready: {path}" in last.content
    assert "have not made a picture" not in last.content.lower()
    assert "not her own words" in (last.note or "")
    assert "image" in (last.note or "")

