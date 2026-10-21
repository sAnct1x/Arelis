"""MCMC-style cell saves samples; plot draws a posterior from that file."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from arelis.core.cell_work import begin_cell_work, cell_work_dir
from arelis.core.claims import ExactnessNeed
from arelis.core.compact_prompt import skinny_description
from arelis.core.events import EventType
from arelis.core.evidence import EvidenceLedger
from arelis.core.loop_helpers import _exactness_finish_refuse
from arelis.core.turn_context import TurnContext
from arelis.core.turn_execute import execute_call
from arelis.core.turn_scratch import named_tools_owed
from arelis.tools.plot import PlotTool
from arelis.tools.python_exec import PythonTool
from arelis.ui.event_host import dispatch_event
from arelis.workspace import WorkspaceRoots
from tests.test_plot_in_chat import _chart_formats, _loaded


class _Bus:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def publish(self, event: object) -> None:
        self.events.append(event)


class _Run:
    def __init__(self) -> None:
        self.bus = _Bus()
        self.max_rounds = 3
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


@pytest.mark.asyncio
async def test_mcmc_cell_saves_samples_and_plot_draws_posterior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arelis_window, qt_app
) -> None:
    assert "savefig" in skinny_description("python")
    data = tmp_path / "data"
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setenv("ARELIS_DATA_DIR", str(data))
    begin_cell_work("mcmc")
    # An older png in this turn's folder must not be the chart that shows.
    (cell_work_dir() / "already.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    )
    roots = WorkspaceRoots.from_paths([str(project)])
    tool = PythonTool(roots, science_io=False)
    saved = await tool.run(
        code=(
            "import numpy as np\n"
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "rng = np.random.default_rng(0)\n"
            "walk = np.zeros(64)\n"
            "for i in range(1, 64):\n"
            "    walk[i] = walk[i - 1] + rng.normal()\n"
            "samples = np.column_stack([walk, walk + rng.normal(size=64)])\n"
            "np.save('samples.npy', samples)\n"
            "np.savetxt('samples.txt', samples)\n"
            "np.savetxt('samples.csv', samples)\n"
            "np.savetxt('mcmc_m.csv', samples, delimiter=',', header='m,c')\n"
            "fig, ax = plt.subplots()\n"
            "ax.scatter(samples[:, 0], samples[:, 1])\n"
            "fig.savefig('posterior.png')\n"
            "print('saved', int(samples.shape[0]))\n"
        )
    )
    assert saved.ok, saved.output
    assert "saved" in saved.output
    npy = cell_work_dir() / "samples.npy"
    assert npy.is_file()
    png = cell_work_dir() / "posterior.png"
    assert png.is_file()
    assert Path(saved.data["abs_path"]).resolve() == png.resolve()
    assert saved.data.get("path") == "posterior.png"

    ctx = TurnContext(text="draw the posterior", role="fast")
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
        "python",
        {"code": "print('already ran')"},
        summary="python",
        call_fp="python-mcmc",
        round_i=1,
        call_i=0,
        fanout_results={0: (4, saved)},
    )
    ready = [
        event
        for event in loop.bus.events
        if getattr(event, "type", None) == EventType.FILE_READY
    ]
    assert len(ready) == 1
    payload = ready[0].payload
    assert payload["source"] == "python"
    assert payload["kind"] == "plot"
    assert Path(str(payload["abs_path"])).resolve() == png.resolve()

    window = arelis_window()
    window.chat.begin_assistant()
    window.chat.append_delta("working")
    dispatch_event(window, ready[0])
    window.chat.finish_assistant("Here is the chart.")
    qt_app.processEvents()
    charts = _chart_formats(window.chat.view.document())
    assert len(charts) == 1
    loaded = _loaded(window.chat.view, charts[0])
    assert loaded is not None and not loaded.isNull()

    quiet = await tool.run(code="print('no figure')\n")
    assert quiet.ok, quiet.output
    await execute_call(
        loop,
        ctx,
        scratch,
        "python",
        {"code": "print('no figure')"},
        summary="python",
        call_fp="python-mcmc-2",
        round_i=2,
        call_i=0,
        fanout_results={0: (1, quiet)},
    )
    ready_after = [
        event
        for event in loop.bus.events
        if getattr(event, "type", None) == EventType.FILE_READY
    ]
    assert len(ready_after) == 1
    assert Path(str(ready_after[0].payload["abs_path"])).resolve() == png.resolve()

    ask = TurnContext(text="plot the posterior", role="fast")
    ask.available_all = {"plot", "python"}
    assert "plot" not in named_tools_owed(loop, ask)
    assert (
        _exactness_finish_refuse(
            "Here's the MCMC line fit. Median slope: 2.029.",
            exact_need=ExactnessNeed(
                False, False, False, False, needs_plot=True, kinds=("plot",)
            ),
            ledger=scratch.ledger,
            numeric_gate=True,
            evidence_gate=True,
        )
        is None
    )

    chart = await PlotTool(roots).run(
        action="scatter", path="samples.npy", x="0", y="1", out="from-npy.png"
    )
    assert chart.ok, chart.output
    assert Path(chart.data["abs_path"]).is_file()

    from_txt = await PlotTool(roots).run(
        action="scatter", path="samples.txt", x="0", y="1", out="from-txt.png"
    )
    assert from_txt.ok, from_txt.output
    assert Path(from_txt.data["abs_path"]).is_file()

    from_csv = await PlotTool(roots).run(
        action="scatter", path="samples.csv", x="0", y="1", out="from-csv.png"
    )
    assert from_csv.ok, from_csv.output
    assert Path(from_csv.data["abs_path"]).is_file()

    named = await PlotTool(roots).run(
        action="scatter", path="mcmc_m.csv", x="m", y="c", out="from-named.png"
    )
    assert named.ok, named.output
    assert Path(named.data["abs_path"]).is_file()
