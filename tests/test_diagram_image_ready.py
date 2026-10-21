"""A finished diagram has to publish the same picture event as an edit.

Chat's "Image ready" line and the Workspace well both listen for that event.
The PNG on disk is not enough. image, image_edit, and diagram all publish
the path resolve_display_path finds, so a short outputs/ path opens from
the data folder.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QImage

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.evidence import EvidenceLedger
from arelis.core.turn_context import TurnContext
from arelis.core.turn_execute import execute_call
from arelis.paths import display_path, user_data_dir
from arelis.tools.base import ToolResult
from arelis.ui.event_host import dispatch_event


class _Run:
    def __init__(self) -> None:
        self.bus = EventBus()
        self.max_rounds = 4
        self._look = None
        self._timer = None
        self.tools_used: set[str] = set()
        self._trace: list[str] = []
        self._receipts: list[dict] = []
        self.memory = SimpleNamespace(sink=None, messages=[])
        self.tool_output_chars = 8000
        self._expected_tools: set[str] = set()
        self._fail_replan_used = False
        self.tools = SimpleNamespace(get=lambda _name: None)

    def _tool_message(self, name: str, out: str) -> dict[str, str]:
        return {"role": "tool", "name": name, "content": out}


def _scratch(ctx: TurnContext) -> SimpleNamespace:
    return SimpleNamespace(
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


async def _drive(name: str, result: ToolResult) -> tuple[bool, list[Event]]:
    ctx = TurnContext(text="Draw a simple diagram of the water cycle", role="fast")
    run = _Run()
    seen: list[Event] = []

    async def capture(event: Event) -> None:
        seen.append(event)

    run.bus.subscribe(None, capture)
    bus_task = asyncio.create_task(run.bus.run())
    try:
        ended = await execute_call(
            run,
            ctx,
            _scratch(ctx),
            name,
            {"kind": "mermaid", "source": "flowchart LR\n  A --> B"},
            summary=name,
            call_fp=f"{name}-1",
            round_i=1,
            call_i=0,
            fanout_results={0: (1, result)},
        )
        await run.bus.drain()
    finally:
        run.bus.stop()
        bus_task.cancel()
        try:
            await bus_task
        except asyncio.CancelledError:
            pass
    return ended, seen


def _ready(events: list[Event]) -> list[Event]:
    return [event for event in events if event.type == EventType.IMAGE_READY]


@pytest.mark.asyncio
async def test_diagram_result_publishes_image_ready(
    tmp_path: Path, arelis_window, qt_app
) -> None:
    image = QImage(8, 8, QImage.Format.Format_ARGB32)
    image.fill(0xFF336699)
    relative = "outputs/diagrams/diagram.png"
    opened = user_data_dir() / relative
    opened.parent.mkdir(parents=True, exist_ok=True)
    assert image.save(str(opened))
    decoy = str((tmp_path / "not-the-file.png").resolve())

    failed, failed_events = await _drive(
        "diagram",
        ToolResult(ok=False, output="That diagram could not be drawn.", data={}),
    )
    assert failed is False
    assert _ready(failed_events) == []

    edit, edit_events = await _drive(
        "image_edit",
        ToolResult(
            ok=True,
            output="Saved outputs/images/mug-nobg.png.",
            data={"path": "outputs/images/mug-nobg.png", "abs_path": decoy},
        ),
    )
    assert edit is False
    edit_ready = _ready(edit_events)
    assert len(edit_ready) == 1
    assert edit_ready[0].payload["path"] == str(
        (user_data_dir() / "outputs/images/mug-nobg.png").resolve()
    )

    ended, events = await _drive(
        "diagram",
        ToolResult(
            ok=True,
            output=f"Saved {relative} in your diagrams folder.",
            data={
                "path": relative,
                "abs_path": decoy,
                "format": "png",
                "title": "diagram",
            },
        ),
    )
    assert ended is False
    ready = _ready(events)
    assert len(ready) == 1
    assert ready[0].payload["path"] == str(opened.resolve())

    window = arelis_window()
    dispatch_event(
        window,
        Event(
            EventType.TOOL_RESULT,
            {
                "tool": "diagram",
                "ok": True,
                "output": f"Saved {relative} in your diagrams folder.",
                "data": {"path": relative, "abs_path": decoy},
            },
        ),
    )
    dispatch_event(window, ready[0])
    qt_app.processEvents()

    chat = window.chat.view.toPlainText()
    assert chat.count("Image ready: open in Workspace") == 1
    assert window.workspace.output.toPlainText() == f"Image ready: {display_path(opened)}"
    assert window.workspace._image_mode
    assert window.workspace.image_label.text() == ""
    pix = window.workspace.image_label.pixmap()
    assert pix is not None and not pix.isNull()
