"""MCMC-style cell saves samples; plot draws a posterior from that file."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.core.cell_work import cell_work_dir
from arelis.tools.plot import PlotTool
from arelis.tools.python_exec import PythonTool
from arelis.workspace import WorkspaceRoots


@pytest.mark.asyncio
async def test_mcmc_cell_saves_samples_and_plot_draws_posterior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setenv("ARELIS_DATA_DIR", str(data))
    roots = WorkspaceRoots.from_paths([str(project)])
    tool = PythonTool(roots)
    saved = await tool.run(
        code=(
            "import numpy as np\n"
            "rng = np.random.default_rng(0)\n"
            "walk = np.zeros(64)\n"
            "for i in range(1, 64):\n"
            "    walk[i] = walk[i - 1] + rng.normal()\n"
            "samples = np.column_stack([walk, walk + rng.normal(size=64)])\n"
            "np.save('samples.npy', samples)\n"
            "print('saved', int(samples.shape[0]))\n"
        )
    )
    assert saved.ok, saved.output
    assert "saved" in saved.output
    npy = cell_work_dir() / "samples.npy"
    assert npy.is_file()

    chart = await PlotTool(roots).run(
        action="scatter", path="samples.npy", x="0", y="1", out="posterior.png"
    )
    assert chart.ok, chart.output
    assert Path(chart.data["abs_path"]).is_file()
