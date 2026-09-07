"""CAS must not pin the glass. SymPy integrate is not interruptible in-thread."""

from __future__ import annotations

import asyncio
import time

import pytest

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


def test_cas_process_returns_the_packed_result() -> None:
    result = _run_in_process(_reply_in_child, timeout=5)
    assert result.ascii == "x**3/3"
    assert result.latex == r"\frac{x^{3}}{3}"
    assert not result.unevaluated


def test_cas_process_reraises_parse_errors() -> None:
    with pytest.raises(ValueError, match="only numbers"):
        _run_in_process(_parse_error_in_child, timeout=5)


@pytest.mark.asyncio
async def test_cas_run_leaves_the_event_loop_free(monkeypatch: pytest.MonkeyPatch) -> None:
    import arelis.tools.cas as cas

    def _block(_action: str, _expr: str, **_kwargs: object) -> _CasResult:
        time.sleep(0.3)
        return _CasResult("1", ascii="1", latex="1")

    monkeypatch.setattr(cas, "_run_timed", _block)
    ticks: list[float] = []

    async def heartbeat() -> None:
        for _ in range(6):
            ticks.append(time.monotonic())
            await asyncio.sleep(0.05)

    result, _ = await asyncio.gather(CasTool().run(expr="x**2"), heartbeat())
    assert result.ok
    assert len(ticks) >= 4


@pytest.mark.asyncio
async def test_cas_solve_stays_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    import arelis.tools.cas as cas

    spawned: list[str] = []

    def _no_spawn(*_args: object, **_kwargs: object) -> _CasResult:
        spawned.append("spawn")
        return _CasResult("[-5, 2]", ascii="[-5, 2]", latex="[-5, 2]")

    monkeypatch.setattr(cas, "_run_in_process", _no_spawn)
    result = await CasTool().run(
        action="solve", expr="x**2 + 3*x - 10 = 0", symbol="x"
    )
    assert result.ok
    assert spawned == []
    assert "2" in str(result.data.get("result", ""))


@pytest.mark.asyncio
async def test_cas_timeout_does_not_claim_none_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import arelis.tools.cas as cas

    def _boom(*_args: object, **_kwargs: object) -> _CasResult:
        raise TimeoutError("cas timeout")

    monkeypatch.setattr(cas, "_run_timed", _boom)
    result = await CasTool().run(
        action="integrate", expr="log(1+x)/(1+x**2)", lo="0", hi="1"
    )
    assert not result.ok
    assert "not a proof" in result.output.lower()
    assert "usually means" not in result.output.lower()


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


@pytest.mark.asyncio
async def test_cas_fiftieth_derivative_is_minus_fifty_factorial() -> None:
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


@pytest.mark.asyncio
async def test_cas_limit_sinc_is_one() -> None:
    result = await CasTool().run(
        action="limit", expr="sin(x)/x", wrt="x", at="0"
    )
    assert result.ok
    assert str(result.data.get("result") or "").strip() == "1"


@pytest.mark.asyncio
async def test_cas_sum_one_to_hundred() -> None:
    result = await CasTool().run(
        action="sum", expr="k", wrt="k", lo="1", hi="100"
    )
    assert result.ok
    assert "5050" in str(result.data.get("result") or "")


@pytest.mark.asyncio
async def test_cas_gaussian_integral_is_sqrt_pi() -> None:
    result = await CasTool().run(
        action="integrate", expr="exp(-x**2)", wrt="x", lo="-inf", hi="inf"
    )
    assert result.ok
    closed = str(result.data.get("result") or "").replace(" ", "").lower()
    assert "erf" not in closed
    assert "sqrt(pi)" in closed or "pi**" in closed


@pytest.mark.asyncio
async def test_cas_factor_difference_of_cubes() -> None:
    result = await CasTool().run(action="factor", expr="x**3 - 8")
    assert result.ok
    closed = str(result.data.get("result") or "").replace(" ", "")
    assert "x-2" in closed or "x - 2" in str(result.data.get("result") or "")


@pytest.mark.asyncio
async def test_cas_simplify_factor_call_in_expr() -> None:
    """The 9B wraps factor() inside simplify when action=factor is new."""
    result = await CasTool().run(action="simplify", expr="factor(x**2 - 9)")
    assert result.ok
    blob = str(result.data.get("result") or "")
    assert "x - 3" in blob or "x-3" in blob.replace(" ", "")


@pytest.mark.asyncio
async def test_cas_dsolve_sho_from_prime_notation() -> None:
    result = await CasTool().run(action="dsolve", expr="y'' + y = 0")
    assert result.ok
    blob = str(result.data.get("result") or "").lower()
    assert "sin" in blob
    assert "cos" in blob


@pytest.mark.asyncio
async def test_cas_ln_over_quad_zero_to_inf_is_zero() -> None:
    result = await CasTool().run(
        action="integrate",
        expr="log(x)/(1+x**2)",
        wrt="x",
        lo="0",
        hi="inf",
    )
    assert result.ok
    closed = str(result.data.get("result") or "").replace(" ", "")
    assert closed in {"0", "0.0"}


@pytest.mark.asyncio
async def test_cas_directional_derivative_gemini_probe() -> None:
    """∇(x²y + y²z + z²x) at (1,-1,2) along ⟨1,2,-2⟩ is -14/3, not -14."""
    result = await CasTool().run(
        action="directional",
        expr="x**2 * y + y**2 * z + z**2 * x",
        wrt="x,y,z",
        at="1,-1,2",
        dir="1,2,-2",
    )
    assert result.ok
    closed = str(result.data.get("result") or "").replace(" ", "")
    latex = str(result.data.get("latex") or "").replace(" ", "")
    blob = closed + latex
    assert "-14/3" in blob
    assert closed.strip() != "-14"
