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
checked on the AST, before anything runs.
"""

from __future__ import annotations

import time
from itertools import pairwise

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
async def test_matplotlib_refusal_sets_next_tool_plot() -> None:
    """The next step is a field on the result, not a phrase in the sentence."""
    result = await PythonTool().run(code="import matplotlib")
    assert result.ok is False
    assert result.data.get("next_tool") == "plot"
    assert result.data.get("refusal") == "chart_import"


def test_chart_import_refusal_is_a_typed_error() -> None:
    from arelis.tools import python_cell_runner as runner

    kind = getattr(runner, "_ChartImportError", None)
    assert kind is not None
    with pytest.raises(kind) as caught:
        runner._import_refusal("matplotlib")
    assert caught.value.next_tool == "plot"
    assert caught.value.refusal == "chart_import"
    assert "call plot" in str(caught.value).lower()
    assert "compute xs" not in str(caught.value).lower()


def test_os_import_refusal_is_not_the_chart_marker() -> None:
    from arelis.tools import python_cell_runner as runner

    with pytest.raises(ValueError) as caught:
        runner._import_refusal("os")
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


