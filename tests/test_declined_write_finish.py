"""Finish from the confirm outcome and the tool result, not from reply text.

The real-app driver skips every confirm. A declined memory remember used to
ship as if the value was saved. A declined workspace write used to end as
the calculator refusal. An empty reply after doc_extract used to paste the
extract and skip the write-up round.
"""

from __future__ import annotations

from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.evidence import EvidenceLedger
from arelis.core.loop_helpers import declined_finish_reply
from arelis.core.memory import SessionMemory
from arelis.core.turn_confirm import SKIP, confirm_call
from arelis.core.turn_context import TurnContext
from arelis.tools.base import ToolRegistry, ToolResult
from tests.hardening_helpers import _collect, _config, _ScriptedRouter

_MEMORY_LINE = "The value was not saved because the save was skipped."
_SEND_LINE = "The message was not sent because the send was skipped."
_WRITE_LINE = "I didn't save work/sq2.py because you said no, so I could not run it."
_WRITE_ONLY_LINE = "I didn't save work/sq2.py because you said no."
_OCR_LINE = "I didn't read the text in shape.png because you said no."
_VISION_LINE = "I didn't look at shape.png because you said no."
_UNKNOWN_LINE = "I didn't run that step because you said no."
_MULTI_LINE = (
    "I didn't read the text in shape.png or save work/sq2.py because you said no."
)
_SEND_WRITE_LINE = "I didn't send that text or save n.txt because you said no."
_SEND_UNKNOWN_LINE = (
    "I didn't send that text or run that step because you said no."
)
_EXTRACT = "Project codename: falcon-77"
_EXTRACT_ANSWER = "The project codename is falcon-77."


def _call(name: str, arguments: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    return (
        "tool_calls",
        [
            {
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        ],
    )


class _MemoryStub:
    name = "memory"
    description = "memory"
    risk = "write"
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "fact": {"type": "string"},
        },
        "required": ["action"],
    }
    runs = 0

    async def run(self, **kwargs: Any) -> ToolResult:
        self.runs += 1
        fact = str(kwargs.get("fact") or "")
        return ToolResult(
            ok=True,
            output=f"Remembered: {fact}",
            data={"fact": fact, "kind": "fact", "status": "active"},
        )


class _WorkspaceStub:
    name = "workspace"
    description = "files"
    risk = "write"
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
    }

    def __init__(self) -> None:
        self.runs = 0
        self.written: list[str] = []

    async def run(self, **kwargs: Any) -> ToolResult:
        self.runs += 1
        path = str(kwargs.get("path") or "")
        self.written.append(path)
        return ToolResult(ok=True, output=f"Wrote {path}")


class _RunScriptStub:
    name = "run_script"
    description = "run a script"
    risk = "side_effect"
    parameters_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    runs = 0

    async def run(self, **kwargs: Any) -> ToolResult:
        self.runs += 1
        path = str(kwargs.get("path") or "")
        # Success with no stdout: run_script_ok, and no calc warrant.
        # Math stays missing, so finish still goes through the skip reply.
        return ToolResult(
            ok=True,
            output="",
            data={"exit": 0, "stdout": "", "path": path},
        )


class _ExtractStub:
    name = "doc_extract"
    description = "read a document"
    risk = "read"
    parameters_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
    }
    runs = 0

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        self.runs += 1
        return ToolResult(ok=True, output=_EXTRACT)


async def _skip(cid: str, tool: str, args: dict[str, Any], summary: str) -> str:
    del cid, tool, args, summary
    return "skip"


async def _allow(cid: str, tool: str, args: dict[str, Any], summary: str) -> str:
    del cid, tool, args, summary
    return "allow"


async def _allow_script_skip_write(
    cid: str, tool: str, args: dict[str, Any], summary: str
) -> str:
    del cid, args, summary
    if tool == "run_script":
        return "allow"
    return "skip"


def _loop(router: _ScriptedRouter, *tools: Any, confirm: Any) -> AgentLoop:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["native_tool_calling"] = True
    cfg["agent"]["max_rounds"] = 6
    cfg["agent"]["confirm_writes"] = True
    return AgentLoop(
        EventBus(),
        router,  # type: ignore[arg-type]
        registry,
        SessionMemory(),
        "persona",
        cfg,
        request_confirm=confirm,
        is_cancelled=lambda: False,
    )


def _done(events: list[Any]) -> dict[str, Any]:
    event = next(item for item in events if item.type == EventType.ASSISTANT_DONE)
    return dict(event.payload)


def _thinking(events: list[Any]) -> str:
    return " ".join(
        str(event.payload.get("text") or "")
        for event in events
        if event.type == EventType.THINKING
    )


class _ConfirmBus:
    async def publish(self, event: Any) -> None:
        return None


class _ConfirmLoop:
    def __init__(self) -> None:
        tools = ToolRegistry()
        for name in ("memory", "workspace"):
            stub = _MemoryStub() if name == "memory" else _WorkspaceStub()
            stub.name = name
            tools.register(stub)
        self.bus = _ConfirmBus()
        self.tools = tools
        self.memory = None
        self._trace: list[str] = []
        self._expected_tools: set[str] = set()
        self._look = None
        self._timer = None
        self.confirm_writes = True
        self.confirm_image = True
        self.confirm_send = True
        self.confirm_browser = True
        self.confirm_desktop = True
        self.confirm_vision = True
        self.confirm_run = True
        self.ask_is_grant = True
        self.tools_used: set[str] = set()
        self._decision = "skip"

    async def request_confirm(
        self, cid: str, tool: str, args: dict[str, Any], summary: str
    ) -> str:
        del cid, tool, args, summary
        return self._decision

    def _tool_message(self, name: str, content: str) -> dict[str, Any]:
        return {"role": "tool", "name": name, "content": content}

    async def _confirm_wait_heartbeat(self, name: str, started: float) -> None:
        del name, started
        return None


@pytest.mark.asyncio
async def test_declined_tools_comes_from_the_confirm_decision_only() -> None:
    """Skip and decline fill the set. A blocked call and reply text do not."""
    loop = _ConfirmLoop()
    ctx = TurnContext(
        text="I skipped it and the user declined the save",
        role="fast",
    )
    messages: list[dict[str, Any]] = [
        {"role": "assistant", "content": "the save was skipped and declined"}
    ]
    action, _summary, _fp = await confirm_call(
        loop,
        ctx,
        "memory",
        {"action": "remember", "fact": "weekly run distance is 24.14016 km"},
        text=ctx.text,
        fail_counts={},
        skip_counts={},
        messages=messages,
        drop_wander=lambda _name: None,
    )
    assert action == SKIP
    assert ctx.declined_tools == {"memory"}
    assert ctx.declined_calls[-1][0] == "memory"
    assert ctx.declined_calls[-1][1]["fact"] == "weekly run distance is 24.14016 km"

    allowed = TurnContext(text="remember that I declined nothing", role="fast")
    loop._decision = "allow"
    action, _summary, _fp = await confirm_call(
        loop,
        allowed,
        "memory",
        {"action": "remember", "fact": "kept"},
        text=allowed.text,
        fail_counts={},
        skip_counts={},
        messages=[],
        drop_wander=lambda _name: None,
    )
    assert action != SKIP
    assert allowed.declined_tools == set()

    blocked = TurnContext(text="write the file, the model said it was declined", role="fast")
    action, _summary, _fp = await confirm_call(
        loop,
        blocked,
        "workspace",
        {"action": "write", "path": "work/sq2.py", "content": "   "},
        text=blocked.text,
        fail_counts={},
        skip_counts={},
        messages=[],
        drop_wander=lambda _name: None,
    )
    assert action == SKIP
    assert blocked.declined_tools == set()


@pytest.mark.asyncio
async def test_declined_workspace_write_is_not_a_calculator_refusal() -> None:
    """P05: skipped work is named in plain words, not the calculator refusal."""
    long_ocr = "/tmp/inbox/shots/shape.png"
    known = declined_finish_reply(
        {"ocr"},
        [("ocr", {"action": "text", "path": long_ocr})],
    )
    assert known == _OCR_LINE
    assert long_ocr not in known
    assert "inbox/shots" not in known
    assert "I did not text" not in known

    picture = declined_finish_reply(
        {"vision"},
        [("vision", {"path": long_ocr})],
    )
    assert picture == _VISION_LINE
    assert long_ocr not in picture
    assert "inbox/shots" not in picture
    assert "run that step" not in picture

    unknown = declined_finish_reply(
        {"mystery_tool"},
        [("mystery_tool", {"action": "frob", "path": long_ocr})],
    )
    assert unknown == _UNKNOWN_LINE
    assert "frob" not in unknown
    assert long_ocr not in unknown

    write = declined_finish_reply(
        {"workspace"},
        [("workspace", {"action": "write", "path": "work/sq2.py"})],
    )
    assert write == _WRITE_ONLY_LINE
    owed = declined_finish_reply(
        {"workspace", "run_script"},
        [("workspace", {"action": "write", "path": "work/sq2.py"})],
    )
    assert owed == _WRITE_LINE

    both = declined_finish_reply(
        {"ocr", "workspace"},
        [
            ("ocr", {"action": "text", "path": long_ocr}),
            ("workspace", {"action": "write", "path": "work/sq2.py"}),
        ],
    )
    assert both == _MULTI_LINE
    assert " too" not in both
    assert both.count("because you said no") == 1

    send_write = declined_finish_reply(
        {"send_sms", "workspace"},
        [
            ("send_sms", {"to": "mom", "body": "hello"}),
            ("workspace", {"action": "write", "path": "n.txt"}),
        ],
    )
    assert send_write == _SEND_WRITE_LINE
    assert "send that text" in send_write

    send_unknown = declined_finish_reply(
        {"send_sms", "mystery_tool"},
        [
            ("send_sms", {"to": "mom", "body": "hello"}),
            ("mystery_tool", {"action": "frob"}),
        ],
    )
    assert send_unknown == _SEND_UNKNOWN_LINE
    assert "run that step" in send_unknown
    assert "frob" not in send_unknown

    workspace = _WorkspaceStub()
    router = _ScriptedRouter(
        [
            [
                _call(
                    "workspace",
                    {
                        "action": "write",
                        "path": "work/sq2.py",
                        "content": "print(12*12)\n",
                    },
                )
            ],
            [("token", "The output is 144.")],
        ]
    )
    bus = EventBus()
    loop = _loop(router, workspace, confirm=_skip)
    loop.bus = bus
    events = await _collect(
        bus,
        loop.run(
            "Use workspace action=write to create work/sq2.py containing "
            "exactly: print(12*12). Then call run_script on work/sq2.py. "
            "Then tell me the output.",
            "fast",
        ),
    )
    text = str(_done(events)["text"])
    assert workspace.runs == 0
    assert text.strip() == _WRITE_ONLY_LINE
    assert "calculator" not in text.lower()

    # Two asked writes, one card at a time. A no on notes.txt used to end
    # the turn, so chores.txt was never asked about. Skip that step, name
    # it, and still run the other file. chores.txt, not todo.txt: TODO is
    # a placeholder token and never reaches a card.
    notes_line = "I didn't save notes.txt because you said no."
    two = _WorkspaceStub()
    cards: list[str] = []

    async def _skip_notes(
        cid: str, tool: str, args: dict[str, Any], summary: str
    ) -> str:
        del cid, tool, summary
        cards.append(str(args.get("path") or ""))
        if str(args.get("path") or "").endswith("notes.txt"):
            return "skip"
        return "allow"

    two_router = _ScriptedRouter(
        [
            [
                _call(
                    "workspace",
                    {
                        "action": "write",
                        "path": "notes.txt",
                        "content": "errands\n",
                    },
                )
            ],
            [
                _call(
                    "workspace",
                    {
                        "action": "write",
                        "path": "chores.txt",
                        "content": "milk\n",
                    },
                )
            ],
            [("token", "Saved chores.txt.")],
        ]
    )
    two_bus = EventBus()
    two_loop = _loop(two_router, two, confirm=_skip_notes)
    two_loop.bus = two_bus
    two_events = await _collect(
        two_bus,
        two_loop.run("Save notes.txt and chores.txt.", "fast"),
    )
    two_text = str(_done(two_events)["text"])
    assert cards == ["notes.txt", "chores.txt"]
    assert two.written == ["chores.txt"]
    assert two.runs == 1
    assert notes_line in two_text
    assert "chores.txt" in two_text

    # A lone decline with no later call must still ship the skip sentence,
    # not the next model line. This ask has no math, so exactness refuse
    # is not the thing that names it.
    lone = _WorkspaceStub()
    lone_router = _ScriptedRouter(
        [
            [
                _call(
                    "workspace",
                    {
                        "action": "write",
                        "path": "notes.txt",
                        "content": "errands\n",
                    },
                )
            ],
            [("token", "SHOULD NOT SHIP")],
        ]
    )
    lone_bus = EventBus()
    lone_loop = _loop(lone_router, lone, confirm=_skip)
    lone_loop.bus = lone_bus
    lone_events = await _collect(
        lone_bus,
        lone_loop.run("Save notes.txt.", "fast"),
    )
    lone_text = str(_done(lone_events)["text"]).strip()
    assert lone.runs == 0
    assert lone_text == notes_line
    assert "SHOULD NOT SHIP" not in lone_text


@pytest.mark.asyncio
async def test_empty_extract_gets_one_writeup_before_the_raw_text() -> None:
    """S37b: an empty reply after doc_extract asks once, then uses those words."""
    extract = _ExtractStub()
    router = _ScriptedRouter(
        [
            [_call("doc_extract", {"path": "work/memo.docx"})],
            [("token", "")],
            [("token", _EXTRACT_ANSWER)],
        ]
    )
    bus = EventBus()
    loop = _loop(router, extract, confirm=_allow)
    loop.bus = bus
    events = await _collect(
        bus,
        loop.run(
            "Read the content of work/memo.docx and tell me the project codename.",
            "fast",
        ),
    )
    text = str(_done(events)["text"]).strip()
    thinking = _thinking(events)
    assert extract.runs == 1
    assert "asking for a write-up" in thinking
    assert text == _EXTRACT_ANSWER
    assert "Project codename:" not in text
    assert router.i == 3


def _script_ledger(*, ok: bool, stdout: str = "") -> EvidenceLedger:
    """A real run_script result. Success is run_script_ok. Failure is run_script_error."""
    ledger = EvidenceLedger()
    ledger.record_tool(
        "run_script",
        ok=ok,
        output=stdout if ok else "exit: 1",
        data={
            "exit": 0 if ok else 1,
            "stdout": stdout,
            "path": "work/sq2.py",
        },
        args={"path": "work/sq2.py"},
    )
    return ledger


_SKIPPED_WRITE = [("workspace", {"action": "write", "path": "work/sq2.py"})]


