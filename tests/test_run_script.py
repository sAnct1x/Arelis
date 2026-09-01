"""Project .py runner — sandbox, argv, timeout, confirm, jobs omit."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from arelis.tools import build_tool_registry
from arelis.tools.policy import evaluate_confirm, set_confirm_mode
from arelis.tools.run_script import RunScriptTool, resolve_interpreter
from arelis.workspace import RootEntry, WorkspaceRoots


def _tool(tmp_path: Path, **kwargs) -> RunScriptTool:
    roots = WorkspaceRoots.from_paths([str(tmp_path)])
    return RunScriptTool(roots, **kwargs)


@pytest.mark.asyncio
async def test_runs_a_script_and_returns_stdout(tmp_path: Path) -> None:
    script = tmp_path / "hello.py"
    script.write_text("print('drift 1.2')\n", encoding="utf-8")
    result = await _tool(tmp_path).run(path="hello.py")
    assert result.ok, result.output
    assert "drift 1.2" in result.output
    assert result.data.get("exit") == 0


@pytest.mark.asyncio
async def test_args_stay_argv_not_a_pipe(tmp_path: Path) -> None:
    script = tmp_path / "echo.py"
    script.write_text(
        "import sys\nprint(repr(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    result = await _tool(tmp_path).run(path="echo.py", args=["hello | world"])
    assert result.ok, result.output
    assert "hello | world" in result.output


@pytest.mark.asyncio
async def test_refuses_non_py(tmp_path: Path) -> None:
    bat = tmp_path / "go.bat"
    bat.write_text("echo no\n", encoding="utf-8")
    result = await _tool(tmp_path).run(path="go.bat")
    assert not result.ok
    assert "not a shell" in result.output.lower()


@pytest.mark.asyncio
async def test_refuses_missing_file(tmp_path: Path) -> None:
    result = await _tool(tmp_path).run(path="gone.py")
    assert not result.ok
    assert "not a file" in result.output.lower()


@pytest.mark.asyncio
async def test_refuses_path_escape(tmp_path: Path, monkeypatch) -> None:
    outside = tmp_path.parent / "outside_run.py"
    outside.write_text("print('escaped')\n", encoding="utf-8")
    result = await _tool(tmp_path).run(path=str(outside))
    assert not result.ok
    assert "outside" in result.output.lower() or "path error" in result.output.lower()


@pytest.mark.asyncio
async def test_refuses_read_only_root(tmp_path: Path) -> None:
    script = tmp_path / "ok.py"
    script.write_text("print(1)\n", encoding="utf-8")
    workspace = WorkspaceRoots(
        [RootEntry(name="lab", path=tmp_path.resolve(), read_only=True)]
    )
    tool = RunScriptTool(workspace)
    result = await tool.run(path="ok.py")
    assert not result.ok
    assert "read-only" in result.output.lower()


@pytest.mark.asyncio
async def test_timeout_kills_a_sleep(tmp_path: Path) -> None:
    script = tmp_path / "sleep.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    result = await _tool(tmp_path).run(path="sleep.py", timeout_s=1)
    assert not result.ok
    assert "timed out" in result.output.lower()


@pytest.mark.asyncio
async def test_nonzero_exit_keeps_output(tmp_path: Path) -> None:
    script = tmp_path / "fail.py"
    script.write_text("import sys\nprint('nope')\nsys.exit(2)\n", encoding="utf-8")
    result = await _tool(tmp_path).run(path="fail.py")
    assert not result.ok
    assert "nope" in result.output
    assert "exit: 2" in result.output


def test_interpreter_prefers_project_venv(tmp_path: Path) -> None:
    fake = tmp_path / ".venv" / "Scripts" / "python.exe"
    fake.parent.mkdir(parents=True)
    fake.write_text("", encoding="utf-8")
    assert resolve_interpreter(tmp_path, None) == str(fake.resolve())
    assert resolve_interpreter(tmp_path, None) != sys.executable


def test_registry_attended_only(tmp_path: Path) -> None:
    config = {"tools": {}, "agent": {}, "workspace": {"roots": [str(tmp_path)]}}
    attended = build_tool_registry(config, attended=True)
    jobs = build_tool_registry(config, allow_send=False)
    assert attended.get("run_script") is not None
    assert jobs.get("run_script") is None


def test_confirm_card_and_voice(tmp_path: Path) -> None:
    config = {"tools": {}, "agent": {}, "workspace": {"roots": [str(tmp_path)]}}
    registry = build_tool_registry(config, attended=True)
    args = {"path": "x.py"}
    set_confirm_mode("card")
    assert registry.needs_confirm("run_script", args, confirm_run=True)
    assert not registry.needs_confirm("run_script", args, confirm_run=False)
    set_confirm_mode("voice")
    try:
        assert evaluate_confirm("run_script", args, risk="side_effect")
        assert registry.needs_confirm("run_script", args, confirm_run=False)
    finally:
        set_confirm_mode("card")
