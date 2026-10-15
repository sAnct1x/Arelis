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
_WRITE_LINE = (
    "I did not write work/sq2.py because the write was skipped, "
    "so I could not run it."
)
_WRITE_ONLY_LINE = "I did not write work/note.txt because the write was skipped."
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
    runs = 0

    async def run(self, **kwargs: Any) -> ToolResult:
        self.runs += 1
        return ToolResult(ok=True, output=f"Wrote {kwargs.get('path')}")


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


def test_remember_and_forget_record_a_memory_write() -> None:
    """A successful remember or forget is a memory_write. A read stays recall."""
    ledger = EvidenceLedger()
    ledger.record_tool(
        "memory",
        ok=True,
        output="Remembered: weekly run distance is 24.14016 km",
        data={"fact": "weekly run distance is 24.14016 km", "kind": "fact"},
        args={"action": "remember", "fact": "weekly run distance is 24.14016 km"},
        native_tools=True,
    )
    assert ledger.has_ok("memory_write")
    assert not ledger.has_ok("recall")

    ledger.record_tool(
        "memory",
        ok=True,
        output="Forgot 1 fact.",
        data={"fact": "weekly run", "status": "rejected"},
        args={"action": "forget", "fact": "weekly run"},
        native_tools=True,
    )
    assert sum(1 for item in ledger.items if item.kind == "memory_write" and item.ok) == 2

    missed = EvidenceLedger()
    missed.record_tool(
        "memory",
        ok=False,
        output="Could not store that fact.",
        data={},
        args={"action": "remember", "fact": "nope"},
        native_tools=True,
    )
    assert not missed.has_ok("memory_write")


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
async def test_declined_memory_save_says_it_was_not_saved() -> None:
    """C01: remember was declined. Keep the answer and say the save was skipped."""
    memory = _MemoryStub()
    router = _ScriptedRouter(
        [
            [
                _call(
                    "memory",
                    {
                        "action": "remember",
                        "fact": "weekly run distance is 24.14016 km",
                    },
                )
            ],
            [("token", "Your weekly run distance is 24.14016 km.")],
        ]
    )
    bus = EventBus()
    loop = _loop(router, memory, confirm=_skip)
    loop.bus = bus
    events = await _collect(
        bus,
        loop.run(
            "Remember that my weekly run distance is 24.14016 km.",
            "fast",
        ),
    )
    payload = _done(events)
    text = str(payload["text"])
    assert memory.runs == 0
    assert "24.14016" in text
    assert _MEMORY_LINE in text
    assert payload.get("unverified") == ["memory_write"]


@pytest.mark.asyncio
async def test_allowed_memory_save_is_not_marked_unverified() -> None:
    """A remember that actually ran is a memory_write, not an unverified gap."""
    memory = _MemoryStub()
    router = _ScriptedRouter(
        [
            [
                _call(
                    "memory",
                    {
                        "action": "remember",
                        "fact": "weekly run distance is 24.14016 km",
                    },
                )
            ],
            [("token", "Your weekly run distance is 24.14016 km.")],
        ]
    )
    bus = EventBus()
    loop = _loop(router, memory, confirm=_allow)
    loop.bus = bus
    events = await _collect(
        bus,
        loop.run("Remember that my weekly run distance is 24.14016 km.", "fast"),
    )
    payload = _done(events)
    assert memory.runs == 1
    assert _MEMORY_LINE not in str(payload["text"])
    assert "unverified" not in payload


@pytest.mark.asyncio
async def test_declined_workspace_write_is_not_a_calculator_refusal() -> None:
    """P05: the write was skipped. Do not answer with the calculator refusal."""
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
    assert text.strip() == (
        "I did not write work/sq2.py because the write was skipped."
    )
    assert "calculator" not in text.lower()


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


@pytest.mark.asyncio
async def test_empty_extract_ships_raw_text_when_the_writeup_is_empty() -> None:
    """The raw extract ships only after that one write-up round is also empty."""
    extract = _ExtractStub()
    router = _ScriptedRouter(
        [
            [_call("doc_extract", {"path": "work/memo.docx"})],
            [("token", "")],
            [("token", "")],
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
    text = str(_done(events)["text"])
    thinking = _thinking(events)
    assert "asking for a write-up" in thinking
    assert "answering from result" in thinking
    assert thinking.index("asking for a write-up") < thinking.index(
        "answering from result"
    )
    assert "falcon-77" in text


def test_skipped_memory_save_has_no_could_not_run_clause() -> None:
    """A declined remember names the skipped save and nothing about a run."""
    text = declined_finish_reply(
        {"memory"},
        [("memory", {"action": "remember", "fact": "12*12 is 144"})],
    )
    assert text == _MEMORY_LINE
    assert "could not run" not in text


def test_skipped_sms_has_no_could_not_run_clause() -> None:
    """A declined text says the send was skipped, not that a script could not run."""
    text = declined_finish_reply(
        {"send_sms"},
        [("send_sms", {})],
    )
    assert text == _SEND_LINE
    assert "could not run" not in text


def test_skipped_email_has_no_could_not_run_clause() -> None:
    """A declined email uses the same send line, with no run clause."""
    text = declined_finish_reply(
        {"send_email"},
        [("send_email", {})],
    )
    assert text == _SEND_LINE
    assert "could not run" not in text


def test_skipped_workspace_write_without_run_script_has_no_could_not_run_clause() -> None:
    """A skipped file write with no owed run_script stops after the skip."""
    text = declined_finish_reply(
        {"workspace"},
        [("workspace", {"action": "write", "path": "work/note.txt"})],
    )
    assert text == _WRITE_ONLY_LINE
    assert "could not run" not in text


def test_skipped_workspace_write_keeps_could_not_run_when_run_script_was_declined() -> None:
    """run_script in the declined set is an owed run, so the write keeps the clause."""
    text = declined_finish_reply(
        {"workspace", "run_script"},
        [("workspace", {"action": "write", "path": "work/sq2.py"})],
    )
    assert text == _WRITE_LINE


def test_skipped_workspace_write_keeps_could_not_run_when_the_ledger_records_a_failed_run() -> None:
    """A run_script_error warrant is the owed run. Reply text is not read."""
    ledger = EvidenceLedger()
    ledger.record_tool(
        "run_script",
        ok=False,
        output="exit: 1",
        data={"exit": 1, "stdout": "", "path": "work/sq2.py"},
        args={"path": "work/sq2.py"},
    )
    text = declined_finish_reply(
        {"workspace"},
        [("workspace", {"action": "write", "path": "work/sq2.py"})],
        ledger=ledger,
    )
    assert text == _WRITE_LINE


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


def test_successful_run_then_skipped_write_drops_could_not_run() -> None:
    """A later skipped write does not owe a run that already succeeded.

    requested_tools still names run_script because the turn used it. The
    run_script_ok warrant is what clears the debt. Reply text is not read.
    """
    ledger = _script_ledger(ok=True, stdout="144")
    assert ledger.has_ok("run_script_ok")
    text = declined_finish_reply(
        {"workspace"},
        _SKIPPED_WRITE,
        ledger=ledger,
        requested_tools={"run_script", "workspace"},
    )
    assert text == "I did not write work/sq2.py because the write was skipped."
    assert "could not run" not in text


def test_success_then_failure_drops_could_not_run() -> None:
    """A later run_script_error does not restore the clause after run_script_ok.

    Both results are recorded through the ledger, success first. The
    skipped write still names only the skip.
    """
    ledger = EvidenceLedger()
    ledger.record_tool(
        "run_script",
        ok=True,
        output="144",
        data={"exit": 0, "stdout": "144", "path": "work/sq2.py"},
        args={"path": "work/sq2.py"},
    )
    ledger.record_tool(
        "run_script",
        ok=False,
        output="exit: 1",
        data={"exit": 1, "stdout": "", "path": "work/sq2.py"},
        args={"path": "work/sq2.py"},
    )
    saw_ok = False
    saw_error_after = False
    for item in ledger.items:
        if item.kind == "run_script_ok" and item.ok:
            saw_ok = True
        if saw_ok and item.kind == "run_script_error" and not item.ok:
            saw_error_after = True
    assert saw_ok and saw_error_after
    text = declined_finish_reply(
        {"workspace"},
        _SKIPPED_WRITE,
        ledger=ledger,
        requested_tools={"run_script", "workspace"},
    )
    assert text == "I did not write work/sq2.py because the write was skipped."
    assert "could not run" not in text


def test_failed_run_then_skipped_write_keeps_could_not_run() -> None:
    """A run_script_error leaves the run owed, so the skipped write keeps the clause."""
    ledger = _script_ledger(ok=False)
    assert not ledger.has_ok("run_script_ok")
    assert any(item.kind == "run_script_error" and not item.ok for item in ledger.items)
    text = declined_finish_reply(
        {"workspace"},
        _SKIPPED_WRITE,
        ledger=ledger,
        requested_tools={"run_script", "workspace"},
    )
    assert text == _WRITE_LINE


def test_no_run_yet_and_run_script_wanted_keeps_could_not_run() -> None:
    """No run_script result yet. A wanted run still adds the clause."""
    text = declined_finish_reply(
        {"workspace"},
        _SKIPPED_WRITE,
        ledger=EvidenceLedger(),
        requested_tools={"run_script"},
    )
    assert text == _WRITE_LINE


def test_memory_and_send_skips_ignore_a_finished_script_run() -> None:
    """A successful run does not change the skipped memory or send lines."""
    ledger = _script_ledger(ok=True, stdout="144")
    memory = declined_finish_reply(
        {"memory"},
        [("memory", {"action": "remember", "fact": "12*12 is 144"})],
        ledger=ledger,
        requested_tools={"run_script", "memory"},
    )
    sms = declined_finish_reply(
        {"send_sms"},
        [("send_sms", {})],
        ledger=ledger,
        requested_tools={"run_script", "send_sms"},
    )
    email = declined_finish_reply(
        {"send_email"},
        [("send_email", {})],
        ledger=ledger,
        requested_tools={"run_script", "send_email"},
    )
    assert memory == _MEMORY_LINE
    assert sms == _SEND_LINE
    assert email == _SEND_LINE
    assert "could not run" not in memory
    assert "could not run" not in sms
    assert "could not run" not in email


@pytest.mark.asyncio
async def test_declined_memory_on_a_math_ask_does_not_say_it_could_not_run() -> None:
    """Math is missing and the save was skipped. Do not blame a script run."""
    memory = _MemoryStub()
    router = _ScriptedRouter(
        [
            [
                _call(
                    "memory",
                    {"action": "remember", "fact": "12*12 is 144"},
                )
            ],
            [("token", "12*12 is 144.")],
        ]
    )
    bus = EventBus()
    loop = _loop(router, memory, confirm=_skip)
    loop.bus = bus
    events = await _collect(
        bus,
        loop.run("Remember that 12*12 is 144.", "fast"),
    )
    text = str(_done(events)["text"])
    assert memory.runs == 0
    assert _MEMORY_LINE in text
    assert "could not run" not in text
    assert "calculator" not in text.lower()


@pytest.mark.asyncio
async def test_declined_workspace_write_without_a_run_has_no_could_not_run_clause() -> None:
    """The file was skipped and nobody asked to run a script."""
    workspace = _WorkspaceStub()
    router = _ScriptedRouter(
        [
            [
                _call(
                    "workspace",
                    {
                        "action": "write",
                        "path": "work/note.txt",
                        "content": "12*12\n",
                    },
                )
            ],
            [("token", "The product is 144.")],
        ]
    )
    bus = EventBus()
    loop = _loop(router, workspace, confirm=_skip)
    loop.bus = bus
    events = await _collect(
        bus,
        loop.run(
            "Use workspace action=write to create work/note.txt containing "
            "exactly: the product is 12*12. Then tell me the product.",
            "fast",
        ),
    )
    text = str(_done(events)["text"]).strip()
    assert workspace.runs == 0
    assert text == _WRITE_ONLY_LINE
    assert "could not run" not in text


@pytest.mark.asyncio
async def test_successful_run_then_skipped_write_does_not_say_it_could_not_run() -> None:
    """run_script already succeeded. A later skipped write must not say it could not run."""
    script = _RunScriptStub()
    workspace = _WorkspaceStub()
    router = _ScriptedRouter(
        [
            [_call("run_script", {"path": "work/sq2.py"})],
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
    loop = _loop(router, script, workspace, confirm=_allow_script_skip_write)
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
    text = str(_done(events)["text"]).strip()
    assert script.runs == 1
    assert workspace.runs == 0
    assert text == "I did not write work/sq2.py because the write was skipped."
    assert "could not run" not in text
