"""Child scripts see a short environment, and one helper publishes tool results.

On main, run_script and run_task copy the process environment, the run card
only calls out deletes past the preview, and the login hop publishes a raw
TOOL_RESULT. These tests are the ones that fail there.
"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path

import pytest

from arelis.core.events import EventType
from arelis.core.turn_context import TurnContext
from arelis.core.turn_execute import _login_check_hop
from arelis.tools.base import ToolResult
from arelis.tools.child_proc import child_env
from arelis.tools.run_script import RunScriptTool
from arelis.tools.run_task import RunTaskTool
from arelis.workspace import WorkspaceRoots

_SECRET = "sk-live-abcdefghijklmnopqrstuvwx"
_ASSIGNMENT = "api_key=sk-live-abcdefghijklmnopqrstuvwx"
_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE = _ROOT / "arelis"
_HELPER = "arelis/core/tool_results.py"


def _roots(tmp_path: Path) -> WorkspaceRoots:
    return WorkspaceRoots.from_paths([str(tmp_path)], active=tmp_path.name)


def _leak(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARELIS_EMAIL_PASSWORD", "desk-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_not_for_a_child")


def _env_names(output: str) -> set[str]:
    tail = output.split("stdout:", 1)[-1]
    if "\nstderr:" in tail:
        tail = tail.split("\nstderr:", 1)[0]
    return {line.strip() for line in tail.splitlines() if line.strip()}


def _is_event_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "Event"
    return isinstance(func, ast.Attribute) and func.attr == "Event"


def _is_tool_result(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute) and node.attr == "TOOL_RESULT":
        base = node.value
        return isinstance(base, ast.Name) and base.id == "EventType"
    return False


def _tool_result_sites() -> list[str]:
    """Files that build a TOOL_RESULT event, outside the one helper."""
    hits: list[str] = []
    for path in sorted(_PACKAGE.rglob("*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_event_call(node):
                continue
            args = list(node.args)
            if node.keywords:
                for keyword in node.keywords:
                    if keyword.arg in {"type", "event_type"}:
                        args.append(keyword.value)
            if any(_is_tool_result(arg) for arg in args):
                hits.append(f"{rel}:{node.lineno}")
    return hits


async def test_login_hop_scrubs() -> None:
    """The sign-in hop used to publish the page, secrets and all."""

    class _Tools:
        async def call(self, name: str, **kwargs: object) -> ToolResult:
            del name, kwargs
            return ToolResult(
                ok=True,
                output=f"form\n{_ASSIGNMENT}",
                data={"body": _ASSIGNMENT, "url": "https://example.test/login"},
            )

    class _Bus:
        def __init__(self) -> None:
            self.events: list[object] = []

        async def publish(self, event: object) -> None:
            self.events.append(event)

    class _Loop:
        def __init__(self) -> None:
            self.bus = _Bus()
            self.tools = _Tools()
            self._timer = None
            self.agent_cfg: dict[str, object] = {}

        async def _finish(self, reply: str, sources: object, streamed: str = "") -> None:
            del reply, sources, streamed

    loop = _Loop()
    ctx = TurnContext(text="open the login page", role="fast")
    await _login_check_hop(
        loop,
        ctx,
        ctx.text,
        snapshot="",
        landed_url="https://example.test/home",
        sources=[],
    )
    results = [e for e in loop.bus.events if getattr(e, "type", None) == EventType.TOOL_RESULT]
    assert results, "the hop published no tool result"
    for event in results:
        blob = json.dumps(getattr(event, "payload", {}))
        assert _SECRET not in blob


async def test_restored_allow_scrubs(monkeypatch: pytest.MonkeyPatch) -> None:
    """A card brought back after restart used to publish the send raw."""
    from arelis.core.bus import EventBus
    from arelis.presence.pending_confirms import PendingConfirm
    from arelis.ui.confirm_host import emit_restored_confirm

    async def _fake(item: object, config: object) -> tuple[bool, str]:
        del item, config
        return True, f"sent {_ASSIGNMENT}"

    monkeypatch.setattr("arelis.ui.confirm_host.execute_pending_confirm", _fake)
    bus = EventBus()
    seen: list[object] = []

    async def _capture(event: object) -> None:
        seen.append(event)

    bus.subscribe(None, _capture)
    item = PendingConfirm(
        id="c-restored",
        tool="send_email",
        args={"to": "you@example.com"},
        summary="send the note",
    )
    runner = asyncio.create_task(bus.run())
    try:
        await emit_restored_confirm(bus, item, {})
        await bus.drain()
    finally:
        bus.stop()
        runner.cancel()
    results = [e for e in seen if getattr(e, "type", None) == EventType.TOOL_RESULT]
    assert results, "the restored card published no tool result"
    blob = json.dumps(results[-1].payload)
    assert _SECRET not in blob
    assert results[-1].payload.get("source") == "pending_confirm"


async def test_run_script_env_is_filtered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project script must not see mail passwords or tokens."""
    direct = child_env(
        {"GITHUB_TOKEN": "nope", "ARELIS_EMAIL_PASSWORD": "nope", "LANG": "C"}
    )
    assert "GITHUB_TOKEN" not in direct
    assert "ARELIS_EMAIL_PASSWORD" not in direct
    assert direct.get("LANG") == "C"
    _leak(monkeypatch)
    script = tmp_path / "envdump.py"
    script.write_text(
        "import os\nprint('\\n'.join(sorted(os.environ)))\n",
        encoding="utf-8",
    )
    tool = RunScriptTool(_roots(tmp_path))
    result = await tool.run(path="envdump.py")
    assert result.ok, result.output
    names = _env_names(result.output)
    assert "PATH" in names
    assert "ARELIS_EMAIL_PASSWORD" not in names
    assert "GITHUB_TOKEN" not in names

    (tmp_path / "arelis-tasks.json").write_text(
        json.dumps(
            {
                "env": [
                    "python",
                    "-c",
                    "import os; print('\\n'.join(sorted(os.environ)))",
                ]
            }
        ),
        encoding="utf-8",
    )
    task = RunTaskTool(_roots(tmp_path))
    ran = await task.run(action="run", name="env")
    assert ran.ok, ran.output
    task_names = _env_names(ran.output)
    assert "PATH" in task_names
    assert "ARELIS_EMAIL_PASSWORD" not in task_names
    assert "GITHUB_TOKEN" not in task_names


