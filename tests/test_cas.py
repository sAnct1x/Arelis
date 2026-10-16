"""CAS must not pin the glass. SymPy integrate is not interruptible in-thread."""

from __future__ import annotations

import sys
import time

import pytest

from arelis.tools import cas
from arelis.tools.cas import CasTool, _CasResult, _run_in_process


def _hang_in_child(queue, *args) -> None:
    time.sleep(30)


def _reply_in_child(queue, *args) -> None:
    queue.put(("ok", "x**3/3", r"\frac{x^{3}}{3}", "x**3/3", False))


def _parse_error_in_child(queue, *args) -> None:
    queue.put(("err", "ValueError", "only numbers and names are allowed"))


def test_cas_timeout_kills_the_worker() -> None:
    start = time.monotonic()
    with pytest.raises(TimeoutError, match="cas timeout"):
        _run_in_process(_hang_in_child, timeout=0.4)
    assert time.monotonic() - start < 4.0


@pytest.mark.asyncio
async def test_cas_definite_ln_over_one_plus_x_squared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[0,1] of ln(1+x)/(1+x^2) is π ln(2)/8 — not a dilog hunt."""
    import arelis.tools.cas as cas

    spawned: list[str] = []

    def _no_spawn(*_args: object, **_kwargs: object) -> _CasResult:
        spawned.append("spawn")
        raise AssertionError("definite identify must not spawn integrate()")

    monkeypatch.setattr(cas, "_run_in_process", _no_spawn)
    result = await CasTool().run(
        action="integrate",
        expr="log(1+x)/(1+x**2)",
        wrt="x",
        lo="0",
        hi="1",
    )
    assert result.ok
    assert spawned == []
    closed = str(result.data.get("result") or "")
    assert "pi" in closed.lower()
    assert "log" in closed.lower()
    assert "8" in closed


@pytest.mark.serial
@pytest.mark.asyncio
async def test_cas_fiftieth_derivative_is_minus_fifty_factorial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The closed form, not the 8s quiet-process budget.

    Serial: the 8s budget is the real one, and an xdist worker does not
    have a quiet machine to spend it on.

    Windows: the serial step on the hosted Windows runners still ran out
    of the 8s budget on this diff, so the budget is doubled there only.
    """
    if sys.platform == "win32":
        monkeypatch.setattr(cas, "_TIMEOUT_S", cas._TIMEOUT_S * 2)
    result = await CasTool().run(
        action="diff",
        expr="1/(x**2-1)",
        wrt="x",
        n=50,
        at="0",
    )
    assert result.ok
    closed = str(result.data.get("result") or "")
    latex = str(result.data.get("latex") or "")
    blob = closed + latex
    assert "50!" in blob or "factorial(50)" in blob
    assert "-" in blob


@pytest.mark.asyncio
async def test_cas_hundredth_derivative_at_zero() -> None:
    result = await CasTool().run(
        action="diff",
        expr="x**2 * e**(2*x)",
        wrt="x",
        n=100,
        at="0",
    )
    assert result.ok
    closed = str(result.data.get("result") or "").replace(" ", "")
    assert "log" not in closed.lower()
    assert "2**100" in closed or "2**98" in closed


@pytest.mark.asyncio
async def test_cas_integrate_x_squared() -> None:
    result = await CasTool().run(action="integrate", expr="x**2", wrt="x")
    assert result.ok
    assert "x**3" in str(result.data.get("result", ""))


