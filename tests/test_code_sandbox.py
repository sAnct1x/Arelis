"""run_script code=: Python runs free in a sandbox and asks before it changes
the user's files (policy A5). docs/code-sandbox.md says what is enforced."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from arelis.core.cell_work import begin_cell_work, cell_work_dir
from arelis.core.events import EventType
from arelis.core.evidence import EvidenceLedger
from arelis.core.turn_context import TurnContext
from arelis.core.turn_execute import execute_call
from arelis.tools.base import ToolRegistry
from arelis.tools.run_script import RunScriptTool
from tests.test_python_cell_work_write import _Run


def _tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, turn: str) -> tuple[RunScriptTool, ToolRegistry]:
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "data"))
    begin_cell_work(turn)
    project = tmp_path / "proj"
    project.mkdir()
    tool = RunScriptTool([str(project)])
    registry = ToolRegistry()
    registry.register(tool)
    return tool, registry


@pytest.mark.asyncio
async def test_sandbox_code_runs_without_a_card_in_the_work_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool, registry = _tool(tmp_path, monkeypatch, "sbx-run")
    args = {"code": "open('fit.txt', 'w').write('2.0')\nprint(3 * 7)\n"}
    assert registry.needs_confirm("run_script", args) is False
    result = await tool.run(**args)
    assert result.ok, result.output
    assert "21" in result.output
    assert (cell_work_dir() / "fit.txt").read_text() == "2.0"


@pytest.mark.asyncio
async def test_outside_write_is_refused_then_asks_then_writes_only_that_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool, registry = _tool(tmp_path, monkeypatch, "sbx-ask")
    his = tmp_path / "his" / "notes.txt"
    his.parent.mkdir()
    args = {"code": f"open({str(his)!r}, 'w').write('new')\nprint('done')\n"}

    first = await tool.run(**args)
    assert not first.ok
    assert not his.exists()
    assert str(his.resolve()) in first.output

    assert registry.needs_confirm("run_script", args) is True
    assert str(his.resolve()) in registry.describe_call("run_script", args)
    approved = await tool.run(**args)
    assert approved.ok, approved.output
    assert his.read_text() == "new"
    # The grant was for that one run.
    assert registry.needs_confirm("run_script", args) is False


@pytest.mark.asyncio
async def test_sandbox_has_no_network_and_starts_no_programs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool, _registry = _tool(tmp_path, monkeypatch, "sbx-net")
    net = await tool.run(
        code=(
            "import socket\n"
            "socket.create_connection(('203.0.113.7', 80), timeout=1)\n"
            "print('connected')\n"
        )
    )
    assert not net.ok
    assert "no network" in net.output
    assert "connected" not in net.output
    proc = await tool.run(
        code="import subprocess, sys\nsubprocess.run([sys.executable, '-c', 'print(5)'])\n"
    )
    assert not proc.ok
    assert "cannot start other programs" in proc.output


@pytest.mark.asyncio
async def test_sandbox_chart_shows_in_chat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool, _registry = _tool(tmp_path, monkeypatch, "sbx-chart")
    code = (
        "import matplotlib\nmatplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "plt.plot([0, 1, 2], [0, 1, 4])\nplt.savefig('curve.png')\nprint('ok')\n"
    )
    result = await tool.run(code=code)
    assert result.ok, result.output
    ctx = TurnContext(text="fit and plot it", role="fast")
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
        exact_need=ctx.exact_need,
        offer_tools=False,
        chat_tools=[],
        messages=[],
        sms_draft=None,
        email_draft=None,
    )
    loop = _Run()
    await execute_call(
        loop,
        ctx,
        scratch,
        "run_script",
        {"code": code},
        summary="run_script",
        call_fp="sbx-chart",
        round_i=1,
        call_i=0,
        fanout_results={0: (1, result)},
    )
    ready = [e for e in loop.bus.events if getattr(e, "type", None) == EventType.FILE_READY]
    assert len(ready) == 1
    assert Path(str(ready[0].payload["abs_path"])).name == "curve.png"
