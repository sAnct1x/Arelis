"""The 9B sends linspace/sin,cos. A traceback then a silent think spiral is the hang.

Fail-before: on main this call is ok=False and the output is a Python traceback.
"""

from __future__ import annotations

import pytest

from tests.test_plot_charts import _tool


@pytest.mark.asyncio
async def test_nine_b_linspace_sine_cosine_draws_or_explains(
    tmp_path, monkeypatch
) -> None:
    """Same args as 9b-cold-r3. Must draw, or a one-line error the model can act on."""
    tool, drop = _tool(tmp_path, monkeypatch)

    result = await tool.run(
        action="line",
        xmin="0",
        xmax="6.283185307",
        xs="linspace(0, 2*pi, 100)",
        ys="sin(x), cos(x)",
        title="Sine and Cosine Functions",
        xlabel="x (radians)",
        ylabel="y",
        out="sine_cosine.png",
    )

    assert "Traceback" not in result.output
    assert result.ok, result.output
    png = drop / "sine_cosine.png"
    assert png.is_file()
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    no_bounds = await tool.run(
        action="line",
        xs="linspace(0, 2*pi, 80)",
        ys="sin(x)",
        out="sine_only.png",
    )
    assert no_bounds.ok, no_bounds.output
    assert "Traceback" not in no_bounds.output

    counted = await tool.run(
        action="line",
        xs="arange(0, 1, 0.5)",
        ys="0, 1",
        out="arange.png",
    )
    assert counted.ok, counted.output
    assert "Traceback" not in counted.output

    bad = await tool.run(action="line", xs="1,2,3", ys="sin(x), cos(x)")
    assert not bad.ok
    assert "Traceback" not in bad.output
    assert "ys" in bad.output
    assert "expr=" in bad.output
    assert "xmax" in bad.output

    evil = await tool.run(
        action="line",
        xs="linspace(__import__('os').name, 1, 2)",
        ys="1,2",
        out="nope.png",
    )
    assert not evil.ok
    assert "Traceback" not in evil.output
    assert not (drop / "nope.png").is_file()
