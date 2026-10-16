"""python_exec had no tests at all, and three real sandbox escapes.

Found 2026-09-17 by listing tools that no test file so much as names. Three
came back: `html_text`, `image_io`, and this one — a tool whose whole job is
**executing code the model wrote**. It shipped with an AST whitelist, an import
allowlist, a forbidden-call list, a locked `__builtins__`, and zero tests to
say whether any of it held.

It did not. Probing it found three escapes, in descending order of severity:

1. **`sympy.sympify` is `eval`.** `sp.sympify("__import__('os').name")`
   returned `nt`. That is arbitrary import and attribute access, which is one
   short step from `.system(...)`. The AST gate never saw it because the
   payload is a *string constant*, and the gate inspects `Attribute` and
   `Name` nodes. Exactly the vulnerability proven by mutation in `plot.py`
   the same day — except there it was hypothetical and here it was live.

2. **`operator.attrgetter("__class__")` walks straight past the dunder rule**,
   for the same reason: a dunder spelled inside a string is a `Constant`.
   `attrgetter` is reachable because `operator` is preloaded in the namespace.

3. **`numpy.savetxt` writes files.** The module docstring says "os,
   subprocess, sockets, and files stay out". The probe wrote a real file to
   the repo root.

The fixes are two general rules rather than a longer denylist of modules:
string literals may not contain `__`, and a small set of attribute names that
mean "evaluate this text" or "touch the disk" may not be called. Both are
checked on the AST, before anything runs. numpy.savetxt and savefig are not
in that set. The hook allows them only when the path stays inside the room's
results folder.
"""

from __future__ import annotations

import time
from itertools import pairwise
from pathlib import Path

import pytest

from arelis.tools.python_exec import PythonTool


async def _run(code: str) -> tuple[bool, str]:
    result = await PythonTool().run(code=code)
    return bool(result.ok), str(result.output)


# --------------------------------------------------------------------------
# It has to actually work, or the hardening below is just breaking a tool
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Escape 1: sympify is eval
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Escape 2: a dunder hidden in a string
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Escape 3: the filesystem
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# The guards that already existed, now actually tested
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matplotlib_refusal_sets_next_tool_plot(tmp_path: Path) -> None:
    """Seaborn still points at plot. A corner figure may land in results."""
    from arelis.workspace import RootEntry, WorkspaceRoots

    result = await PythonTool().run(code="import seaborn")
    assert result.ok is False
    assert result.data.get("next_tool") == "plot"
    assert result.data.get("refusal") == "chart_import"
    loaded = await PythonTool().run(code="import emcee")
    assert loaded.ok is True
    assert loaded.data.get("refusal") is None

    root = tmp_path / "proj"
    root.mkdir()
    (root / "data.csv").write_text("1.5\n2.5\n", encoding="utf-8")
    tool = PythonTool(WorkspaceRoots([RootEntry(name="proj", path=root)]))
    results = root / "results"
    figure = results / "corner.png"
    table = results / "chain.txt"
    sheet = results / "rows.csv"
    npy = results / "chain.npy"
    saved = await tool.run(
        code=(
            "import csv\n"
            "import numpy as np\n"
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "import corner\n"
            f"seen = np.loadtxt({str(root / 'data.csv')!r})\n"
            f"np.savetxt({str(table)!r}, np.array([1.0, 2.0, 3.0]))\n"
            "loaded = np.loadtxt(" + repr(str(table)) + ")\n"
            f"np.save({str(npy)!r}, loaded)\n"
            "again = np.load(" + repr(str(npy)) + ")\n"
            f"with open({str(sheet)!r}, 'w', newline='') as handle:\n"
            "    csv.writer(handle).writerow(['a', 'b'])\n"
            "fig, ax = plt.subplots()\n"
            "ax.plot([1, 2], [3, 4])\n"
            f"fig.savefig({str(figure)!r})\n"
            "print('saved', float(seen[0]), float(again[0]))\n"
        )
    )
    assert saved.ok, saved.output
    assert figure.is_file() and figure.stat().st_size > 0
    assert table.is_file()
    assert sheet.is_file()
    assert npy.is_file()
    assert "saved" in saved.output
    backend = await tool.run(
        code="import matplotlib\nmatplotlib.use('TkAgg')\nprint(matplotlib.get_backend())"
    )
    assert backend.ok, backend.output
    assert "agg" in backend.output.lower()
    relative = await tool.run(
        code=(
            "import matplotlib.pyplot as plt\n"
            "fig, ax = plt.subplots()\n"
            "fig.savefig('fig.png')\n"
        )
    )
    assert relative.ok is False
    assert "results" in relative.output.lower()

    outside = tmp_path / "outside.csv"
    in_room = root / "side.csv"
    escaped = tmp_path / "escape.csv"
    link = results / "link.csv"
    link.symlink_to(outside)
    for target in (outside, in_room, results / ".." / "escape.csv", link):
        refused = await tool.run(
            code=f"import numpy as np\nnp.savetxt({str(target)!r}, np.array([1.0]))\n"
        )
        assert refused.ok is False, target
        assert "results" in refused.output.lower()
    assert not outside.exists()
    assert not in_room.exists()
    assert not escaped.exists()
    blocked = await tool.run(code="import subprocess\nsubprocess.call(['true'])")
    assert blocked.ok is False
    assert "subprocess" in blocked.output
    peeked = await tool.run(code="print(open('/etc/passwd').read(8))")
    assert peeked.ok is False
    assert "root:" not in peeked.output


def test_chart_import_refusal_is_a_typed_error() -> None:
    from arelis.tools import python_cell_runner as runner

    kind = getattr(runner, "_ChartImportError", None)
    assert kind is not None
    assert "matplotlib" in runner._ALLOWED_IMPORTS
    assert "corner" in runner._ALLOWED_IMPORTS
    assert "csv" in runner._ALLOWED_IMPORTS
    assert "matplotlib" not in runner._CHART_IMPORTS
    with pytest.raises(kind) as caught:
        runner._import_refusal("seaborn")
    assert caught.value.next_tool == "plot"
    assert caught.value.refusal == "chart_import"
    assert "call plot" in str(caught.value).lower()
    assert "compute xs" not in str(caught.value).lower()


def test_os_import_refusal_is_not_the_chart_marker() -> None:
    from arelis.tools import python_cell_runner as runner

    for name in ("os", "subprocess"):
        with pytest.raises(ValueError) as caught:
            runner._import_refusal(name)
        assert getattr(caught.value, "next_tool", None) != "plot"
        assert not isinstance(caught.value, runner._ChartImportError)


# --------------------------------------------------------------------------
# The cell has to die when it is stuck in C, and it has to die in a child
# --------------------------------------------------------------------------


async def _power_stall() -> tuple[bool, str, float]:
    """The integer power that held the GIL."""
    started = time.monotonic()
    ok, out = await _run("x = 7**(10**8)")
    return ok, out, time.monotonic() - started


def _max_gap(start: float, stamps: list[float], end: float) -> float:
    points = [start, *stamps, end]
    return max(b - a for a, b in pairwise(points))


