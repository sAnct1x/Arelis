"""Finish from the confirm outcome and the tool result, not from reply text.

The real-app driver skips every confirm. A declined memory remember used to
ship as if the value was saved. A declined workspace write used to end as
the calculator refusal. An empty reply after doc_extract used to paste the
extract and skip the write-up round.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.evidence import EvidenceLedger
from arelis.core.loop_helpers import declined_finish_reply
from arelis.core.memory import SessionMemory
from arelis.core.turn_confirm import RUN, SKIP, confirm_call
from arelis.core.turn_context import TurnContext
from arelis.tools import policy as write_policy
from arelis.tools.base import ToolRegistry, ToolResult
from arelis.tools.pdf_assemble import PdfAssembleTool
from arelis.tools.plot import PlotTool
from arelis.tools.policy import _drive_local_path, normalize_write_path
from arelis.workspace import WorkspaceRoots
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
        self.workspace: Any = None

    def preview_path(self, args: dict[str, Any] | None = None) -> Path:
        raw = args if isinstance(args, dict) else {}
        return Path(str(raw.get("path") or "").strip())

    async def run(self, **kwargs: Any) -> ToolResult:
        self.runs += 1
        path = str(kwargs.get("path") or "")
        self.written.append(path)
        return ToolResult(ok=True, output=f"Wrote {path}")


class _DocumentStub:
    name = "document"
    description = "document"
    risk = "write"
    parameters_schema = {
        "type": "object",
        "properties": {
            "format": {"type": "string"},
            "title": {"type": "string"},
            "body": {"type": "string"},
            "filename": {"type": "string"},
        },
    }

    def __init__(self) -> None:
        self.runs = 0
        self.written: list[str] = []
        self.workspace: Any = None

    def preview_path(self, args: dict[str, Any] | None = None) -> Path:
        raw = args if isinstance(args, dict) else {}
        fmt = str(raw.get("format") or "txt").strip().lower().lstrip(".") or "txt"
        name = str(raw.get("filename") or raw.get("title") or "").strip()
        leaf = Path(name.replace("\\", "/")).name or "document"
        if Path(leaf).suffix.lower().lstrip(".") != fmt:
            leaf = f"{Path(leaf).stem or leaf}.{fmt}"
        return Path(leaf)

    async def run(self, **kwargs: Any) -> ToolResult:
        self.runs += 1
        dest = str(self.preview_path(kwargs))
        self.written.append(dest)
        return ToolResult(ok=True, output=f"written {dest}")


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
    def __init__(self, *extra: Any) -> None:
        tools = ToolRegistry()
        if extra:
            for tool in extra:
                tools.register(tool)
        else:
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
        self.cards: list[tuple[str, dict[str, Any]]] = []

    async def request_confirm(
        self, cid: str, tool: str, args: dict[str, Any], summary: str
    ) -> str:
        del cid, summary
        self.cards.append((tool, dict(args)))
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
async def test_declined_workspace_write_is_not_a_calculator_refusal(
    tmp_path: Path,
) -> None:
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

    # Same dest through document after the workspace no. Tool-plus-path
    # keying used to open a card, write the file, and ship "written"
    # next to the skip sentence. Notes.TXT is that dest on Windows.
    document = _DocumentStub()
    redo = _WorkspaceStub()
    redo_cards: list[tuple[str, str]] = []

    async def _skip_workspace_notes(
        cid: str, tool: str, args: dict[str, Any], summary: str
    ) -> str:
        del cid, summary
        dest = str(args.get("path") or args.get("filename") or "")
        redo_cards.append((tool, dest))
        if tool == "workspace" and dest.casefold().endswith("notes.txt"):
            return "skip"
        return "allow"

    redo_router = _ScriptedRouter(
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
                    "document",
                    {
                        "filename": "Notes.TXT",
                        "title": "notes",
                        "body": "errands\n",
                    },
                )
            ],
            [("token", "written notes.txt")],
        ]
    )
    redo_bus = EventBus()
    redo_loop = _loop(
        redo_router, redo, document, confirm=_skip_workspace_notes
    )
    redo_loop.bus = redo_bus
    redo_events = await _collect(
        redo_bus,
        redo_loop.run("Save notes.txt.", "fast"),
    )
    redo_text = str(_done(redo_events)["text"])
    assert redo_cards == [("workspace", "notes.txt")]
    assert redo.runs == 0
    assert document.runs == 0
    assert document.written == []
    assert "written" not in redo_text.casefold()
    assert notes_line in redo_text

    # The dest is preview_path, resolved against the workspace. After
    # notes.txt is declined, title=notes, filename=notes, a drop-tray
    # spelling of that same output, and abs / dot / backslash / drive
    # paths are the same dest: no card, no write. Raw argument text
    # would miss those. An input named notes.txt is not an output.
    root = tmp_path / "ws"
    root.mkdir()
    roots = WorkspaceRoots.from_paths([str(root)])
    abs_notes = str((root / "notes.txt").resolve())
    posix_notes = abs_notes.replace("\\", "/")
    slash_notes = abs_notes.replace("/", "\\")
    # On Windows abs_notes already has a drive. Prefixing C: makes
    # C:D:\\... which is not that file. Swap the drive case instead.
    # On POSIX, C: plus the backslash spelling is the Linux dest.
    if len(abs_notes) >= 2 and abs_notes[1] == ":":
        win_notes = abs_notes[0].swapcase() + abs_notes[1:]
    else:
        win_notes = "C:" + slash_notes
    assert normalize_write_path("notes.txt", workspace=roots) == "notes.txt"
    assert normalize_write_path(abs_notes, workspace=roots) == "notes.txt"
    assert normalize_write_path(posix_notes, workspace=roots) == "notes.txt"
    assert normalize_write_path(slash_notes, workspace=roots) == "notes.txt"
    assert normalize_write_path(win_notes, workspace=roots) == "notes.txt"
    # Keep a Windows drive letter. Stripping it made abs notes.txt
    # a new dest on windows-latest.
    saved_os = write_policy.os.name
    write_policy.os.name = "nt"
    try:
        assert _drive_local_path(r"D:\ws\notes.txt") == "D:/ws/notes.txt"
    finally:
        write_policy.os.name = saved_os
    workspace = _WorkspaceStub()
    workspace.workspace = roots
    document = _DocumentStub()
    document.workspace = roots
    pdf = PdfAssembleTool(roots)
    plot = PlotTool(roots, None)
    gate = _ConfirmLoop(workspace, document, pdf, plot)
    ctx = TurnContext(text="Save notes.txt.", role="fast")

    async def _gate(
        name: str, args: dict[str, Any], *, text: str = ctx.text
    ) -> str:
        action, _summary, _fp = await confirm_call(
            gate,
            ctx,
            name,
            args,
            text=text,
            fail_counts={},
            skip_counts={},
            messages=[],
            drop_wander=lambda _name: None,
        )
        return action

    first = await _gate(
        "workspace",
        {"action": "write", "path": "notes.txt", "content": "errands\n"},
    )
    assert first == SKIP
    assert gate.cards == [
        ("workspace", {"action": "write", "path": "notes.txt", "content": "errands\n"})
    ]
    assert workspace.runs == 0

    blocked = (
        (
            "document",
            {"format": "txt", "title": "notes", "body": "errands\n"},
        ),
        (
            "document",
            {"format": "txt", "filename": "notes", "body": "errands\n"},
        ),
        (
            "document",
            {
                "format": "txt",
                "filename": "outputs/documents/notes.txt",
                "body": "errands\n",
            },
        ),
        (
            "workspace",
            {"action": "write", "path": win_notes, "content": "errands\n"},
        ),
        (
            "workspace",
            {"action": "write", "path": abs_notes, "content": "errands\n"},
        ),
        (
            "workspace",
            {"action": "write", "path": posix_notes, "content": "errands\n"},
        ),
        (
            "workspace",
            {"action": "write", "path": "./notes.txt", "content": "errands\n"},
        ),
        (
            "workspace",
            {"action": "write", "path": slash_notes, "content": "errands\n"},
        ),
        (
            "workspace",
            {"action": "write", "path": ".\\notes.txt", "content": "errands\n"},
        ),
    )
    for name, args in blocked:
        before = len(gate.cards)
        action = await _gate(name, args)
        assert action == SKIP
        assert len(gate.cards) == before
        assert workspace.runs == 0
        assert document.runs == 0
        assert document.written == []

    # Reading or converting notes.txt is not a write of that dest.
    read = await _gate("workspace", {"action": "read", "path": "notes.txt"})
    assert read == RUN
    assert len(gate.cards) == 1
    convert_cards = len(gate.cards)
    other_pdf = await _gate(
        "pdf",
        {"action": "split", "path": "notes.txt", "pages": "1", "dest": "kept.pdf"},
    )
    assert len(gate.cards) == convert_cards + 1
    assert gate.cards[-1][0] == "pdf"
    assert other_pdf == SKIP
    other_doc = await _gate(
        "document",
        {
            "format": "txt",
            "title": "kept-notes",
            "from_path": "notes.txt",
            "body": "errands\n",
        },
    )
    assert len(gate.cards) == convert_cards + 2
    assert gate.cards[-1][0] == "document"
    assert other_doc == SKIP
    assert workspace.runs == 0
    assert document.runs == 0

    # A declined pdf or plot dest stays blocked when the source changes.
    plot_ctx = TurnContext(text="Draw the chart.", role="fast")
    plot_gate = _ConfirmLoop(workspace, document, pdf, plot)
    plot_gate._decision = "skip"

    async def _plot_gate(name: str, args: dict[str, Any]) -> str:
        action, _summary, _fp = await confirm_call(
            plot_gate,
            plot_ctx,
            name,
            args,
            text=plot_ctx.text,
            fail_counts={},
            skip_counts={},
            messages=[],
            drop_wander=lambda _name: None,
        )
        return action

    plot_skip = await _plot_gate(
        "plot",
        {
            "action": "line",
            "path": "src-a.csv",
            "out": "declined-chart.png",
            "xs": "1,2",
            "ys": "3,4",
        },
    )
    assert plot_skip == SKIP
    assert len(plot_gate.cards) == 1
    plot_again = await _plot_gate(
        "plot",
        {
            "action": "line",
            "path": "src-b.csv",
            "out": "declined-chart.png",
            "xs": "1,2",
            "ys": "3,4",
        },
    )
    assert plot_again == SKIP
    assert len(plot_gate.cards) == 1

    pdf_skip = await _plot_gate(
        "pdf",
        {"action": "split", "path": "src-a.pdf", "pages": "1", "dest": "declined.pdf"},
    )
    assert pdf_skip == SKIP
    assert len(plot_gate.cards) == 2
    pdf_again = await _plot_gate(
        "pdf",
        {"action": "split", "path": "src-b.pdf", "pages": "1", "dest": "declined.pdf"},
    )
    assert pdf_again == SKIP
    assert len(plot_gate.cards) == 2


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


