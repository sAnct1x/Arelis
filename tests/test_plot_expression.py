"""plot could not plot a function, which is the most obvious chart ask there is.

Found 2026-09-17 while sweeping the `ForceGate` table. The scripted board said
"plot the sine wave from 0 to 2pi" ended with no tool call, and the first guess
was a missing inject behind the nudge — the same hole `document` and
`diagnostics` had. It was not. Reading the schema, `plot` accepts a table path
plus column names, or `xs`/`ys` as *literal comma-separated numbers*, and the
description ends "This is not Python: do not pass code or matplotlib".

So there was no argument shape that draws sin(x). The only way to satisfy the
ask was for the model to hand-type a few hundred sine values into `ys=`, which
is both wrong and exactly the invent-the-data failure the tool exists to
prevent. A nudge cannot fix that and an inject would have had to fabricate the
numbers. The tool was too shallow to finish the job.

The evaluator deliberately reuses `cas.parse_cas_expr` rather than growing a
second expression parser here. That function is the hardened one: it whitelists
an AST, then parses into a locked namespace with empty builtins. A fresh
`eval`, or `sympify` on raw text, would have been a sandbox escape in a tool
that any turn can reach.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from arelis.tools.plot import PlotTool, plot_range_value, sample_expression


def test_a_sine_wave_is_actually_sampled() -> None:
    x, y = sample_expression("sin(x)", lo=0.0, hi=2 * math.pi, samples=400)

    assert len(x) == len(y) == 400
    assert x[0] == pytest.approx(0.0)
    assert x[-1] == pytest.approx(2 * math.pi)
    # The shape, not just the length: peak near pi/2, trough near 3pi/2.
    assert y.max() == pytest.approx(1.0, abs=1e-3)
    assert y.min() == pytest.approx(-1.0, abs=1e-3)
    assert float(y[int(len(y) * 0.25)]) == pytest.approx(1.0, abs=1e-2)


def test_the_range_can_be_written_the_way_people_say_it() -> None:
    """ "0 to 2pi" is the ask; requiring 6.283185 defeats the point."""
    assert plot_range_value("2pi", name="xmax") == pytest.approx(2 * math.pi)
    assert plot_range_value("pi/2", name="xmax") == pytest.approx(math.pi / 2)
    assert plot_range_value("-1", name="xmin") == pytest.approx(-1.0)
    assert plot_range_value("1e3", name="xmax") == pytest.approx(1000.0)


def test_a_caret_means_a_power_here_like_it_does_in_cas() -> None:
    _x, y = sample_expression("x^2", lo=0.0, hi=3.0, samples=4)
    assert list(y) == pytest.approx([0.0, 1.0, 4.0, 9.0])


def test_an_asymptote_does_not_kill_the_chart() -> None:
    """1/x over a range containing 0 must drop the blow-up, not raise."""
    x, y = sample_expression("1/x", lo=-1.0, hi=1.0, samples=101)

    assert len(x) == len(y)
    assert len(x) > 50, "almost everything was thrown away"
    assert np.isfinite(y).all(), "a non-finite value survived into the chart"


def test_a_second_variable_is_refused_rather_than_guessed() -> None:
    """Picking a value for y to plot x*y would be inventing data."""
    with pytest.raises(ValueError, match="one variable"):
        sample_expression("x*y", lo=0.0, hi=1.0, samples=10)


def test_a_constant_still_draws() -> None:
    _x, y = sample_expression("3", lo=0.0, hi=1.0, samples=5)
    assert list(y) == pytest.approx([3.0] * 5)


@pytest.mark.parametrize(
    "hostile",
    [
        '__import__("os").system("echo hi")',
        "open('/etc/passwd').read()",
        "().__class__.__bases__",
        "lambda: 1",
        "[x for x in range(3)]",
    ],
)
def test_the_expression_is_not_a_python_escape_hatch(hostile: str) -> None:
    """Inherited from cas.parse_cas_expr's AST whitelist, and it must stay that way.

    This is the test that matters most in the file. `plot` is reachable from any
    turn, so an expression field that reached `eval` would be remote code
    execution behind a chart request.
    """
    with pytest.raises(ValueError):
        sample_expression(hostile, lo=0.0, hi=1.0, samples=5)


def test_an_empty_or_backwards_range_is_refused() -> None:
    with pytest.raises(ValueError, match="xmin"):
        sample_expression("x", lo=1.0, hi=1.0, samples=5)
    with pytest.raises(ValueError, match="xmin"):
        sample_expression("x", lo=2.0, hi=1.0, samples=5)


def test_the_sample_count_is_bounded() -> None:
    """A model asking for ten million points must not hang the GUI thread."""
    x, _y = sample_expression("x", lo=0.0, hi=1.0, samples=10_000_000)
    assert len(x) <= 5000


def test_an_expression_that_is_all_asymptote_is_refused() -> None:
    with pytest.raises(ValueError, match="finite"):
        sample_expression("log(x)", lo=-5.0, hi=-1.0, samples=20)


@pytest.mark.asyncio
async def test_a_formula_ask_writes_a_real_png(tmp_path, monkeypatch) -> None:
    """End to end, because nothing else in the suite runs plot.run at all.

    Every other plot test checks copy, policy or intent routing. A tool whose
    entire job is writing a file had no test that it writes one, which is how a
    missing argument shape survived this long.
    """
    from arelis.workspace import RootEntry, WorkspaceRoots

    root = tmp_path / "proj"
    root.mkdir()
    drop = tmp_path / "drop"
    tool = PlotTool(WorkspaceRoots([RootEntry(name="proj", path=root.resolve())]))
    monkeypatch.setattr(tool, "drop_dir", lambda: _ensure(drop))

    result = await tool.run(action="line", expr="sin(x)", xmin="0", xmax="2pi", out="sine.png")

    assert result.ok, result.output
    written = drop / "sine.png"
    assert written.is_file(), "the chart was reported but not written"
    assert written.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    assert "400 points" in result.output


def _ensure(path):
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_the_schema_advertises_the_new_shape() -> None:
    props = PlotTool.parameters_schema["properties"]
    for key in ("expr", "xmin", "xmax", "samples", "var"):
        assert key in props, f"{key} is not offered to the model"
    assert "expr" in PlotTool.description
    # The old warning must not survive next to a field that takes an expression.
    assert "do not pass code" in PlotTool.description
    assert "histogram" in props["action"]["enum"]
