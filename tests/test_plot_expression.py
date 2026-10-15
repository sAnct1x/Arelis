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

import pytest

from arelis.tools.plot import sample_expression


def test_a_second_variable_is_refused_rather_than_guessed() -> None:
    """Picking a value for y to plot x*y would be inventing data."""
    with pytest.raises(ValueError, match="one variable"):
        sample_expression("x*y", lo=0.0, hi=1.0, samples=10)


def test_an_empty_or_backwards_range_is_refused() -> None:
    with pytest.raises(ValueError, match="xmin"):
        sample_expression("x", lo=1.0, hi=1.0, samples=5)
    with pytest.raises(ValueError, match="xmin"):
        sample_expression("x", lo=2.0, hi=1.0, samples=5)


def test_an_expression_that_is_all_asymptote_is_refused() -> None:
    with pytest.raises(ValueError, match="finite"):
        sample_expression("log(x)", lo=-5.0, hi=-1.0, samples=20)


def _ensure(path):
    path.mkdir(parents=True, exist_ok=True)
    return path


