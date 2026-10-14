"""A python result is not a script run.

P05 try 2: the workspace write was approved, run_script's confirm was
skipped, and the python cell printed 144. Finish must say the script
was not run. The reply text is not consulted.
"""

from __future__ import annotations

from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.evidence import EvidenceLedger
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry, ToolResult
from tests.hardening_helpers import _collect, _config, _ScriptedRouter

_CLAIM = "The file was written and executed. It prints 144"
_WROTE = "Wrote work/sq2.py."
_SKIPPED = "work/sq2.py was not run because the run was skipped."
_FAILED = "work/sq2.py was not run because the run failed."
_PYTHON = "Calculated with python (not the script): 144"
_FACT = "weekly run distance is 24.14016 km"
_SAVED = f"Saved: {_FACT}."
_P05 = (
    "Use workspace action=write to create work/sq2.py containing "
    "exactly: print(12*12). Then call run_script on work/sq2.py. "
    "Then tell me the output."
)


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


class _PythonStub:
    name = "python"
    description = "python cell"
    risk = "read"
    parameters_schema = {
        "type": "object",
        "properties": {"code": {"type": "string"}},
        "required": ["code"],
    }
    runs = 0

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        self.runs += 1
        return ToolResult(ok=True, output="144", data={"result": "144"})


class _RunScriptStub:
    name = "run_script"
    description = "run a project .py"
    risk = "side_effect"
    parameters_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    runs = 0

    def __init__(self, *, ok: bool) -> None:
        self.ok = ok

    async def run(self, **kwargs: Any) -> ToolResult:
        self.runs += 1
        path = str(kwargs.get("path") or "")
        if not self.ok:
            return ToolResult(
                ok=False,
                output="exit: 1\n\nstderr:\nboom",
                data={"exit": 1, "stdout": "", "path": path},
            )
        return ToolResult(
            ok=True,
            output="exit: 0\n\nstdout:\n144",
            data={"exit": 0, "stdout": "144", "path": path},
        )


def _loop(router: _ScriptedRouter, *tools: Any, confirm: Any) -> AgentLoop:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["native_tool_calling"] = True
    cfg["agent"]["max_rounds"] = 6
    cfg["agent"]["confirm_writes"] = True
    cfg["agent"]["confirm_run"] = True
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


async def _allow_write_skip_run(
    cid: str, tool: str, args: dict[str, Any], summary: str
) -> str:
    del cid, args, summary
    if tool == "run_script":
        return "skip"
    return "allow"


async def _allow(cid: str, tool: str, args: dict[str, Any], summary: str) -> str:
    del cid, tool, args, summary
    return "allow"


def _done(events: list[Any]) -> dict[str, Any]:
    event = next(item for item in events if item.type == EventType.ASSISTANT_DONE)
    return dict(event.payload)


def test_only_a_successful_run_script_sets_run_script_ok() -> None:
    """python's 144 is a calc warrant. It is not a script run."""
    python = EvidenceLedger()
    python.record_tool(
        "python",
        ok=True,
        output="144",
        data={"result": "144"},
        args={"code": "print(12*12)"},
    )
    assert python.has_ok("calc")
    assert not python.has_ok("run_script_ok")

    failed = EvidenceLedger()
    failed.record_tool(
        "run_script",
        ok=False,
        output="exit: 1\n\nstderr:\nboom",
        data={"exit": 1, "stdout": ""},
        args={"path": "work/sq2.py"},
    )
    assert not failed.has_ok("run_script_ok")
    assert not failed.has_ok("calc")

    ran = EvidenceLedger()
    ran.record_tool(
        "run_script",
        ok=True,
        output="exit: 0\n\nstdout:\n144",
        data={"exit": 0, "stdout": "144"},
        args={"path": "work/sq2.py"},
    )
    assert ran.has_ok("run_script_ok")
    assert ran.has_ok("calc")


@pytest.mark.asyncio
async def test_write_approved_run_skipped_python_144_is_not_a_run() -> None:
    """P05: write allowed, run_script skipped, python printed 144."""
    workspace = _WorkspaceStub()
    python = _PythonStub()
    script = _RunScriptStub(ok=True)
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
            [_call("run_script", {"path": "work/sq2.py"})],
            [_call("python", {"code": "print(12*12)"})],
            [("token", _CLAIM)],
        ]
    )
    bus = EventBus()
    loop = _loop(router, workspace, script, python, confirm=_allow_write_skip_run)
    loop.bus = bus
    events = await _collect(bus, loop.run(_P05, "fast"))
    payload = _done(events)
    text = str(payload["text"])
    assert workspace.runs == 1
    assert script.runs == 0
    assert python.runs == 1
    assert text == "\n".join((_WROTE, _SKIPPED, _PYTHON))
    assert _CLAIM not in text
    assert payload.get("unverified") == ["run_script"]


@pytest.mark.asyncio
async def test_run_script_error_is_not_a_run() -> None:
    """A failed run replaces the reply with the same three state lines."""
    workspace = _WorkspaceStub()
    python = _PythonStub()
    script = _RunScriptStub(ok=False)
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
            [_call("run_script", {"path": "work/sq2.py"})],
            [_call("python", {"code": "print(12*12)"})],
            [("token", _CLAIM)],
        ]
    )
    bus = EventBus()
    loop = _loop(router, workspace, script, python, confirm=_allow)
    loop.bus = bus
    events = await _collect(bus, loop.run(_P05, "fast"))
    payload = _done(events)
    text = str(payload["text"])
    assert workspace.runs == 1
    assert script.runs == 1
    assert python.runs == 1
    assert text == "\n".join((_WROTE, _FAILED, _PYTHON))
    assert _CLAIM not in text
    assert payload.get("unverified") == ["run_script"]


@pytest.mark.asyncio
async def test_write_and_memory_save_are_both_listed_when_the_run_is_skipped() -> None:
    """Successes come from the ledger. The model's sentence does not ship."""
    workspace = _WorkspaceStub()
    memory = _MemoryStub()
    script = _RunScriptStub(ok=True)
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
            [_call("memory", {"action": "remember", "fact": _FACT})],
            [_call("run_script", {"path": "work/sq2.py"})],
            [("token", _CLAIM)],
        ]
    )
    bus = EventBus()
    loop = _loop(
        router, workspace, memory, script, confirm=_allow_write_skip_run
    )
    loop.bus = bus
    events = await _collect(bus, loop.run(_P05, "fast"))
    payload = _done(events)
    text = str(payload["text"])
    assert workspace.runs == 1
    assert memory.runs == 1
    assert script.runs == 0
    assert text == "\n".join((_WROTE, _SAVED, _SKIPPED))
    assert _CLAIM not in text
    assert payload.get("unverified") == ["run_script"]


@pytest.mark.asyncio
async def test_run_script_success_adds_no_not_run_line() -> None:
    """A successful run_script result is the warrant. No line is added."""
    script = _RunScriptStub(ok=True)
    router = _ScriptedRouter(
        [
            [_call("run_script", {"path": "work/sq2.py"})],
            [("token", "It prints 144.")],
        ]
    )
    bus = EventBus()
    loop = _loop(router, script, confirm=_allow)
    loop.bus = bus
    events = await _collect(
        bus,
        loop.run("Call run_script on work/sq2.py and tell me the output.", "fast"),
    )
    payload = _done(events)
    text = str(payload["text"])
    assert script.runs == 1
    assert text.strip() == "It prints 144."
    assert "unverified" not in payload
