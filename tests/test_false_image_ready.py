"""A model must not claim Image ready unless a picture tool produced a file."""

from __future__ import annotations

import pytest

from arelis.core.events import EventType
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
