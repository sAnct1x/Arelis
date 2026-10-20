"""The python cell may write samples.npy into this turn's work folder.

Fail-before: on main, np.save/savez is refused as a disk touch ('use the
workspace tool for files') so sampler output never reaches plot.

Mutants this file is supposed to catch:

1. Containment skipped: `../escape.npy` or an absolute path writes outside
   the work folder.
2. Extension check removed: `pwn.exe` is written.
3. Size cap removed: a file over 50 MB is left on disk.
4. Overwrite allowed: a file the cell did not write this turn is replaced.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.core.cell_work import cell_work_dir
from arelis.paths import outputs_dir
from arelis.tools.analyze import AnalyzeTool
from arelis.tools.plot import PlotTool
from arelis.tools.python_exec import PythonTool
from arelis.workspace import WorkspaceRoots

# Same 50 MB file cap the cell enforces. Imported from the runner after the
# constant exists; inlined here so fail-before on main still collects.
_FILE_MAX = 50 * 1024 * 1024


def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WorkspaceRoots:
    data = tmp_path / "data"
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setenv("ARELIS_DATA_DIR", str(data))
    return WorkspaceRoots.from_paths([str(project)])


@pytest.mark.asyncio
async def test_cell_saves_samples_npy_readable_and_refuses_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots = _project(tmp_path, monkeypatch)
    tool = PythonTool(roots)
    docs = outputs_dir() / "documents"
    docs.mkdir(parents=True, exist_ok=True)
    user_drop = docs / "samples.npy"
    user_drop.write_bytes(b"user-drop")

    saved = await tool.run(
        code=(
            "import numpy as np\n"
            "np.save('samples.npy', np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]))\n"
            "print('saved')\n"
        )
    )
    assert saved.ok, saved.output
    work = cell_work_dir()
    npy = work / "samples.npy"
    assert npy.is_file()
    assert user_drop.read_bytes() == b"user-drop"
    assert npy.resolve() != user_drop.resolve()

    summary = AnalyzeTool(roots)._analyze("samples.npy", "summary", 5)
    assert summary.ok, summary.output
    assert "3 rows" in summary.output

    via_work = AnalyzeTool(roots)._analyze("work/samples.npy", "summary", 5)
    assert via_work.ok, via_work.output
    assert "3 rows" in via_work.output

    chart = await PlotTool(roots).run(
        action="scatter", path="samples.npy", x="0", y="1", out="posterior.png"
    )
    assert chart.ok, chart.output
    assert Path(chart.data["abs_path"]).is_file()

    planted = work / "keep.npy"
    planted.write_bytes(b"already-here")
    clobber = await tool.run(
        code="import numpy as np\nnp.save('keep.npy', np.array([9.0]))\n"
    )
    assert clobber.ok is False, clobber.output
    assert planted.read_bytes() == b"already-here"

    again = await tool.run(
        code="import numpy as np\nnp.save('samples.npy', np.array([[1.0, 2.0]]))\n"
    )
    assert again.ok, again.output

    fig = await tool.run(
        code="import matplotlib.pyplot as plt\nplt.savefig('fig.png')\n"
    )
    assert fig.ok is False, fig.output

    outside = tmp_path / "escape.npy"
    escaped = await tool.run(
        code=f"import numpy as np\nnp.save({str(outside)!r}, np.array([1.0]))\n"
    )
    assert escaped.ok is False, escaped.output
    assert not outside.exists()

    parented = await tool.run(
        code="import numpy as np\nnp.save('../escape.npy', np.array([1.0]))\n"
    )
    assert parented.ok is False, parented.output
    assert not (outputs_dir() / "escape.npy").exists()
    assert not (outputs_dir() / "work" / "escape.npy").exists()

    evil = await tool.run(
        code="import numpy as np\nnp.save('pwn.exe', np.array([1.0]))\n"
    )
    assert evil.ok is False, evil.output
    assert "npy" in evil.output.lower()
    assert not (work / "pwn.exe").exists()

    n_over = _FILE_MAX // 8 + 4096
    huge = await tool.run(
        code=f"import numpy as np\nnp.save('big.npy', np.ones({n_over}))\n"
    )
    assert huge.ok is False, huge.output
    assert "50" in huge.output
    assert not (work / "big.npy").exists()
